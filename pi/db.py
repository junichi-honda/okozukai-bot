"""SQLite アクセス層。

button のコールバック(gpiozero が生成するスレッド)、LCD 表示スレッド、
Bolt のイベントハンドラ(イベントごとに別スレッド)、再送/棚卸しワーカーなど
複数スレッドから同時に触られる。sqlite3.Connection はスレッドを跨げないため
threading.local() でスレッドごとに接続を持ち、WAL + busy_timeout で
「database is locked」を避ける。
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

import config
from time_utils import jst_date, jst_timestamp

_local = threading.local()


def _connect() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def init_db() -> None:
    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
    get_conn().executescript(schema)


def _query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, params).fetchall()


def _query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, params).fetchone()


# --- 残高(仕様書 §5) ---


def get_balance() -> int:
    row = _query_one("SELECT COALESCE(SUM(amount), 0) AS balance FROM ledger")
    return row["balance"] if row else 0


def get_balance_as_of(date_str: str) -> int:
    row = _query_one(
        "SELECT COALESCE(SUM(amount), 0) AS balance FROM ledger WHERE date(created_at) <= ?",
        (date_str,),
    )
    return row["balance"] if row else 0


# --- タスク ---


def get_active_tasks() -> list[sqlite3.Row]:
    return _query("SELECT * FROM tasks WHERE active = 1 ORDER BY task_id")


def get_task(task_id: str) -> sqlite3.Row | None:
    return _query_one("SELECT * FROM tasks WHERE task_id = ?", (task_id,))


def update_task(task_id: str, label: str, amount: int, allow_duplicate_same_day: bool) -> None:
    get_conn().execute(
        "UPDATE tasks SET label = ?, amount = ?, allow_duplicate_same_day = ? WHERE task_id = ?",
        (label, amount, 1 if allow_duplicate_same_day else 0, task_id),
    )


# --- 申請(仕様書 §6, §12) ---


def has_same_day_request(task_id: str) -> bool:
    row = _query_one(
        """SELECT COUNT(*) AS c FROM requests
             WHERE task_id = ?
               AND status IN ('pending', 'approved')
               AND date(created_at) = ?""",
        (task_id, jst_date()),
    )
    return bool(row and row["c"] > 0)


def create_request(task: sqlite3.Row) -> int:
    conn = get_conn()
    conn.execute(
        """INSERT INTO requests (task_id, label, amount, status, created_at)
             VALUES (?, ?, ?, 'pending', ?)""",
        (task["task_id"], task["label"], task["amount"], jst_timestamp()),
    )
    return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def set_request_slack_ts(request_id: int, ts: str) -> None:
    get_conn().execute("UPDATE requests SET slack_ts = ? WHERE id = ?", (ts, request_id))


def get_request(request_id: int) -> sqlite3.Row | None:
    return _query_one("SELECT * FROM requests WHERE id = ?", (request_id,))


def get_unposted_requests() -> list[sqlite3.Row]:
    """仕様書 §12-1: 投稿がまだ成功していない申請(再送ワーカー用)"""
    return _query(
        "SELECT * FROM requests WHERE status = 'pending' AND slack_ts IS NULL ORDER BY id"
    )


def get_stale_pending_requests(cutoff_timestamp: str) -> list[sqlite3.Row]:
    """仕様書 §12-2: 起動時・再接続時の棚卸し対象。

    しきい値は 'YYYY-MM-DD HH:MM:SS' (JST) を呼び出し側(time_utils)で計算して渡す。
    created_at も同じ形式の文字列なので、SQLite の日時関数を介さず文字列比較でよい。
    """
    return _query(
        "SELECT * FROM requests WHERE status = 'pending' AND created_at <= ? ORDER BY id",
        (cutoff_timestamp,),
    )


def decide_request(request_id: int, status: str, user_id: str) -> bool:
    """pending のみを条件に更新することで二重処理を防ぐ(仕様書 §10, §12-3)"""
    conn = get_conn()
    conn.execute(
        """UPDATE requests SET status = ?, approved_by = ?, decided_at = ?
             WHERE id = ? AND status = 'pending'""",
        (status, user_id, jst_timestamp(), request_id),
    )
    return conn.execute("SELECT changes() AS c").fetchone()["c"] > 0


# --- 元帳(仕様書 §5, §8, §9-4) ---


def insert_ledger(
    type_: str,
    amount: int,
    label: str | None,
    request_id: int | None = None,
    created_by: str | None = None,
) -> None:
    get_conn().execute(
        """INSERT INTO ledger (type, amount, label, request_id, created_by, created_at)
             VALUES (?, ?, ?, ?, ?, ?)""",
        (type_, amount, label, request_id, created_by, jst_timestamp()),
    )


# --- 記帳履歴(仕様書 §13) ---


def get_ledger_range(from_date: str, to_date: str) -> list[sqlite3.Row]:
    return _query(
        """SELECT l.type,
                  COALESCE(l.label, r.label) AS label,
                  l.amount,
                  l.created_at
             FROM ledger l
             LEFT JOIN requests r ON l.request_id = r.id
            WHERE date(l.created_at) BETWEEN ? AND ?
            ORDER BY l.created_at ASC""",
        (from_date, to_date),
    )


def get_type_totals(from_date: str, to_date: str) -> dict[str, int]:
    rows = _query(
        """SELECT type, SUM(amount) AS total FROM ledger
            WHERE date(created_at) BETWEEN ? AND ?
            GROUP BY type""",
        (from_date, to_date),
    )
    totals = {"earn_button": 0, "earn_manual": 0, "payment": 0}
    for row in rows:
        totals[row["type"]] = row["total"]
    return totals


def get_task_breakdown(from_date: str, to_date: str) -> list[sqlite3.Row]:
    """仕様書 §14: 期間内のタスク別内訳(承認分のみ)"""
    return _query(
        """SELECT r.task_id AS task_id, r.label AS label, COUNT(*) AS count, SUM(l.amount) AS total
             FROM ledger l
             JOIN requests r ON l.request_id = r.id
            WHERE l.type = 'earn_button'
              AND date(l.created_at) BETWEEN ? AND ?
            GROUP BY r.task_id, r.label
            ORDER BY r.task_id""",
        (from_date, to_date),
    )
