# おこづかいカウンター Bot(Raspberry Pi 4 版)

`おこづかいカウンター_Slackアプリ仕様書.md` の本実装。Pi 4 上で常時稼働し、
タクトスイッチ(ボタン)・I2C LCD1602・アクティブブザーと、Slack Bolt
(Socket Mode)を組み合わせて動く。外部公開 URL は不要。

先に Cloudflare Workers 版(`../cloudflare/`)で Slack 側のロジックを検証済み。
本実装はそのロジックを踏襲しつつ、仕様書 §11(LCD/ブザー)・§12(オフライン対策)
を追加で実装している。

## 構成

```
config.py            設定値・環境変数の読み込み
time_utils.py         JST 固定の日時ユーティリティ
db.py                 SQLite アクセス層(スレッドごとに接続を持つ)
schema.sql             tasks / requests / ledger
blocks.py              Slack Block Kit メッセージ組み立て
hardware.py             LCD・ブザー・ボタン制御(実機/dummyの2backend)
services.py             ボタン・Slackの両方から呼ばれる業務ロジック本体
slack_bot.py            Slack Bolt (Socket Mode) アプリ
main.py                 常駐プロセスのエントリポイント
monthly_summary.py       月末サマリ投稿(cron から実行)
smoke_test.py            ハードウェア/Slack無しでロジックを検証するスクリプト
systemd/okozukai-bot.service
```

## アーキテクチャのポイント

- **1プロセス・複数スレッド構成**。`main.py` が DB 初期化 → `HardwareController`
  (LCD/ブザー/ボタン)の起動 → Slack Bolt (Socket Mode) の起動、の順で立ち上げる。
- ボタン押下(gpiozero のコールバックスレッド)も Slack のアクション/コマンド
  (Bolt のイベントスレッド)も、両方とも `services.py` の同じ関数を経由して
  DB を更新する。**LCD 表示はどちらから来た更新も `HardwareController.display_queue`
  という1つのキューに積み、専用スレッドだけが I2C バスと LCD を触る**
  (仕様書 §1 の「同じ Queue に push するだけで済む設計」に対応)。
- `sqlite3.Connection` はスレッドを跨げないため、`db.py` は `threading.local()`
  でスレッドごとに接続を持つ。`PRAGMA busy_timeout=5000` を設定しているので、
  複数スレッドが同時に書き込んでも `database is locked` にはならず待機する。
- 日付境界は SQLite の `date(x, 'localtime')` を使わず、Python 側で
  `zoneinfo("Asia/Tokyo")` から JST 文字列を作って bind している
  (`created_at` 自体が JST 文字列で保存されているため、`'localtime'` を使うと
  二重に9時間ずれる)。

## 仕様書 §12(オフライン対策)の実装

- **§12-1 投稿の取りこぼし対策**: `requests` は先に `slack_ts=NULL` で INSERT
  してから Slack へ投稿する。投稿に失敗しても行は `pending` のまま残し、
  20秒ごとの再送ワーカー(`services.retry_unposted_requests`)が
  `slack_ts IS NULL AND status='pending'` を拾って再送する。
- **§12-2 起動時・定期の棚卸し**: 起動時と5分ごとに、作成から30分以上
  経過した `pending` 件数を LCD に一時表示する(Bolt の低レベルな
  再接続イベントには依存せず、定期実行で代替している)。
- **§12-3 冪等性**: `approve`/`reject` は `WHERE status='pending'` 条件付き
  UPDATE、`pay_all` は毎回最新の残高を取得してから精算するため、
  再送・再試行で重複処理は起きない。

## セットアップ(Pi 4 実機)

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# SLACK_APP_TOKEN(xapp-...)/ SLACK_BOT_TOKEN(xoxb-...)を入力
# GPIO ピン番号を実際の配線に合わせて調整
```

Slack アプリ側は仕様書 §4 の通り(Socket Mode ON、Bot Token Scopes:
`chat:write` / `commands`、Slash Command `/okozukai`、Interactivity ON)。
Cloudflare 版のために Socket Mode を OFF にしていた場合は、Pi 版を動かす前に
**再度 ON に戻すこと**。

タイムゾーンの確認:

```bash
timedatectl   # Asia/Tokyo になっているか確認
```

動作確認:

```bash
# ハードウェア無しでロジックだけ検証(この開発機など Pi 以外でも動く)
python smoke_test.py

# 実機で起動(Ctrl+C で終了)
python main.py
```

まず Slack 無しで配線・DB を確認したい場合は `.env` の
`OKOZUKAI_AUTO_APPROVE=true` を指定する(仕様書 §1 のプロトタイプモード)。
ボタンを押すと即時承認され、LCD 残高が更新される。Slack を使う本番では
`false` に戻すこと。

## systemd での常駐

```bash
sudo cp systemd/okozukai-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now okozukai-bot
journalctl -u okozukai-bot -f
```

`systemd/okozukai-bot.service` 内のパス(`/home/pi/app/pi/...`)は
実際の配置場所に合わせて書き換えること。

## 月末サマリの cron 登録(仕様書 §14)

```
5 0 1 * * /home/pi/app/pi/.venv/bin/python /home/pi/app/pi/monthly_summary.py >> /home/pi/logs/monthly_summary.log 2>&1
```

cron は毎月1日にしか動かないため、動作確認は `--force` を付けて手動実行するか、
Slack 上で `/okozukai summary` を実行する。

## コマンド

| コマンド | 内容 |
|---|---|
| (物理ボタン A / B) | 申請作成。同日重複は §6 の通りタスクごとに設定可能 |
| `/okozukai add <金額> <メモ>` | 任意金額の追加・訂正(マイナス可、その場合メモ必須) |
| `/okozukai config` | タスク名・金額・同日重複可否をモーダルで変更 |
| `/okozukai history [YYYY-MM \| YYYY-MM-DD YYYY-MM-DD]` | 記帳履歴(ephemeral) |
| `/okozukai summary` | 月末サマリを即時投稿(cron の動作確認用) |
| `/okozukai debug` | Bot Token の疎通確認(`auth.test` + トークンの形の診断) |

`/okozukai press` はこのバージョンには無い(実機ボタンがあるため)。
Cloudflare のテスト版だけに存在するコマンド。

## この開発機など、Pi 以外での動作確認について

`OKOZUKAI_HARDWARE=dummy` にすると GPIO/I2C を使わず、LCD 表示・ブザーは
ログに出力するだけになる。`smoke_test.py` はこのモードでロジック層
(申請・重複チェック・承認/却下・全額支払い・任意追加・履歴・月末サマリ・
再送/棚卸しワーカー)を一通り検証する。**実機の GPIO・I2C・タクトスイッチの
物理的な動作は Pi 実機でのみ確認できる**(この開発機には接続されていないため
未検証)。
