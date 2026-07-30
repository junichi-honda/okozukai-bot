"""Block Kit メッセージ組み立て(仕様書 §7, §9, §13, §14)。"""

from __future__ import annotations

from typing import Any

import config
from time_utils import short_date

TASK_EMOJI: dict[str, str] = {"A": "🛁", "B": "🍽"}


def task_emoji(task_id: str) -> str:
    return TASK_EMOJI.get(task_id, "🧹")


def yen(amount: int) -> str:
    return f"{'+' if amount >= 0 else '-'}{abs(amount)}円"


def _mentions() -> str:
    return " ".join(f"<@{uid}>" for uid in config.SLACK_APPROVERS)


def pay_all_block(balance: int) -> dict[str, Any]:
    return {
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "全額支払い済みにする"},
                "style": "primary",
                "action_id": "pay_all",
                "value": "pay_all",
                "confirm": {
                    "title": {"type": "plain_text", "text": "確認"},
                    "text": {
                        "type": "mrkdwn",
                        "text": f"未払い残高 *{balance}円* を全額支払い済みにしてよろしいですか?",
                    },
                    "confirm": {"type": "plain_text", "text": "支払い済みにする"},
                    "deny": {"type": "plain_text", "text": "キャンセル"},
                },
            }
        ],
    }


def request_message(request_id: int, task) -> dict[str, Any]:
    """仕様書 §9-1"""
    emoji = task_emoji(task["task_id"])
    mentions = _mentions()
    return {
        "text": f"{mentions} {task['label']}の申請があります ({task['amount']}円)",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{mentions}\n{emoji} *{task['label']}* の申請があります\n金額: *{task['amount']}円*",
                },
            },
            {
                "type": "actions",
                "block_id": f"request_{request_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "承認"},
                        "style": "primary",
                        "action_id": "approve",
                        "value": str(request_id),
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "却下"},
                        "style": "danger",
                        "action_id": "reject",
                        "value": str(request_id),
                    },
                ],
            },
        ],
    }


def approved_message(label: str, amount: int, approved_by: str, balance: int) -> dict[str, Any]:
    """仕様書 §9-2"""
    return {
        "text": f"✅ {label} 承認済み({amount}円)/ 未払い残高 {balance}円",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"✅ *{label}* 承認済み({amount}円)\n承認者: <@{approved_by}>\n未払い残高: *{balance}円*",
                },
            },
            pay_all_block(balance),
        ],
    }


def rejected_message(label: str, amount: int, balance: int) -> dict[str, Any]:
    """仕様書 §9-3"""
    return {
        "text": f"❌ 却下されました({label}・{amount}円)/ 未払い残高 {balance}円",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"❌ 却下されました({label}・{amount}円)\n未払い残高: *{balance}円*",
                },
            },
            pay_all_block(balance),
        ],
    }


def manual_entry_message(user_id: str, amount: int, memo: str, balance: int) -> dict[str, Any]:
    """仕様書 §8"""
    icon = "💰" if amount >= 0 else "✏️"
    action = "追加しました" if amount >= 0 else "訂正しました"
    summary = f"{icon} {yen(amount)} を{action}" + (f"({memo})" if memo else "")
    return {
        "text": f"{summary} / 未払い残高 {balance}円",
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{summary}\n登録者: <@{user_id}>\n未払い残高: *{balance}円*",
                },
            },
            pay_all_block(balance),
        ],
    }


