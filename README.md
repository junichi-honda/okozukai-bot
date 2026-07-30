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

最終的には Raspberry Pi 4 上で Slack Bolt(Socket Mode)+ SQLite として動かす想定。
現時点では **Cloudflare Workers + D1 を使ったテストデプロイ版**のみを実装している。

→ 詳細・セットアップ手順は [`cloudflare/README.md`](cloudflare/README.md) を参照。

## ディレクトリ構成

```
cloudflare/   Cloudflare Workers + D1 によるテスト実装(HTTP モード)
```

Pi 4 向けの Python 実装(Socket Mode + SQLite)は未着手。
