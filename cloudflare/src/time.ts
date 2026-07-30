/**
 * JST 固定の日時ユーティリティ。
 *
 * Workers/D1 のランタイムは常に UTC なので、SQLite の date(x, 'localtime') は
 * JST にならない(9時間ずれる)。日付境界の判定は必ずここで JST 文字列を作り、
 * SQL にはパラメータとして渡す。
 */

const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

/** UTC の Date を「JST の壁時計を UTC ゲッタで読める」Date にずらす */
function shiftToJst(date: Date): Date {
  return new Date(date.getTime() + JST_OFFSET_MS);
}

const pad = (n: number) => String(n).padStart(2, '0');

/** 'YYYY-MM-DD HH:MM:SS' (JST) — DB の created_at 形式 */
export function jstTimestamp(now: Date = new Date()): string {
  const d = shiftToJst(now);
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
  );
}

/** 'YYYY-MM-DD' (JST) */
export function jstDate(now: Date = new Date()): string {
  return jstTimestamp(now).slice(0, 10);
}

/** JST での年・月(1-12)・日 */
export function jstParts(now: Date = new Date()): { year: number; month: number; day: number } {
  const d = shiftToJst(now);
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

/** その年月の末日 */
export function lastDayOfMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/** 年月から 'YYYY-MM-DD' の期間を作る */
export function monthRange(year: number, month: number): { from: string; to: string } {
  return {
    from: `${year}-${pad(month)}-01`,
    to: `${year}-${pad(month)}-${pad(lastDayOfMonth(year, month))}`,
  };
}

/** 指定年月の前月 */
export function previousMonth(year: number, month: number): { year: number; month: number } {
  return month === 1 ? { year: year - 1, month: 12 } : { year, month: month - 1 };
}

/** 'YYYY-MM-DD HH:MM:SS' → 'MM/DD' */
export function shortDate(timestamp: string): string {
  return `${timestamp.slice(5, 7)}/${timestamp.slice(8, 10)}`;
}
