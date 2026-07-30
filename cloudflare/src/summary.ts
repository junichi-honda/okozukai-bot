import { monthlySummaryMessage } from './blocks';
import { getBalanceAsOf, getTaskBreakdown, getTypeTotals } from './db';
import { postMessage } from './slack';
import { jstParts, monthRange, previousMonth } from './time';
import type { Env } from './types';

/**
 * 仕様書 §14: 月末サマリの自動投稿。
 *
 * Cloudflare の cron は UTC のため 15:05 UTC(= 翌日 00:05 JST)に毎日起動し、
 * JST で1日でなければ何もしない。
 */
export async function runMonthlySummary(env: Env, force = false): Promise<void> {
  const today = jstParts();
  if (!force && today.day !== 1) return;

  const target = previousMonth(today.year, today.month);
  const { from, to } = monthRange(target.year, target.month);

  const [breakdown, totals, endingBalance] = await Promise.all([
    getTaskBreakdown(env, from, to),
    getTypeTotals(env, from, to),
    getBalanceAsOf(env, to),
  ]);

  const diff = totals.earn_button + totals.earn_manual + totals.payment;
  const hasEntries = breakdown.length > 0 || totals.earn_manual !== 0 || totals.payment !== 0;

  if (!hasEntries) {
    await postMessage(env, {
      text: `📅 ${target.year}年${target.month}月は記帳がありませんでした。`,
    });
    return;
  }

  await postMessage(
    env,
    monthlySummaryMessage(target.year, target.month, breakdown, totals, diff, endingBalance),
  );
}
