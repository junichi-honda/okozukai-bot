import {
  createRequest,
  getActiveTasks,
  getBalance,
  getBalanceAsOf,
  getLedgerRange,
  getTask,
  getTypeTotals,
  hasSameDayRequest,
  insertLedger,
  markRequestPostFailed,
  setRequestSlackTs,
} from './db';
import {
  configView,
  historyMessage,
  manualEntryMessage,
  requestMessage,
  taskEmoji,
} from './blocks';
import { ephemeral, postMessage, respond, slackApi } from './slack';
import { runMonthlySummary } from './summary';
import { jstParts, monthRange } from './time';
import { isApprover, type Env } from './types';

/** 明細を省略する件数のしきい値(仕様書 §13-3) */
const HISTORY_DETAIL_LIMIT = 20;

const USAGE = [
  '`/okozukai press A|B` — ボタン押下をシミュレート(申請を作成)',
  '`/okozukai add <金額> <メモ>` — 任意金額の追加・訂正(マイナス可、その場合メモ必須)',
  '`/okozukai config` — タスク名・金額・同日重複可否の変更',
  '`/okozukai history [YYYY-MM | YYYY-MM-DD YYYY-MM-DD]` — 記帳履歴',
  '`/okozukai summary` — 月末サマリを今すぐ投稿(cron の動作確認用)',
  '`/okozukai debug` — Bot Token の疎通確認',
].join('\n');

const ackEmpty = () => new Response('', { status: 200 });

export async function handleCommand(
  params: URLSearchParams,
  env: Env,
  ctx: ExecutionContext,
): Promise<Response> {
  const text = (params.get('text') ?? '').trim();
  const userId = params.get('user_id') ?? '';
  const responseUrl = params.get('response_url') ?? '';
  const triggerId = params.get('trigger_id') ?? '';

  const [sub, ...rest] = text.split(/\s+/).filter(Boolean);

  switch (sub) {
    case 'config':
      // trigger_id は数秒で失効するため waitUntil に回さず、その場で views.open する。
      await handleConfig(env, userId, triggerId, responseUrl);
      return ackEmpty();

    case 'press':
      ctx.waitUntil(handlePress(env, rest[0], responseUrl));
      return ackEmpty();

    case 'add':
      ctx.waitUntil(handleAdd(env, userId, rest, responseUrl));
      return ackEmpty();

    case 'history':
      ctx.waitUntil(handleHistory(env, rest, responseUrl));
      return ackEmpty();

    case 'summary':
      ctx.waitUntil(handleSummaryNow(env, userId, responseUrl));
      return ackEmpty();

    case 'debug':
      ctx.waitUntil(handleDebug(env, userId, responseUrl));
      return ackEmpty();

    default:
      ctx.waitUntil(ephemeral(responseUrl, `使い方:\n${USAGE}`));
      return ackEmpty();
  }
}

/** 仕様書 §7: タスク設定モーダル */
async function handleConfig(
  env: Env,
  userId: string,
  triggerId: string,
  responseUrl: string,
): Promise<void> {
  if (!isApprover(env, userId)) {
    await ephemeral(responseUrl, 'この操作は保護者のみ実行できます。');
    return;
  }
  const tasks = await getActiveTasks(env);
  const res = await slackApi(env, 'views.open', {
    trigger_id: triggerId,
    view: configView(tasks),
  });
  // 失敗しても Slack 上は「何も起きない」だけになるため、必ず理由を返す
  if (!res.ok) await ephemeral(responseUrl, `モーダルを開けませんでした: ${res.error}`);
}

/**
 * 端末のボタン押下に相当する申請の作成。
 * Cloudflare 上では Pi 4 のタクトスイッチが無いため、このコマンドで代替する。
 */
async function handlePress(env: Env, rawTaskId: string | undefined, responseUrl: string) {
  const taskId = (rawTaskId ?? '').toUpperCase();
  if (!taskId) {
    await ephemeral(responseUrl, '例: `/okozukai press A`');
    return;
  }

  const task = await getTask(env, taskId);
  if (!task || !task.active) {
    await ephemeral(responseUrl, `タスク ${taskId} は存在しない、または無効です。`);
    return;
  }

  // 仕様書 §6: allow_duplicate_same_day = 0 のときだけ同日チェックを行う
  if (!task.allow_duplicate_same_day && (await hasSameDayRequest(env, taskId))) {
    await ephemeral(
      responseUrl,
      `${task.label} は今日すでに申請済みです(ALREADY DONE TODAY)。`,
    );
    return;
  }

  const requestId = await createRequest(env, task);
  const posted = await postMessage(env, requestMessage(env, requestId, task));

  if (!posted.ok) {
    // 再送ワーカーが無いので pending のまま残さない(同日チェックを塞いでしまう)
    await markRequestPostFailed(env, requestId);
    await ephemeral(
      responseUrl,
      `Slack への投稿に失敗しました: \`${posted.error}\`\n` +
        'この申請は無効化したので、原因を直してから再実行できます。' +
        '`/okozukai debug` でトークンの状態を確認できます。',
    );
    return;
  }

  if (typeof posted.ts === 'string') {
    await setRequestSlackTs(env, requestId, posted.ts);
  }

  await ephemeral(
    responseUrl,
    `${taskEmoji(task.task_id)} ${task.label} の申請を送りました(${task.amount}円)。`,
  );
}

