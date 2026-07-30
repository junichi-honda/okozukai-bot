import { updateTask } from './db';
import { postMessage } from './slack';
import type { Env } from './types';

interface ViewSubmissionPayload {
  user: { id: string };
  view: {
    callback_id: string;
    state: {
      values: Record<string, Record<string, { value?: string | null; selected_options?: unknown[] }>>;
    };
  };
}

interface ParsedTask {
  label?: string;
  amount?: number;
  allowDuplicateSameDay?: boolean;
}

/** 仕様書 §7: タスク設定モーダルの送信 */
export function handleViewSubmission(
  payload: ViewSubmissionPayload,
  env: Env,
  ctx: ExecutionContext,
): Response {
  if (payload.view.callback_id !== 'task_config_submit') {
    return new Response('', { status: 200 });
  }

  const values = payload.view.state.values;
  const errors: Record<string, string> = {};
  const parsed = new Map<string, ParsedTask>();

  const entryFor = (taskId: string): ParsedTask => {
    let entry = parsed.get(taskId);
    if (!entry) {
      entry = {};
      parsed.set(taskId, entry);
    }
    return entry;
  };

  for (const [blockId, block] of Object.entries(values)) {
    const match = /^task_(.+)_(label|amount|dup)$/.exec(blockId);
    if (!match) continue;
    const [, taskId, field] = match;

    if (field === 'label') {
      const value = (block.label?.value ?? '').trim();
      if (!value) errors[blockId] = 'タスク名を入力してください';
      else entryFor(taskId).label = value;
    } else if (field === 'amount') {
      const raw = (block.amount?.value ?? '').trim();
      if (!/^-?\d+$/.test(raw)) errors[blockId] = '半角数字で入力してください';
      else entryFor(taskId).amount = Number(raw);
    } else {
      const selected = block.allow_duplicate_same_day?.selected_options ?? [];
      entryFor(taskId).allowDuplicateSameDay = selected.length > 0;
    }
  }

  if (Object.keys(errors).length > 0) {
    return json({ response_action: 'errors', errors });
  }

  ctx.waitUntil(applyUpdates(env, payload.user.id, parsed));
  return new Response('', { status: 200 });
}

async function applyUpdates(
  env: Env,
  userId: string,
  parsed: Map<string, ParsedTask>,
): Promise<void> {
  const lines: string[] = [];

  for (const [taskId, task] of parsed) {
    if (task.label === undefined || task.amount === undefined) continue;
    const allow = task.allowDuplicateSameDay ?? false;
    await updateTask(env, taskId, {
      label: task.label,
      amount: task.amount,
      allowDuplicateSameDay: allow,
    });
    lines.push(
      `• ${taskId}: ${task.label} / ${task.amount}円 / 同日複数回: ${allow ? '許可' : '1日1回まで'}`,
    );
  }

  if (lines.length === 0) return;

  await postMessage(env, {
    text: `⚙️ タスク設定を更新しました(<@${userId}>)\n${lines.join('\n')}`,
  });
}

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });
}