def strip_pay_all_button(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """全額支払い済みボタンを押した後、元メッセージからそのボタンだけ外す"""
    return [
        b
        for b in blocks
        if not (
            b.get("type") == "actions"
            and any(el.get("action_id") == "pay_all" for el in b.get("elements", []))
        )
    ]


def config_view(tasks) -> dict[str, Any]:
    """仕様書 §7 のタスク設定モーダル"""
    blocks: list[dict[str, Any]] = []

    for i, task in enumerate(tasks):
        if i > 0:
            blocks.append({"type": "divider"})

        blocks.append(
            {
                "type": "input",
                "block_id": f"task_{task['task_id']}_label",
                "label": {"type": "plain_text", "text": f"タスク名 ({task['task_id']})"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "label",
                    "initial_value": task["label"],
                },
            }
        )
        blocks.append(
            {
                "type": "input",
                "block_id": f"task_{task['task_id']}_amount",
                "label": {"type": "plain_text", "text": f"金額(円) ({task['task_id']})"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "amount",
                    "initial_value": str(task["amount"]),
                },
            }
        )

        option = {
            "text": {"type": "plain_text", "text": "同日に複数回申請できるようにする"},
            "value": task["task_id"],
        }
        checkboxes: dict[str, Any] = {
            "type": "checkboxes",
            "action_id": "allow_duplicate_same_day",
            "options": [option],
        }
        if task["allow_duplicate_same_day"]:
            checkboxes["initial_options"] = [option]

        blocks.append(
            {
                "type": "input",
                "block_id": f"task_{task['task_id']}_dup",
                "label": {"type": "plain_text", "text": " "},
                "optional": True,
                "element": checkboxes,
            }
        )

    return {
        "type": "modal",
        "callback_id": "task_config_submit",
        "title": {"type": "plain_text", "text": "タスク設定"},
        "submit": {"type": "plain_text", "text": "保存"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": blocks,
    }


LEDGER_ICON = {"earn_button": "✅", "earn_manual": "💰", "payment": "💸"}


def history_message(
    title: str,
    rows,
    totals: dict[str, int],
    ending_balance: int,
    detail_limit: int,
) -> dict[str, Any]:
    """仕様書 §13"""
    diff = totals["earn_button"] + totals["earn_manual"] + totals["payment"]
    summary_text = (
        f"収入(承認分): {yen(totals['earn_button'])} / 収入(手動): {yen(totals['earn_manual'])} / "
        f"支払い: {yen(totals['payment'])}\n差引: {yen(diff)} / 期間末残高: *{ending_balance}円*"
    )

    if not rows:
        return {
            "response_type": "ephemeral",
            "text": f"{title}: 記帳はありませんでした",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{title}*\nこの期間の記帳はありませんでした。"},
                }
            ],
        }

    if len(rows) > detail_limit:
        return {
            "response_type": "ephemeral",
            "text": f"{title}({len(rows)}件)",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*{title}({len(rows)}件)*\n"
                            "件数が多いため明細は省略します。期間を絞って再実行してください。\n"
                            "例: `/okozukai history 2026-07-15 2026-07-31`"
                        ),
                    },
                },
                {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
            ],
        }

    detail = "\n".join(
        f"{short_date(r['created_at'])} {LEDGER_ICON.get(r['type'], '•')} "
        f"{r['label'] or '(メモなし)'} {yen(r['amount'])}"
        for r in rows
    )

    return {
        "response_type": "ephemeral",
        "text": f"{title}({len(rows)}件)",
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": detail}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": summary_text}},
        ],
    }


def monthly_summary_message(
    year: int,
    month: int,
    breakdown,
    totals: dict[str, int],
    diff: int,
    ending_balance: int,
) -> dict[str, Any]:
    """仕様書 §14"""
    header = f"📅 {year}年{month}月のおこづかいサマリ"
    lines = [f"{task_emoji(b['task_id'])} {b['label']}: {b['count']}回 ({yen(b['total'])})" for b in breakdown]
    if totals["earn_manual"]:
        lines.append(f"💰 手動追加: {yen(totals['earn_manual'])}")
    if totals["payment"]:
        lines.append(f"💸 支払い: {yen(totals['payment'])}")

    return {
        "text": header,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": header}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"今月の増減: *{yen(diff)}*\n月末時点の残高: *{ending_balance}円*",
                },
            },
        ],
    }
