import { handleBlockActions } from './actions';
import { handleCommand } from './commands';
import { verifySlackRequest } from './slack';
import { runMonthlySummary } from './summary';
import { handleViewSubmission } from './views';
import type { Env } from './types';

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method === 'GET') {
      return new Response('okozukai-bot (Cloudflare Workers) is running.\n');
    }
    if (request.method !== 'POST') {
      return new Response('Method Not Allowed', { status: 405 });
    }

    // 署名検証は生のボディ文字列に対して行う必要があるため、
    // formData() ではなく text() で読む。
    const rawBody = await request.text();
    if (!(await verifySlackRequest(env.SLACK_SIGNING_SECRET, request, rawBody))) {
      return new Response('invalid signature', { status: 401 });
    }

    const contentType = request.headers.get('content-type') ?? '';

    // Event Subscriptions を後から有効にしたときの URL 検証に備える
    if (contentType.includes('application/json')) {
      const body = JSON.parse(rawBody) as { type?: string; challenge?: string };
      if (body.type === 'url_verification' && body.challenge) {
        return new Response(body.challenge, { headers: { 'content-type': 'text/plain' } });
      }
      return new Response('', { status: 200 });
    }

    const params = new URLSearchParams(rawBody);

    if (params.get('command')) {
      return handleCommand(params, env, ctx);
    }

    const rawPayload = params.get('payload');
    if (rawPayload) {
      const payload = JSON.parse(rawPayload) as { type?: string };
      if (payload.type === 'block_actions') {
        return handleBlockActions(payload as never, env, ctx);
      }
      if (payload.type === 'view_submission') {
        return handleViewSubmission(payload as never, env, ctx);
      }
    }

    return new Response('', { status: 200 });
  },

  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(runMonthlySummary(env));
  },
};