/**
 * SLACK_BOT_TOKEN の疎通確認。トークン本体は出さず、種類の判別に必要な
 * プレフィックス・長さ・末尾空白の有無だけを返す。
 */
async function handleDebug(env: Env, userId: string, responseUrl: string) {
  if (!isApprover(env, userId)) {
    await ephemeral(responseUrl, 'この操作は保護者のみ実行できます。');
    return;
  }

  const token = env.SLACK_BOT_TOKEN ?? '';
  const shape = [
    `プレフィックス: \`${token.slice(0, 5) || '(未設定)'}\` (期待値: \`xoxb-\`)`,
    `長さ: ${token.length}`,
    `前後の空白/改行: ${token !== token.trim() ? '**あり(これが原因)**' : 'なし'}`,
  ].join('\n');

  const auth = await slackApi<{ team?: string; user?: string; bot_id?: string }>(
    env,
    'auth.test',
    {},
  );
  const result = auth.ok
    ? `✅ auth.test 成功 — team: ${auth.team} / bot: ${auth.user} (${auth.bot_id})`
    : `❌ auth.test 失敗 — \`${auth.error}\``;

  await ephemeral(responseUrl, `${result}\n\nSLACK_BOT_TOKEN の形:\n${shape}`);
}

/** 仕様書 §8: 任意金額の追加・訂正 */
async function handleAdd(env: Env, userId: string, args: string[], responseUrl: string) {
  if (!isApprover(env, userId)) {
    await ephemeral(responseUrl, 'この操作は保護者のみ実行できます。');
    return;
  }

  const [rawAmount, ...memoParts] = args;
  if (!rawAmount || !/^-?\d+$/.test(rawAmount)) {
    await ephemeral(responseUrl, '金額は半角の整数で指定してください。例: `/okozukai add 330 メルカリ 漫画売却`');
    return;
  }

  const amount = Number(rawAmount);
  if (amount === 0) {
    await ephemeral(responseUrl, '金額に 0 は指定できません。');
    return;
  }

  const memo = memoParts.join(' ').trim();
  // 理由なしのマイナス訂正を防ぐ(仕様書 §8-6)
  if (amount < 0 && !memo) {
    await ephemeral(responseUrl, 'マイナス金額の場合はメモ(理由)が必須です。例: `/okozukai add -50 入力ミス訂正`');
    return;
  }

  await insertLedger(env, {
    type: 'earn_manual',
    amount,
    label: memo || null,
    createdBy: userId,
  });

  const balance = await getBalance(env);
  await postMessage(env, manualEntryMessage(userId, amount, memo, balance));
}

/**
 * 月末サマリ(仕様書 §14)を日付判定を飛ばして即時投稿する。
 * cron は毎月1日にしか発火しないため、それ以外の日に動作確認する用。
 */
async function handleSummaryNow(env: Env, userId: string, responseUrl: string) {
  if (!isApprover(env, userId)) {
    await ephemeral(responseUrl, 'この操作は保護者のみ実行できます。');
    return;
  }
  await runMonthlySummary(env, true);
}

/** 仕様書 §13: 記帳履歴 */
async function handleHistory(env: Env, args: string[], responseUrl: string) {
  const range = parseHistoryRange(args);
  if (!range) {
    await ephemeral(
      responseUrl,
      '期間の指定が不正です。`/okozukai history` / `history 2026-07` / `history 2026-07-01 2026-07-15`',
    );
    return;
  }

  const [rows, totals, endingBalance] = await Promise.all([
    getLedgerRange(env, range.from, range.to),
    getTypeTotals(env, range.from, range.to),
    getBalanceAsOf(env, range.to),
  ]);

  await respond(
    responseUrl,
    historyMessage(range.title, rows, totals, endingBalance, HISTORY_DETAIL_LIMIT),
  );
}

function parseHistoryRange(
  args: string[],
): { from: string; to: string; title: string } | null {
  if (args.length === 0) {
    const { year, month } = jstParts();
    return { ...monthRange(year, month), title: `${year}年${month}月の記帳履歴` };
  }

  if (args.length === 1 && /^\d{4}-\d{2}$/.test(args[0])) {
    const [year, month] = args[0].split('-').map(Number);
    if (month < 1 || month > 12) return null;
    return { ...monthRange(year, month), title: `${year}年${month}月の記帳履歴` };
  }

  if (args.length === 2 && args.every((a) => /^\d{4}-\d{2}-\d{2}$/.test(a))) {
    const [from, to] = args;
    if (from > to) return null;
    return { from, to, title: `${from} 〜 ${to} の記帳履歴` };
  }

  return null;
}
