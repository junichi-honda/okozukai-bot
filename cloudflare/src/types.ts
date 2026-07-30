export interface Env {
  DB: D1Database;
  /** 投稿先のプライベートチャンネル */
  CHANNEL_ID: string;
  /** 承認者の Slack user ID をカンマ区切りで指定 */
  SLACK_APPROVERS: string;
  /** wrangler secret put SLACK_BOT_TOKEN */
  SLACK_BOT_TOKEN: string;
  /** wrangler secret put SLACK_SIGNING_SECRET */
  SLACK_SIGNING_SECRET: string;
}

export interface Task {
  task_id: string;
  label: string;
  amount: number;
  allow_duplicate_same_day: number;
  active: number;
}

export interface RequestRow {
  id: number;
  task_id: string;
  label: string;
  amount: number;
  status: string;
  slack_ts: string | null;
  approved_by: string | null;
  created_at: string;
  decided_at: string | null;
}

export type LedgerType = 'earn_button' | 'earn_manual' | 'payment';

export interface LedgerRow {
  type: LedgerType;
  label: string | null;
  amount: number;
  created_at: string;
}

export function approvers(env: Env): string[] {
  return env.SLACK_APPROVERS.split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

export function isApprover(env: Env, userId: string): boolean {
  return approvers(env).includes(userId);
}
