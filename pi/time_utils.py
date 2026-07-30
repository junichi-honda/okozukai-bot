"""JST 固定の日時ユーティリティ。

Pi のシステム時刻が Asia/Tokyo に設定されている前提(README 参照)だが、
`zoneinfo` で明示的に JST に変換することで、万一 UTC のままでも日付境界が
ずれないようにする。SQLite 側の `date(x, 'localtime')` は使わない
(保存する文字列が既に JST のため、二重に9時間ずれてしまう)。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    return datetime.now(JST)


def jst_timestamp(when: datetime | None = None) -> str:
    """'YYYY-MM-DD HH:MM:SS' (JST) — DB の created_at 形式"""
    when = (when or now_jst()).astimezone(JST)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def jst_date(when: datetime | None = None) -> str:
    """'YYYY-MM-DD' (JST)"""
    return jst_timestamp(when)[:10]


def last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    return (next_month.toordinal() - date(year, month, 1).toordinal())


def month_range(year: int, month: int) -> tuple[str, str]:
    return (
        f"{year:04d}-{month:02d}-01",
        f"{year:04d}-{month:02d}-{last_day_of_month(year, month):02d}",
    )


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def minutes_ago_timestamp(minutes: int) -> str:
    """'YYYY-MM-DD HH:MM:SS' (JST) — 現在時刻から指定分だけ遡った時刻"""
    return jst_timestamp(now_jst() - timedelta(minutes=minutes))


def short_date(timestamp: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' -> 'MM/DD'"""
    return f"{timestamp[5:7]}/{timestamp[8:10]}"
