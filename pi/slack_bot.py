"""Slack Bolt (Socket Mode) アプリ本体(仕様書 §4, §7〜§10)。

外部公開 URL 不要。main.py から `build_app()` → `SocketModeHandler(...).start()`
の順で呼び出す。services.py に業務ロジックを委譲し、ここでは Slack API との
やり取り(ack・レスポンス整形・エラーメッセージ)に専念する。
"""

from __future__ import annotations

import logging

from slack_bolt import App
from slack_sdk.errors import SlackApiError

import blocks
import config
import db
import services
from hardware import HardwareController

logger = logging.getLogger("okozukai.slack_bot")

USAGE = "\n".join(
    [
        "`/okozukai add <金額> <メモ>` — 任意金額の追加・訂正(マイナス可、その場合メモ必須)",
        "`/okozukai config` — タスク名・金額・同日重複可否の変更",
        "`/okozukai history [YYYY-MM | YYYY-MM-DD YYYY-MM-DD]` — 記帳履歴",
        "`/okozukai summary` — 月末サマリを今すぐ投稿(cron の動作確認用)",
        "`/okozukai debug` — Bot Token の疎通確認",
    ]
)


def build_app(hardware: HardwareController) -> App:
    app = App(token=config.SLACK_BOT_TOKEN)

    def post_message(payload: dict) -> dict:
        try:
            resp = app.client.chat_postMessage(channel=config.CHANNEL_ID, **payload)
            return {"ok": True, "ts": resp["ts"]}
        except SlackApiError as e:
            return {"ok": False, "error": e.response.get("error", str(e))}

    services.configure(post_message, hardware)

    # --- スラッシュコマンド ---

    @app.command("/okozukai")
    def handle_command(ack, body, client, respond):
        ack()
        text = (body.get("text") or "").strip()
        user_id = body["user_id"]
        parts = text.split()
        sub = parts[0] if parts else ""
        rest = parts[1:]

        if sub == "config":
            _handle_config(client, respond, user_id, body["trigger_id"])
        elif sub == "add":
            _handle_add(respond, user_id, rest)
        elif sub == "history":
            _handle_history(respond, rest)
        elif sub == "summary":
            _handle_summary(respond, user_id)
        elif sub == "debug":
            _handle_debug(client, respond, user_id)
        else:
            respond(replace_original=False, text=f"使い方:\n{USAGE}")

    def _handle_config(client, respond, user_id: str, trigger_id: str) -> None:
        if not services.is_approver(user_id):
            respond(replace_original=False, text="この操作は保護者のみ実行できます。")
            return
        tasks = db.get_active_tasks()
        try:
            client.views_open(trigger_id=trigger_id, view=blocks.config_view(tasks))
        except SlackApiError as e:
            respond(replace_original=False, text=f"モーダルを開けませんでした: {e.response.get('error', e)}")

    def _handle_add(respond, user_id: str, args: list[str]) -> None:
        if not services.is_approver(user_id):
            respond(replace_original=False, text="この操作は保護者のみ実行できます。")
            return
        if not args:
            respond(replace_original=False, text="例: `/okozukai add 330 メルカリ 漫画売却`")
            return
        raw_amount, *memo_parts = args
        ok, result = services.add_manual(user_id, raw_amount, " ".join(memo_parts).strip())
        if ok:
            app_client_post(result)
        else:
            respond(replace_original=False, text=result)

    def app_client_post(payload: dict) -> None:
        try:
            app.client.chat_postMessage(channel=config.CHANNEL_ID, **payload)
        except SlackApiError:
            logger.exception("chat_postMessage に失敗しました")

    def _handle_history(respond, args: list[str]) -> None:
        result = services.history(args)
        if isinstance(result, str):
            respond(replace_original=False, text=result)
        else:
            respond(replace_original=False, **result)

    def _handle_summary(respond, user_id: str) -> None:
        if not services.is_approver(user_id):
            respond(replace_original=False, text="この操作は保護者のみ実行できます。")
            return
        message = services.run_monthly_summary(force=True)
        if message is None:
            respond(replace_original=False, text="集計対象の記帳がありませんでした。")
            return
        app_client_post(message)

    def _handle_debug(client, respond, user_id: str) -> None:
        if not services.is_approver(user_id):
            respond(replace_original=False, text="この操作は保護者のみ実行できます。")
            return
        token = config.SLACK_BOT_TOKEN or ""
        shape = "\n".join(
            [
                f"プレフィックス: `{token[:5] or '(未設定)'}` (期待値: `xoxb-`)",
                f"長さ: {len(token)}",
                f"前後の空白/改行: {'**あり(これが原因)**' if token != token.strip() else 'なし'}",
            ]
        )
        try:
            auth = client.auth_test()
            result = f"✅ auth.test 成功 — team: {auth['team']} / bot: {auth['user']} ({auth['bot_id']})"
        except SlackApiError as e:
            result = f"❌ auth.test 失敗 — `{e.response.get('error', e)}`"
        respond(replace_original=False, text=f"{result}\n\nSLACK_BOT_TOKEN の形:\n{shape}")

    # --- ボタンアクション ---

    @app.action("approve")
    @app.action("reject")
    def handle_decision(ack, body, respond, action):
        ack()
        user_id = body["user"]["id"]
        if not services.is_approver(user_id):
            respond(text="承認・却下は保護者のみ実行できます。", replace_original=False)
            return

        try:
            request_id = int(action["value"])
        except (KeyError, TypeError, ValueError):
            respond(text="申請 ID を特定できませんでした。", replace_original=False)
            return

        message = services.decide(request_id, action["action_id"], user_id)
        if message is None:
            respond(text="この申請は既に処理済みです。", replace_original=False)
            return

        respond(replace_original=True, **message)

    @app.action("pay_all")
    def handle_pay_all(ack, body, respond):
        ack()
        user_id = body["user"]["id"]
        settled, note = services.pay_all(user_id)

        original_blocks = body.get("message", {}).get("blocks", [])
        respond(
            replace_original=True,
            text=note,
            blocks=blocks.strip_pay_all_button(original_blocks) + [
                {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]}
            ],
        )

        if settled:
            app_client_post({"text": f"💴 全額支払い済みにしました({settled}円)。未払い残高: 0円\n実行者: <@{user_id}>"})

    # --- タスク設定モーダルの送信(仕様書 §7) ---

    @app.view("task_config_submit")
    def handle_task_config_submit(ack, body, view):
        parsed, errors = services.parse_config_submission(view["state"]["values"])

        if errors:
            ack(response_action="errors", errors=errors)
            return
        ack()

        user_id = body["user"]["id"]
        lines = services.update_tasks(parsed)
        if lines:
            app_client_post({"text": f"⚙️ タスク設定を更新しました(<@{user_id}>)\n" + "\n".join(lines)})

    return app
