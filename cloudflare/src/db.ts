import { jstDate, jstTimestamp } from './time';
import type { Env, LedgerRow, LedgerType, RequestRow, Task } from './types';

/** 残高 = ledger の総和(仕様書 §5) */
export async function getBalance(env: Env): Promise<number> {
  const row = await env.DB.prepare('SELECT COALESCE(SUM(amount), 0) AS balance FROM ledger').first<{
    balance: number;
  }>();
  return row?.balance ?? 0;
}

/** 指定日(JST)の終了時点での残高 */
export async function getBalanceAsOf(env: Env, date: string): Promise<number> {
  const row = await env.DB.prepare(
    'SELECT COALESCE(SUM(amount), 0) AS balance FROM ledger WHERE date(created_at) <= ?',
  )
    .bind(date)
    .first<{ balance: number }>();
  return row?.balance ?? 0;
}

export async function getActiveTasks(env: Env): Promise<Task[]> {
  const { results } = await env.DB.prepare(
    'SELECT * FROM tasks WHERE active = 1 ORDER BY task_id',
  ).all<Task>();
  return results ?? [];
}

export function getTask(env: Env, taskId: string): Promise<Task | null> {
  return env.DB.prepare('SELECT * FROM tasks WHERE task_id = ?').bind(taskId).first<Task>();
}

/**
 * 同日重複申請のチェック(仕様書 §6)。
 * allow_duplicate_same_day = 1 のタスクは呼び出し側でスキップする。
 */
export async function hasSameDayRequest(env: Env, taskId: string): Promise<boolean> {
  const row = await env.DB.prepare(
    `SELECT COUNT(*) AS c FROM requests
      WHERE task_id = ?
        AND status IN ('pending', 'approved')
        AND date(created_at) = ?`,
  )
    .bind(taskId, jstDate())
    .first<{ c: number }>();
  return (row?.c ?? 0) > 0;
}

/** 申請を作成(label/amount は申請時点のスナップショット) */
export async function createRequest(env: Env, task: Task): Promise<number> {
  const res = await env.DB.prepare(
    `INSERT INTO requests (task_id, label, amount, status, created_at)
       VALUES (?, ?, ?, 'pending', ?)`,
  )
    .bind(task.task_id, task.label, task.amount, jstTimestamp())
    .run();
  return res.meta.last_row_id as number;
}

export async function setRequestSlackTs(env: Env, requestId: number, ts: string): Promise<void> {
  await env.DB.prepare('UPDATE requests SET slack_ts = ? WHERE id = ?').bind(ts, requestId).run();
}

/**
 * Slack への投稿に失敗した申請を post_failed にする。
 *
 * Pi 4 版(仕様書 §12-1)は slack_ts IS NULL を再送ワーカーが拾うが、
 * Cloudflare 版に再送ワーカーは無い。pending のまま残すと §6 の同日チェックに
 * 引っかかって同じタスクを再申請できなくなるため、対象外の status に落とす。
 */
export async function markRequestPostFailed(env: Env, requestId: number): Promise<void> {
  await env.DB.prepare(
    "UPDATE requests SET status = 'post_failed' WHERE id = ? AND status = 'pending'",
  )
    .bind(requestId)
    .run();
}

export function getRequest(env: Env, requestId: number): Promise<RequestRow | null> {
  return env.DB.prepare('SELECT * FROM requests WHERE id = ?').bind(requestId).first<RequestRow>();
}

/**
 * pending のみを条件に更新することで二重クリックを弾く(仕様書 §10)。
 * 更新できなかった場合は false。
 */
export async function decideRequest(
  env: Env,
  requestId: number,
  status: 'approved' | 'rejected',
  userId: string,
): Promise<boolean> {
  const res = await env.DB.prepare(
    `UPDATE requests SET status = ?, approved_by = ?, decided_at = ?
       WHERE id = ? AND status = 'pending'`,
  )
    .bind(status, userId, jstTimestamp(), requestId)
    .run();
  return (res.meta.changes ?? 0) > 0;
}

export async function insertLedger(
  env: Env,
  entry: {
    type: LedgerType;
    amount: number;
    label: string | null;
    requestId?: number | null;
    createdBy?: string | null;
  },
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO ledger (type, amount, label, request_id, created_by, created_at)
       VALUES (?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      entry.type,
      entry.amount,
      entry.label,
      entry.requestId ?? null,
      entry.createdBy ?? null,
      jstTimestamp(),
    )
    .run();
}

export async function updateTask(
  env: Env,
  taskId: string,
  fields: { label: string; amount: number; allowDuplicateSameDay: boolean },
): Promise<void> {
  await env.DB.prepare(
    'UPDATE tasks SET label = ?, amount = ?, allow_duplicate_same_day = ? WHERE task_id = ?',
  )
    .bind(fields.label, fields.amount, fields.allowDuplicateSameDay ? 1 : 0, taskId)
    .run();
}

/**
 * 記帳履歴(仕様書 §13)。
 * ボタン経由の収入は ledger.label が NULL なので requests.label(申請時点の
 * タスク名スナップショット)を拾う。
 */
export async function getLedgerRange(env: Env, from: string, to: string): Promise<LedgerRow[]> {
  const { results } = await env.DB.prepare(
    `SELECT l.type,
            COALESCE(l.label, r.label) AS label,
            l.amount,
            l.created_at
       FROM ledger l
       LEFT JOIN requests r ON l.request_id = r.id
      WHERE date(l.created_at) BETWEEN ? AND ?
      ORDER BY l.created_at ASC`,
  )
    .bind(from, to)
    .all<LedgerRow>();
  return results ?? [];
}

/** 期間内のタスク別内訳(承認分のみ。仕様書 §14) */
export async function getTaskBreakdown(
  env: Env,
  from: string,
  to: string,
): Promise<{ task_id: string; label: string; count: number; total: number }[]> {
  const { results } = await env.DB.prepare(
    `SELECT r.task_id        AS task_id,
            r.label          AS label,
            COUNT(*)         AS count,
            SUM(l.amount)    AS total
       FROM ledger l
       JOIN requests r ON l.request_id = r.id
      WHERE l.type = 'earn_button'
        AND date(l.created_at) BETWEEN ? AND ?
      GROUP BY r.task_id, r.label
      ORDER BY r.task_id`,
  )
    .bind(from, to)
    .all<{ task_id: string; label: string; count: number; total: number }>();
  return results ?? [];
}

/** 期間内の type 別合計 */
export async function getTypeTotals(
  env: Env,
  from: string,
  to: string,
): Promise<Record<LedgerType, number>> {
  const { results } = await env.DB.prepare(
    `SELECT type, SUM(amount) AS total FROM ledger
      WHERE date(created_at) BETWEEN ? AND ?
      GROUP BY type`,
  )
    .bind(from, to)
    .all<{ type: LedgerType; total: number }>();

  const totals: Record<LedgerType, number> = { earn_button: 0, earn_manual: 0, payment: 0 };
  for (const row of results ?? []) totals[row.type] = row.total;
  return totals;
}
