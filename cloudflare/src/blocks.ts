import type { Env, LedgerRow, Task } from './types';
import { approvers } from './types';
import { shortDate } from './time';

/** タスクごとの絵文字。label はモーダルで変更されうるので task_id に紐付ける */
const TASK_EMOJI: Record<string, string> = { A: '🛁', B: '🍽' };

export function taskEmoji(taskId: string): string {
  return TASK_EMOJI[taskId] ?? '🧹';
}

export function yen(amount: number): string {
  return `${amount >= 0 ? '+' : '-'}${Math.abs(amount)}円`;
}

function mentions(env: Env): string {
  return approvers(env)
    .map((id) => `<@${id}>`)
    .join(' ');
}

/** 「全額支払い済みにする」ボタン(仕様書 §9-2) */
function payAllBlock(balance: number) {
  return {
    type: 'actions',
    elements: [
      {
        type: 'button',
        text: { type: 'plain_text', text: '全額支払い済みにする' },
        style: 'primary',
        action_id: 'pay_all',
        value: 'pay_all',
        confirm: {
          title: { type: 'plain_text', text: '確認' },
          text: {
            type: 'mrkdwn',
            text: `未払い残高 *${balance}円* を全額支払い済みにしてよろしいですか?`,
          },
          confirm: { type: 'plain_text', text: '支払い済みにする' },
          deny: { type: 'plain_text', text: 'キャンセル' },
        },
      },
    ],
  };
}

/** 申請メッセージ(仕様書 §9-1) */
export function requestMessage(env: Env, requestId: number, task: Task) {
  const emoji = taskEmoji(task.task_id);
  return {
    text: `${mentions(env)} ${task.label}の申請があります (${task.amount}円)`,
    blocks: [
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `${mentions(env)}\n${emoji} *${task.label}* の申請があります\n金額: *${task.amount}円*`,
        },
      },
      {
        type: 'actions',
        block_id: `request_${requestId}`,
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: '承認' },
            style: 'primary',
            action_id: 'approve',
            value: String(requestId),
          },
          {
            type: 'button',
            text: { type: 'plain_text', text: '却下' },
            style: 'danger',
            action_id: 'reject',
            value: String(requestId),
          },
        ],
      },
    ],
  };
}

/** 承認後の差し替えメッセージ(仕様書 §9-2) */
export function approvedMessage(
  label: string,
  amount: number,
  approvedBy: string,
  balance: number,
) {
  return {
    text: `✅ ${label} 承認済み(${amount}円)/ 未払い残高 ${balance}円`,
    blocks: [
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text:
            `✅ *${label}* 承認済み(${amount}円)\n` +
            `承認者: <@${approvedBy}>\n` +
            `未払い残高: *${balance}円*`,
        },
      },
      payAllBlock(balance),
    ],
  };
}

/** 任意金額の追加・訂正の確認メッセージ(仕様書 §8) */
export function manualEntryMessage(
  userId: string,
  amount: number,
  memo: string,
  balance: number,
) {
  const icon = amount >= 0 ? '💰' : '✏️';
  const action = amount >= 0 ? '追加しました' : '訂正しました';
  const summary = `${icon} ${yen(amount)} を${action}${memo ? `(${memo})` : ''}`;

  return {
    text: `${summary} / 未払い残高 ${balance}円`,
    blocks: [
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `${summary}\n登録者: <@${userId}>\n未払い残高: *${balance}円*`,
        },
      },
      payAllBlock(balance),
    ],
  };
}

/** 却下後の差し替えメッセージ(仕様書 §9-3) */
export function rejectedMessage(label: string, amount: number, balance: number) {
  return {
    text: `❌ 却下されました(${label}・${amount}円)/ 未払い残高 ${balance}円`,
    blocks: [
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `❌ 却下されました(${label}・${amount}円)\n未払い残高: *${balance}円*`,
        },
      },
      payAllBlock(balance),
    ],
  };
}

