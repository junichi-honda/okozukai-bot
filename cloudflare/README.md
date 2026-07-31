# おこづかいカウンター Slack アプリ(Cloudflare Workers テスト版)

`おこづかいカウンター_Slackアプリ仕様書.md` の Slack 側ロジックを、Pi 4 の代わりに
Cloudflare Workers + D1 で動かすテスト実装。

## Pi 4 版との差分

| 項目 | 仕様書(Pi 4) | この実装(Cloudflare) |
|---|---|---|
| Slack 接続方式 | Socket Mode(外部公開 URL 不要) | **HTTP モード**(Request URL + 署名検証) |
| DB | Pi 4 内の SQLite | **D1**(SQLite 互換) |
| 日付境界 | `date(x, 'localtime')` = JST | Workers は常に UTC なので **JST 文字列を JS 側で生成**して保存・比較 |
| 月末サマリ | cron 毎月1日 00:05 JST | **Cron Trigger `5 15 * * *` (UTC) を毎日実行**し、JST で1日かを判定 |
| ボタン入力 | タクトスイッチ | **`/okozukai press A|B`** で代替 |
| LCD / ブザー(§11) | あり | なし(ハードウェアが無いため実装しない) |
| オフライン対策(§12) | 再送ワーカー・棚卸し | 不要(Worker は常時オンライン)なので未実装 |

## セットアップ

```bash
cd cloudflare
npm install
npx wrangler login

# D1 を作成し、出力された database_id を wrangler.jsonc に貼る
npx wrangler d1 create okozukai-bot

# スキーマ + 初期タスク(A: お風呂掃除 20円 / B: 皿洗い 10円)を投入
npx wrangler d1 migrations apply okozukai-bot --remote

npx wrangler deploy

# Slack の認証情報・ワークスペース固有の値を登録(このリポジトリには値を含めない)
npx wrangler secret put SLACK_BOT_TOKEN       # xoxb-...
npx wrangler secret put SLACK_SIGNING_SECRET  # Basic Information の Signing Secret
npx wrangler secret put CHANNEL_ID            # 申請を投稿するチャンネルの ID(C から始まる文字列)
npx wrangler secret put SLACK_APPROVERS       # 承認者の Slack ユーザー ID をカンマ区切りで(例: U0000000000,U0000000001)
```

### Slack アプリ側の設定(HTTP モード用)

1. **Settings > Socket Mode → OFF**(ON のままだと Request URL が使われない)
2. **Slash Commands > /okozukai** の Request URL に `https://<worker>.workers.dev/`
3. **Interactivity & Shortcuts → ON**、Request URL に同じ URL
4. Bot Token Scopes: `chat:write`, `commands`
5. `CHANNEL_ID` に指定したチャンネルに Bot を招待

`xapp-...`(App-Level Token)は Socket Mode 専用で、HTTP モードでは使わない。

## コマンド

| コマンド | 内容 |
|---|---|
| `/okozukai press A` | 端末ボタン押下の代替。同日重複チェック後に申請を投稿 |
| `/okozukai add 330 メルカリ 漫画売却` | 任意金額の追加(マイナス可・その場合メモ必須) |
| `/okozukai config` | タスク名・金額・同日重複可否をモーダルで変更 |
| `/okozukai history [YYYY-MM \| YYYY-MM-DD YYYY-MM-DD]` | 記帳履歴(ephemeral) |
| `/okozukai summary` | 月末サマリを即時投稿(cron は毎月1日のみ発火するため動作確認用) |

## ローカル確認

```bash
npx wrangler d1 migrations apply okozukai-bot --local
npx wrangler dev
# 月末サマリのテスト(scheduled ハンドラを手動実行)
npx wrangler dev --test-scheduled
curl "http://localhost:8787/__scheduled"
```

ローカルでは Slack 署名検証が通らないため、`.dev.vars` に
`SLACK_SIGNING_SECRET` / `SLACK_BOT_TOKEN` を置いて実際の Slack から
トンネル経由で叩くか、`wrangler tail` で本番ログを見るのが早い。
