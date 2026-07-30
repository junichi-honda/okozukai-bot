# おこづかいカウンター Bot

長男(9歳)専用のおこづかい管理 Slack アプリ。タスク(お風呂掃除・皿洗いなど)の
ボタン申請を保護者が Slack 上で承認/却下し、未払い残高を管理する。

- 保護者2名を毎回メンションして申請を通知
- 承認・却下いずれのメッセージにも未払い残高と「全額支払い済みにする」ボタンを表示
- `/okozukai add` で任意金額の追加・訂正(メルカリ売上などの不定期収入にも対応)
- `/okozukai config` でタスク名・金額・同日重複可否をモーダルから変更
- `/okozukai history` で記帳履歴を期間指定で確認
- 月末に自動でサマリを投稿

## 現在の状態

本番は Raspberry Pi 4 上で Slack Bolt(Socket Mode)+ SQLite + LCD/ブザー/ボタンで
動かす(`pi/`)。Slack 側のロジックは事前に Cloudflare Workers + D1 のテスト
デプロイ版(`cloudflare/`)で検証済みで、そちらは動作確認用として残してある。

→ Pi 4 版のセットアップ手順は [`pi/README.md`](pi/README.md)
→ Cloudflare テスト版は [`cloudflare/README.md`](cloudflare/README.md)

## ディレクトリ構成

```
pi/           Raspberry Pi 4 向け本実装(Slack Bolt Socket Mode + SQLite + LCD/ブザー/ボタン)
cloudflare/   Cloudflare Workers + D1 によるテスト実装(HTTP モード)
```
