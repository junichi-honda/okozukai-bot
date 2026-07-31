"""ハードウェア・Slack の両方から呼ばれる共通ロジック。

button のコールバック(§6, §11)と Slack のアクション/コマンドハンドラ(§7〜§10)
の両方がここを経由することで、DB の更新規則(二重処理防止・残高計算)を
一箇所に集約する。Slack への投稿は `configure()` で注入した関数を介して行い、
このモジュール自体は slack_sdk/slack_bolt に依存しない(テストしやすくするため)。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Callable

import blocks
import config
import db
from hardware import ALREADY_DONE_TODAY, WAITING_FOR_APPROVAL, HardwareController
from time_utils import minutes_ago_timestamp, month_range, now_jst, previous_month

logger = logging.getLogger("okozukai.services")

# Slack へのメッセージ投稿を行う関数。slack_bot.py から注入される。
# 戻り値: {"ok": bool, "ts": str | None, "error": str | None}
PostMessageFn = Callable[[dict[str, Any]], dict[str, Any]]

_post_message: PostMessageFn | None = None
_hardware: HardwareController | None = None

AUTO_APPROVE_USER = "AUTO_APPROVE"


def configure(post_message: PostMessageFn, hardware: HardwareController) -> None:
    global _post_message, _hardware
    _post_message = post_message
    _hardware = hardware


def _require_wired() -> tuple[PostMessageFn, HardwareController]:
    if _post_message is None or _hardware is None:
        raise RuntimeError("services.configure() が呼ばれていません")
    return _post_message, _hardware


def is_approver(user_id: str) -> bool:
    return user_id in config.SLACK_APPROVERS


# --- ボタン押下(仕様書 §6, §11, §12-1) ---


def handle_button_press(task_id: str) -> None:
    """物理ボタン押下(または AUTO_APPROVE プロトタイプ)のエントリポイント。

    gpiozero のコールバックスレッドから呼ばれる。DB 書き込み → (Slack 投稿 |
    自動承認) → LCD/ブザー表示までをこの関数だけで完結させる。
    """
    logger.info("ボタン押下を検知しました: task_id=%s", task_id)
    _, hardware = _require_wired()

    task = db.get_task(task_id)
    if task is None or not task["active"]:
        logger.warning("未知/無効なタスク: %s", task_id)
        return

    if not task["allow_duplicate_same_day"] and db.has_same_day_request(task_id):
        hardware.push(ALREADY_DONE_TODAY, buzzer=2)
        return

    request_id = db.create_request(task)
    hardware.push(WAITING_FOR_APPROVAL, buzzer=1)

    if config.AUTO_APPROVE:
        _auto_approve(request_id, task)
        return

    post_request_to_slack(request_id, task)


def _auto_approve(request_id: int, task) -> None:
    """仕様書 §1: Slack 無しでの動作確認用プロトタイプモード"""
    _, hardware = _require_wired()
    if not db.decide_request(request_id, "approved", AUTO_APPROVE_USER):
        return
    db.insert_ledger("earn_button", task["amount"], None, request_id, AUTO_APPROVE_USER)
    hardware.push(f"APPROVED +{task['amount']}", buzzer=1)


def post_request_to_slack(request_id: int, task) -> bool:
    """仕様書 §9-1 の投稿。成功したら slack_ts を保存する。

    再送ワーカー(§12-1)からも同じ関数を使う。
    """
    post_message, _ = _require_wired()
    payload = blocks.request_message(request_id, task)
    result = post_message(payload)
    if result.get("ok") and result.get("ts"):
        db.set_request_slack_ts(request_id, result["ts"])
        return True
    logger.warning("Slack への投稿に失敗しました(request_id=%s): %s", request_id, result.get("error"))
    return False


def retry_unposted_requests() -> None:
    """仕様書 §12-1: slack_ts が NULL のまま残っている申請を再送する。"""
    for row in db.get_unposted_requests():
        # 直前に他スレッドが投稿済みにしている可能性があるため再確認してから送る
        # (完全な排他ではないが、再投稿の窓を狭める)
        latest = db.get_request(row["id"])
        if latest is None or latest["status"] != "pending" or latest["slack_ts"] is not None:
            continue
        post_request_to_slack(latest["id"], latest)


def reconciliation_sweep() -> None:
    """仕様書 §12-2: 起動時・定期的に古い pending 申請の件数を LCD に一時表示する。"""
    _, hardware = _require_wired()
    cutoff = minutes_ago_timestamp(config.RECONCILIATION_PENDING_MINUTES)
    stale = db.get_stale_pending_requests(cutoff)
    if stale:
        hardware.push(f"{len(stale)} PENDING", "CHECK SLACK")


# --- 承認・却下・全額支払い(仕様書 §9, §10) ---


def decide(request_id: int, action: str, user_id: str) -> dict[str, Any] | None:
    """approve/reject を処理する。戻り値は Slack へ返す差し替えメッセージ、
    処理済み(二重クリック等)なら None。
    """
    _, hardware = _require_wired()

    request = db.get_request(request_id)
    if request is None:
        return None

    status = "approved" if action == "approve" else "rejected"
    if not db.decide_request(request_id, status, user_id):
        return None

    if action == "approve":
        db.insert_ledger("earn_button", request["amount"], None, request_id, user_id)

    balance = db.get_balance()
    if action == "approve":
        hardware.push(f"APPROVED +{request['amount']}", buzzer=1)
        return blocks.approved_message(request["label"], request["amount"], user_id, balance)

    hardware.push("REJECTED", buzzer=2)
    return blocks.rejected_message(request["label"], request["amount"], balance)


def pay_all(user_id: str) -> tuple[int, str]:
    """仕様書 §9-4。戻り値は (精算額(0なら未精算), 表示用の一言)。"""
    _, hardware = _require_wired()
    balance = db.get_balance()

    if balance <= 0:
        hardware.push("NOTHING TO PAY", buzzer=2)
        return 0, "未払い残高は0円のため、支払い操作は行いませんでした。"

    db.insert_ledger("payment", -balance, "全額支払い", None, user_id)
    hardware.push("PAID OUT", "0 YEN", buzzer=1)
    return balance, f"💴 <@{user_id}> が全額支払い済みにしました({balance}円)"


# --- 任意金額の追加・訂正(仕様書 §8) ---


def add_manual(user_id: str, raw_amount: str, memo: str) -> tuple[bool, str | dict[str, Any]]:
    """成功時は (True, block_kit_message)、失敗時は (False, エラー文言)。"""
    _, hardware = _require_wired()

    if not raw_amount or not re.fullmatch(r"-?\d+", raw_amount):
        return False, "金額は半角の整数で指定してください。例: `/okozukai add 330 メルカリ 漫画売却`"

    amount = int(raw_amount)
    if amount == 0:
        return False, "金額に 0 は指定できません。"
    if amount < 0 and not memo:
        return False, "マイナス金額の場合はメモ(理由)が必須です。例: `/okozukai add -50 入力ミス訂正`"

    db.insert_ledger("earn_manual", amount, memo or None, None, user_id)
    balance = db.get_balance()

    icon = "+" if amount >= 0 else "-"
    hardware.push(f"{icon}{abs(amount)} {'EARNED' if amount >= 0 else 'CORRECTED'}", buzzer=1)

    return True, blocks.manual_entry_message(user_id, amount, memo, balance)


# --- タスク設定(仕様書 §7) ---


def parse_config_submission(
    values: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """view_submission の state.values を (parsed, errors) に変換する。

    slack_bot.py の Bolt ハンドラから分離することで、Slack を起動せずに
    このパース処理だけを smoke_test.py で検証できるようにしている。
    """
    errors: dict[str, str] = {}
    parsed: dict[str, dict[str, Any]] = {}

    for block_id, block in values.items():
        match = re.fullmatch(r"task_(.+)_(label|amount|dup)", block_id)
        if not match:
            continue
        task_id, field = match.group(1), match.group(2)
        entry = parsed.setdefault(task_id, {})

        if field == "label":
            text_value = (block["label"]["value"] or "").strip()
            if not text_value:
                errors[block_id] = "タスク名を入力してください"
            else:
                entry["label"] = text_value
        elif field == "amount":
            raw = (block["amount"]["value"] or "").strip()
            if not re.fullmatch(r"-?\d+", raw):
                errors[block_id] = "半角数字で入力してください"
            else:
                entry["amount"] = int(raw)
        else:
            selected = block["allow_duplicate_same_day"]["selected_options"]
            entry["allow_duplicate_same_day"] = len(selected) > 0

    return parsed, errors


def update_tasks(parsed: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for task_id, fields in parsed.items():
        if "label" not in fields or "amount" not in fields:
            continue
        allow = fields.get("allow_duplicate_same_day", False)
        db.update_task(task_id, fields["label"], fields["amount"], allow)
        lines.append(
            f"• {task_id}: {fields['label']} / {fields['amount']}円 / "
            f"同日複数回: {'許可' if allow else '1日1回まで'}"
        )
    return lines


# --- 記帳履歴(仕様書 §13) ---


def parse_history_range(args: list[str]) -> tuple[str, str, str] | None:
    if not args:
        now = now_jst()
        frm, to = month_range(now.year, now.month)
        return frm, to, f"{now.year}年{now.month}月の記帳履歴"

    if len(args) == 1 and re.fullmatch(r"\d{4}-\d{2}", args[0]):
        year, month = (int(x) for x in args[0].split("-"))
        if not 1 <= month <= 12:
            return None
        frm, to = month_range(year, month)
        return frm, to, f"{year}年{month}月の記帳履歴"

    if len(args) == 2 and all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", a) for a in args):
        frm, to = args
        if frm > to:
            return None
        return frm, to, f"{frm} 〜 {to} の記帳履歴"

    return None


def history(args: list[str]) -> dict[str, Any] | str:
    parsed = parse_history_range(args)
    if parsed is None:
        return "期間の指定が不正です。`/okozukai history` / `history 2026-07` / `history 2026-07-01 2026-07-15`"

    frm, to, title = parsed
    rows = db.get_ledger_range(frm, to)
    totals = db.get_type_totals(frm, to)
    ending_balance = db.get_balance_as_of(to)
    return blocks.history_message(title, rows, totals, ending_balance, config.HISTORY_DETAIL_LIMIT)


# --- 月末サマリ(仕様書 §14) ---


def run_monthly_summary(force: bool = False) -> dict[str, Any] | None:
    now = now_jst()
    if not force and now.day != 1:
        return None

    year, month = previous_month(now.year, now.month)
    frm, to = month_range(year, month)

    breakdown = db.get_task_breakdown(frm, to)
    totals = db.get_type_totals(frm, to)
    ending_balance = db.get_balance_as_of(to)
    diff = totals["earn_button"] + totals["earn_manual"] + totals["payment"]

    has_entries = bool(breakdown) or totals["earn_manual"] != 0 or totals["payment"] != 0
    if not has_entries:
        return {"text": f"📅 {year}年{month}月は記帳がありませんでした。"}

    return blocks.monthly_summary_message(year, month, breakdown, totals, diff, ending_balance)


# --- デバッグ(仕様書には無い、動作確認用の追加コマンド) ---


def reset_records() -> None:
    """記帳履歴(ledger・requests)を全消去する。タスク定義(tasks)は残す。"""
    _, hardware = _require_wired()
    db.reset_records()
    hardware.show_balance()