/** タスク設定モーダル(仕様書 §7) */
export function configView(tasks: Task[]) {
  const blocks: Record<string, unknown>[] = [];

  tasks.forEach((task, index) => {
    if (index > 0) blocks.push({ type: 'divider' });

    blocks.push({
      type: 'input',
      block_id: `task_${task.task_id}_label`,
      label: { type: 'plain_text', text: `タスク名 (${task.task_id})` },
      element: {
        type: 'plain_text_input',
        action_id: 'label',
        initial_value: task.label,
      },
    });

    blocks.push({
      type: 'input',
      block_id: `task_${task.task_id}_amount`,
      label: { type: 'plain_text', text: `金額(円) (${task.task_id})` },
      element: {
        type: 'plain_text_input',
        action_id: 'amount',
        initial_value: String(task.amount),
      },
    });

    const option = {
      text: { type: 'plain_text', text: '同日に複数回申請できるようにする' },
      value: task.task_id,
    };
    blocks.push({
      type: 'input',
      block_id: `task_${task.task_id}_dup`,
      label: { type: 'plain_text', text: ' ' },
      optional: true,
      element: {
        type: 'checkboxes',
        action_id: 'allow_duplicate_same_day',
        options: [option],
        // 現在の設定を初期値として反映する(未選択のときは initial_options を付けない)
        ...(task.allow_duplicate_same_day ? { initial_options: [option] } : {}),
      },
    });
  });

  return {
    type: 'modal',
    callback_id: 'task_config_submit',
    title: { type: 'plain_text', text: 'タスク設定' },
    submit: { type: 'plain_text', text: '保存' },
    close: { type: 'plain_text', text: 'キャンセル' },
    blocks,
  };
}

const LEDGER_ICON: Record<string, string> = {
  earn_button: '✅',
  earn_manual: '💰',
  payment: '💸',
};

/** 記帳履歴(仕様書 §13) */
export function historyMessage(
  title: string,
  rows: LedgerRow[],
  totals: { earn_button: number; earn_manual: number; payment: number },
  endingBalance: number,
  detailLimit: number,
) {
  const diff = totals.earn_button + totals.earn_manual + totals.payment;
  const summaryText =
    `収入(承認分): ${yen(totals.earn_button)} / 収入(手動): ${yen(totals.earn_manual)} / ` +
    `支払い: ${yen(totals.payment)}\n差引: ${yen(diff)} / 期間末残高: *${endingBalance}円*`;

  if (rows.length === 0) {
    return {
      response_type: 'ephemeral',
      replace_original: false,
      text: `${title}: 記帳はありませんでした`,
      blocks: [
        {
          type: 'section',
          text: { type: 'mrkdwn', text: `*${title}*\nこの期間の記帳はありませんでした。` },
        },
      ],
    };
  }

  if (rows.length > detailLimit) {
    return {
      response_type: 'ephemeral',
      replace_original: false,
      text: `${title}(${rows.length}件)`,
      blocks: [
        {
          type: 'section',
          text: {
            type: 'mrkdwn',
            text:
              `*${title}(${rows.length}件)*\n` +
              '件数が多いため明細は省略します。期間を絞って再実行してください。\n' +
              '例: `/okozukai history 2026-07-15 2026-07-31`',
          },
        },
        { type: 'section', text: { type: 'mrkdwn', text: summaryText } },
      ],
    };
  }

  const detail = rows
    .map(
      (r) =>
        `${shortDate(r.created_at)} ${LEDGER_ICON[r.type] ?? '•'} ${r.label ?? '(メモなし)'} ${yen(r.amount)}`,
    )
    .join('\n');

  return {
    response_type: 'ephemeral',
    replace_original: false,
    text: `${title}(${rows.length}件)`,
    blocks: [
      { type: 'section', text: { type: 'mrkdwn', text: `*${title}*` } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: detail } },
      { type: 'divider' },
      { type: 'section', text: { type: 'mrkdwn', text: summaryText } },
    ],
  };
}

/** 月末サマリ(仕様書 §14) */
export function monthlySummaryMessage(
  year: number,
  month: number,
  breakdown: { task_id: string; label: string; count: number; total: number }[],
  totals: { earn_manual: number; payment: number },
  diff: number,
  endingBalance: number,
) {
  const header = `📅 ${year}年${month}月のおこづかいサマリ`;
  const lines = breakdown.map(
    (b) => `${taskEmoji(b.task_id)} ${b.label}: ${b.count}回 (${yen(b.total)})`,
  );
  if (totals.earn_manual !== 0) lines.push(`💰 手動追加: ${yen(totals.earn_manual)}`);
  if (totals.payment !== 0) lines.push(`💸 支払い: ${yen(totals.payment)}`);

  return {
    text: header,
    blocks: [
      { type: 'header', text: { type: 'plain_text', text: header } },
      { type: 'section', text: { type: 'mrkdwn', text: lines.join('\n') } },
      { type: 'divider' },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `今月の増減: *${yen(diff)}*\n月末時点の残高: *${endingBalance}円*`,
        },
      },
    ],
  };
}
