"""Pi 4 上で常時起動するエントリポイント(仕様書 §3, §4, §11, §12)。

- DB 初期化
- LCD/ブザー/ボタンの起動(HardwareController)
- Slack Bolt (Socket Mode) の起動
- §12-1 再送ワーカー・§12-2 棚卸しワーカーの起動
- Bolt 本体をこのスレッドでブロッキング実行
"""

from __future__ import annotations

import logging
import threading
import time

import config
import db
import services
from hardware import HardwareController
from slack_bot import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("okozukai.main")


def _run_periodic(name: str, interval_seconds: float, fn) -> None:
    def loop() -> None:
        while True:
            time.sleep(interval_seconds)
            try:
                fn()
            except Exception:
                logger.exception("%s の実行に失敗しました", name)

    threading.Thread(target=loop, name=name, daemon=True).start()


def main() -> None:
    if config.AUTO_APPROVE:
        logger.warning("AUTO_APPROVE=true です。Slack には投稿されず、申請は即時承認されます(§1 のプロトタイプモード)。")
    if not config.AUTO_APPROVE and not (config.SLACK_BOT_TOKEN and config.SLACK_APP_TOKEN):
        raise SystemExit(
            "SLACK_BOT_TOKEN / SLACK_APP_TOKEN が未設定です。.env を設定するか、"
            "動作確認のみなら OKOZUKAI_AUTO_APPROVE=true を指定してください。"
        )

    db.init_db()

    hardware = HardwareController(balance_provider=db.get_balance)
    hardware.register_buttons(on_press=services.handle_button_press)
    hardware.start()

    if config.AUTO_APPROVE:
        # Slack を使わないプロトタイプモードではボタン監視のみで待機する
        services.configure(post_message=lambda payload: {"ok": False, "error": "auto_approve"}, hardware=hardware)
        logger.info("AUTO_APPROVE モードで待機します。Ctrl+C で終了。")
        threading.Event().wait()
        return

    app = build_app(hardware)

    services.reconciliation_sweep()  # 起動時の棚卸し(§12-2)
    _run_periodic("retry-unposted", config.POST_RETRY_INTERVAL_SECONDS, services.retry_unposted_requests)
    _run_periodic("reconciliation-sweep", config.RECONCILIATION_INTERVAL_SECONDS, services.reconciliation_sweep)

    from slack_bolt.adapter.socket_mode import SocketModeHandler

    logger.info("Socket Mode で待機します。Ctrl+C で終了。")
    SocketModeHandler(app, config.SLACK_APP_TOKEN).start()


if __name__ == "__main__":
    main()
