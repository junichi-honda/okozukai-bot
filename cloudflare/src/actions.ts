import { approvedMessage, rejectedMessage } from './blocks';
import { decideRequest, getBalance, getRequest, insertLedger } from './db';
import { ephemeral, postMessage, respond } from './slack';
import { isApprover, type Env } from './types';

interface SlackBlock {
  type: string;
  elements?: { action_id?: string }[];
}

interface BlockActionsPayload {
  user: { id: string };
  response_url: string;
  actions: { action_id: string; value?: string }[];
  /** ボタンが載っていた元メッセージ(差し替え用) */
  message?: { text?: string; blocks?: SlackBlock[] };
}

const ackEmpty = () => new Response('', { status: 200 });

export function handleBlockActions(
  payload: BlockActionsPayload,
  env: Env,
  ctx: ExecutionContext,
): Response {
  const action = payload.actions?.[0];
  if (!action) return ackEmpty();

  const userId = payload.user.id;
  const responseUrl = payload.response_url;

  switch (action.action_id) {
    case 'approve':
    case 'reject':
      ctx.waitUntil(
        handleDecision(env, action.action_id, Number(action.value), userId, responseUrl),
      );
      break;
    case 'pay_all':
      ctx.waitUntil(handlePayAll(env, userId, responseUrl, payload.message));
      break;
  }

  return ackEmpty();
}

/** 仕様書 §9-2 / §9-3: 承認・却下 */
async function handleDecision(
  env: Env,
  actionId: 'approve' | 'reject',
  requestId: number,
  userId: string,
  responseUrl: string,
): Promise<void> {
  if (!isApprover(env, userId)) {
    await ephemeral(responseUrl, '承認・却下は保護者のみ実行できます。');
    return;
  }
  if (!Number.isInteger(requestId)) {
    await ephemeral(responseUrl, '申請 ID を特定できませんでした。');
    return;
  }

  const request = await getRequest(env, requestId);
  if (!request) {
    await ephemeral(responseUrl, 'この申請は見つかりませんでした。');
    return;
  }

  // 二重クリック防止: pending 以外は更新されない(仕様書 §10)
  const status = actionId === 'approve' ? 'approved' : 'rejected';
  const updated = await decideRequest(env, requestId, status, userId);
  if (!updated) {
    await ephemeral(responseUrl, 'この申請は既に処理済みです。');
    return;
  }

  if (actionId === 'approve') {
    await insertLedger(env, {
      type: 'earn_button',
      amount: request.amount,
      label: null, // 表示用のタスク名は requests.label を参照する(仕様書 §13)
      requestId,
      createdBy: userId,
    });
  }

  const balance = await getBalance(env);
  const message =
    actionId === 'approve'
      ? approvedMessage(request.label, request.amount, userId, balance)
      : rejectedMessage(request.label, request.amount, balance);

  await respond(responseUrl, { replace_original: true, ...message });
}

/**
 * 仕様書 §9-4: その時点の未払い残高を全額精算する。
 * チャンネル参加者が保護者2名のみのため権限チェックはしない。
 */
async function handlePayAll(
  env: Env,
  userId: string,
  responseUrl: string,
  message: BlockActionsPayload['message'],
): Promise<void> {
  const balance = await getBalance(env);

  if (balance <= 0) {
    // 残高0で押された場合も、押せてしまうボタンは残さず外す
    await replaceWithoutPayAllButton(
      responseUrl,
      message,
      '未払い残高は0円のため、支払い操作は行いませんでした。',
    );
    return;
  }

  await insertLedger(env, {
    type: 'payment',
    amount: -balance,
    label: '全額支払い',
    createdBy: userId,
  });

  // 押した本人のメッセージからボタンを外す(再度押せないようにする)
  await replaceWithoutPayAllButton(
    responseUrl,
    message,
    `💴 <@${userId}> が全額支払い済みにしました(${balance}円)`,
  );

  await postMessage(env, {
    text: `💴 全額支払い済みにしました(${balance}円)。未払い残高: 0円\n実行者: <@${userId}>`,
  });
}

/**
 * 元メッセージから pay_all ボタンの actions ブロックだけを取り除き、
 * 末尾に結果の一文を足して差し替える。
 */
async function replaceWithoutPayAllButton(
  responseUrl: string,
  message: BlockActionsPayload['message'],
  note: string,
): Promise<void> {
  const kept = (message?.blocks ?? []).filter(
    (block) =>
      !(
        block.type === 'actions' &&
        (block.elements ?? []).some((element) => element.action_id === 'pay_all')
      ),
  );

  const blocks = [
    ...kept,
    { type: 'context', elements: [{ type: 'mrkdwn', text: note }] },
  ];

  await respond(responseUrl, {
    replace_original: true,
    text: message?.text ?? note,
    blocks,
  });
}
