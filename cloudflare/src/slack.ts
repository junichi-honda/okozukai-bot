import type { Env } from './types';

const encoder = new TextEncoder();

function timingSafeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function toHex(buffer: ArrayBuffer): string {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Slack の署名検証 (https://api.slack.com/authentication/verifying-requests-from-slack)。
 *
 * Socket Mode ではなく公開 URL で受けるため、これが唯一のセキュリティ境界になる。
 * 生のリクエストボディ文字列をそのまま HMAC 対象にする必要があるので、
 * 呼び出し側は formData() ではなく text() で読んだ値を渡すこと。
 */
export async function verifySlackRequest(
  signingSecret: string,
  request: Request,
  rawBody: string,
): Promise<boolean> {
  if (!signingSecret) {
    console.error('SLACK_SIGNING_SECRET が未設定です (wrangler secret put SLACK_SIGNING_SECRET)');
    return false;
  }

  const signature = request.headers.get('x-slack-signature');
  const timestamp = request.headers.get('x-slack-request-timestamp');
  if (!signature || !timestamp) return false;

  // リプレイ対策: 5分以上古いリクエストは拒否
  const age = Math.abs(Date.now() / 1000 - Number(timestamp));
  if (!Number.isFinite(age) || age > 60 * 5) return false;

  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(signingSecret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const mac = await crypto.subtle.sign('HMAC', key, encoder.encode(`v0:${timestamp}:${rawBody}`));
  return timingSafeEqual(`v0=${toHex(mac)}`, signature);
}

/** Slack Web API を JSON で呼ぶ */
export async function slackApi<T = Record<string, unknown>>(
  env: Env,
  method: string,
  payload: Record<string, unknown>,
): Promise<T & { ok: boolean; error?: string }> {
  const res = await fetch(`https://slack.com/api/${method}`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json; charset=utf-8',
      authorization: `Bearer ${env.SLACK_BOT_TOKEN}`,
    },
    body: JSON.stringify(payload),
  });
  const json = (await res.json()) as T & { ok: boolean; error?: string };
  if (!json.ok) console.error(`slack ${method} failed: ${json.error}`);
  return json;
}

export function postMessage(env: Env, payload: Record<string, unknown>) {
  return slackApi(env, 'chat.postMessage', { channel: env.CHANNEL_ID, ...payload });
}

/**
 * response_url への応答。approve/reject のメッセージ差し替えは
 * ts を管理せずに済む replace_original を使う。
 */
export async function respond(responseUrl: string, payload: Record<string, unknown>): Promise<void> {
  const res = await fetch(responseUrl, {
    method: 'POST',
    headers: { 'content-type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) console.error(`response_url failed: ${res.status} ${await res.text()}`);
}

/** 実行者にだけ見えるエラー/案内 */
export function ephemeral(responseUrl: string, text: string): Promise<void> {
  return respond(responseUrl, { response_type: 'ephemeral', replace_original: false, text });
}
