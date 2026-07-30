"""設定値。秘密情報は環境変数(.env)、それ以外はここに定数として置く。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# --- 仕様書 §2 の確定値 ---
SLACK_APPROVERS: list[str] = ["U02LS99PPQE", "U02M18CUKPE"]
CHANNEL_ID: str = "C0BLS8KTW90"

# --- Slack 認証情報(.env で上書きする) ---
SLACK_BOT_TOKEN: str = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_APP_TOKEN: str = os.environ.get("SLACK_APP_TOKEN", "")

# --- DB ---
DB_PATH: str = os.environ.get("OKOZUKAI_DB_PATH", str(BASE_DIR / "data" / "okozukai.db"))

# --- 動作モード ---
# True の間は Slack に投稿せず即時承認する(仕様書 §1: 最初のプロトタイプ用)。
AUTO_APPROVE: bool = os.environ.get("OKOZUKAI_AUTO_APPROVE", "false").lower() == "true"

# "dummy" = GPIO/I2C を使わずログ出力のみ(この開発機など、Pi以外での動作確認用)
# "gpio"  = 実機のボタン・LCD・ブザーを使う
HARDWARE_BACKEND: str = os.environ.get("OKOZUKAI_HARDWARE", "gpio")

# --- GPIO ピン配置(配線に合わせて .env で上書きする) ---
BUTTON_PINS: dict[str, int] = {
    "A": int(os.environ.get("OKOZUKAI_BUTTON_PIN_A", "17")),
    "B": int(os.environ.get("OKOZUKAI_BUTTON_PIN_B", "27")),
}
BUZZER_PIN: int = int(os.environ.get("OKOZUKAI_BUZZER_PIN", "22"))
LCD_I2C_ADDRESS: int = int(os.environ.get("OKOZUKAI_LCD_I2C_ADDRESS", "0x27"), 16)
BUTTON_BOUNCE_TIME: float = 0.2  # 秒。タクトスイッチのチャタリング対策

# --- 表示 ---
DISPLAY_MESSAGE_SECONDS: float = 4.0  # 一時メッセージを表示してから残高表示に戻るまでの秒数

# --- §12-1 再送ワーカー ---
POST_RETRY_INTERVAL_SECONDS: float = 20.0

# --- §12-2 起動時・定期の棚卸し ---
RECONCILIATION_INTERVAL_SECONDS: float = 5 * 60.0
RECONCILIATION_PENDING_MINUTES: int = 30

# --- §13 記帳履歴 ---
HISTORY_DETAIL_LIMIT: int = 20

# --- §14 月末サマリ(cron から呼ばれる monthly_summary.py が使う) ---
MONTHLY_SUMMARY_HOUR_JST: int = 0
MONTHLY_SUMMARY_MINUTE_JST: int = 5
