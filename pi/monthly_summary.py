"""月末サマリの自動投稿(仕様書 §14)。cron から実行する。

  5 0 1 * * /home/jhonda/app/pi/.venv/bin/python /home/jhonda/app/pi/monthly_summary.py \
      >> /home/jhonda/logs/monthly_summary.log 2>&1

main.py(Socket Mode 常駐プロセス)とは別プロセスとして毎月1回だけ起動する
軽量スクリプトなので、Bolt App は使わず WebClient で直接投稿する。
"""

from __future__ import annotations

import logging
import sys

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import config
import services

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("okozukai.monthly_summary")


def main() -> int:
    force = "--force" in sys.argv  # 動作確認用(cron は毎月1日にしか実行しないため)

    message = services.run_monthly_summary(force=force)
    if message is None:
        logger.info("今日は集計対象日ではないため何もしません。")
        return 0

    client = WebClient(token=config.SLACK_BOT_TOKEN)
    try:
        client.chat_postMessage(channel=config.CHANNEL_ID, **message)
    except SlackApiError:
        logger.exception("月末サマリの投稿に失敗しました")
        return 1

    logger.info("月末サマリを投稿しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
