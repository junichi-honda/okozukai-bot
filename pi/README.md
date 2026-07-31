# おこづかいカウンター Bot(Raspberry Pi 4 版)

Pi 4 上で常時稼働し、タクトスイッチ(ボタン)・I2C LCD1602・アクティブブザーと、
Slack Bolt(Socket Mode)を組み合わせて動く。外部公開 URL は不要。

先に Cloudflare Workers 版(`../cloudflare/`)で Slack 側のロジックを検証済み。
本実装はそのロジックを踏襲しつつ、LCD/ブザー制御・オフライン時の再送/棚卸しを
追加で実装している。

このドキュメントは、**ゼロから(SD カードすら作っていない状態から)実機を
動かすまでの完全な手順**をまとめたものです。

---

## 必要なもの

| 部品 | 備考 |
|---|---|
| Raspberry Pi 4 | メモリ容量は問わない |
| microSD カード | 16GB 以上、Class10 相当推奨 |
| microSD カードリーダー | 作業用 PC に SD スロットが無い場合 |
| USB-C 電源 | 5V/3A 出力のもの推奨 |
| I2C 接続 LCD1602(PCF8574 バックパック付き) | I2C アドレスは基板により `0x27` または `0x3F` |
| タクトスイッチ ×2〜 | お手伝いメニューの数だけ |
| アクティブブザー(3ピン: VCC / GND / I/O) | **「低レベルトリガー」型かどうかを商品説明で確認**(後述) |
| ブレッドボード、ジャンパー線(オス-メス) | |
| (任意)冷却ファン | 24時間稼働させる場合は推奨 |

---

## 1. SD カードの準備(Raspberry Pi Imager)

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/) を作業用 PC にインストールして起動
2. **デバイス**: Raspberry Pi 4
3. **OS**: Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**(デスクトップ不要のため Lite でよい)
4. **ストレージ**: 使用する microSD カードを選択
5. 「次へ」の後に出る **OS Customisation(歯車アイコン)** で以下を設定する

   - **一般タブ**
     - ホスト名: 任意(例 `okozukai`)
     - ユーザー名/パスワード: **ユーザー名は `pi` にする**(本リポジトリの
       `systemd/okozukai-bot.service` や README の手順が `pi` ユーザー前提のため。
       別名にする場合は該当箇所を読み替えること)
     - Wi-Fi: SSID・パスワード・国コード(`JP`)
     - ロケール: タイムゾーン `Asia/Tokyo`、キーボードレイアウト `jp`
   - **サービスタブ**
     - SSH を有効化 → **パスワード認証**を選択

6. 「保存」→「次へ」→ 書き込み

### 既知の注意点: カスタマイズ設定が反映されないことがある

まれに、上記で設定した内容(ホスト名・ユーザー・SSH 有効化など)が
**実際には書き込まれない**ことがある(Raspberry Pi Imager 側の問題と見られる)。
書き込み後、SD カードを PC に挿し直して次を確認するとよい。

- `bootfs` パーティション(FAT32、`/boot/firmware` 相当)を開く
- `user-data` というファイルをテキストエディタで開く
- 中身が **すべて `#` から始まるコメント行だけ**(例:
  `#hostname: raspberrypi` のように行頭に `#` が付いている)なら、
  カスタマイズが反映されていない。**Imager で書き込みからやり直すこと**
- `hostname: okozukai` のように `#` の付いていない行が実際に入っていれば正常

書き込み直後は SSH が使えるようになるまで数分かかることがある(初回起動処理)。
しばらく待っても `ssh <ユーザー名>@<ホスト名>.local` に繋がらない場合は、
本ドキュメント末尾の「トラブルシューティング」を参照。

---

## 2. 配線

Pi の電源を**必ず切ってから**配線すること。GPIO ヘッダーのピン番号は、
USB/LAN ポート側を手前にして置いたときの物理ピン番号(BCM 番号ではない)。
Pin 1 は基板上で四角いパッドになっている、SD カードスロットに一番近い角。

### LCD1602(I2C、4ピン: GND / VCC / SDA / SCL)

| LCD 側 | Pi 側(物理ピン番号) |
|---|---|
| GND | 6番(または他の GND ピン) |
| VCC | 2番(**5V**) |
| SDA | 3番(GPIO2) |
| SCL | 5番(GPIO3) |

### ボタン(タクトスイッチ、GND と GPIO の2本のみ使用)

| | Pi 側(物理ピン番号) |
|---|---|
| ボタン A 信号線 | 11番(GPIO17) |
| ボタン B 信号線 | 13番(GPIO27) |
| どちらも GND | 上記 LCD の GND と共有可 |

コード側は `Button(pin, bounce_time=0.2)`(内部プルアップ、押下で LOW)を
前提にしているので、ボタンの反対側の足は GND に繋ぐだけでよい(プルアップ
抵抗の追加は不要)。

### ブザー(3ピン: VCC / GND / I/O)

| ブザー側 | Pi 側(物理ピン番号) |
|---|---|
| VCC | **17番(3.3V)**(LCD の5Vレールとは別にすること。理由は下記) |
| GND | 共有 GND でよい |
| I/O | 15番(GPIO22) |

**重要: ブザーの VCC は 3.3V に接続すること(5V ではない)。**

「低レベルトリガー」型のアクティブブザーは、VCC と I/O の**電位差**を見て
ON/OFF を判定する。VCC を 5V に繋いだ状態で GPIO の HIGH(3.3V)を出力しても、
まだ 1.7V の電位差が残ってしまい、「OFF のつもり」でも鳴り続けることがある。
VCC を Pi の 3.3V に合わせておけば、GPIO の HIGH = VCC と同電位になり、
確実に OFF にできる。

またこの理由により、**LCD(5V 必須)とブザー(3.3V)は電源レールを
共有しないこと**。ブレッドボード上で LCD 用と別の行・別のジャンパー線を
用意すること。

商品説明に「低レベルトリガー」「Low level trigger」の記載が無い、あるいは
違うタイプのブザーを使う場合は、`hardware.py` の `_BuzzerBackend` にある
`active_high=False` を実際の挙動に合わせて調整すること。

---

## 3. Slack アプリの作成

1. https://api.slack.com/apps → **Create New App** → **From scratch** → アプリ名・ワークスペースを指定
2. **Settings > Socket Mode** → ON にする
   - 表示される **App-Level Token** を生成(スコープ `connections:write`)→ `xapp-...` を控える(`.env` の `SLACK_APP_TOKEN`)
3. **Features > OAuth & Permissions**
   - **Scopes > Bot Token Scopes** に `chat:write` と `commands` を追加
   - ページ上部の **Install to Workspace** を実行
   - 発行される **Bot User OAuth Token**(`xoxb-...`)を控える(`.env` の `SLACK_BOT_TOKEN`)
4. **Features > Slash Commands** → **Create New Command**
   - Command: `/okozukai`
   - Socket Mode 使用時は Request URL は不要
5. **Features > Interactivity & Shortcuts** → ON にする(Request URL は不要)
6. 申請を投稿したいプライベートチャンネルを作成し、作成した Bot を招待する(`/invite @<Botの表示名>`)
7. **チャンネル ID を控える**: チャンネル名をクリック → 一番下にスクロール → `C` から始まる文字列(`.env` の `CHANNEL_ID`)
8. **承認者(保護者)の Slack ユーザー ID を控える**: 各ユーザーのプロフィールを開く →
   「…」その他の操作 → **メンバーIDをコピーする**(`U` から始まる文字列。
   `.env` の `SLACK_APPROVERS` にカンマ区切りで複数指定)

---

## 4. ソフトウェアのセットアップ

SSH で Pi に接続してから作業する(`ssh pi@<ホスト名>.local`、または IP アドレス指定)。

### I2C の有効化

```bash
sudo raspi-config nonint do_i2c 0
```

または `sudo raspi-config` → **Interface Options > I2C** → 有効化。反映後、
以下でアドレスが見えるか確認する(LCD 側は `0x27` または `0x3F`)。

```bash
sudo apt-get install -y i2c-tools
sudo i2cdetect -y 1
```

### アプリの配置

```bash
git clone <このリポジトリのURL> ~/app/okozukai-bot
cp -r ~/app/okozukai-bot/pi ~/app/pi   # systemd unit は ~/app/pi 前提のため
cd ~/app/pi

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`lgpio`(gpiozero のピンファクトリ)のビルドに失敗する場合、ビルドツールと
ライブラリが不足している。以下でインストールしてから再実行する。

```bash
sudo apt-get install -y swig python3-dev liblgpio-dev
pip install lgpio
```

### `.env` の作成

```bash
cp .env.example .env
nano .env
```

以下を実際の値に書き換える。

- `SLACK_APP_TOKEN`(`xapp-...`)
- `SLACK_BOT_TOKEN`(`xoxb-...`)
- `CHANNEL_ID`(手順3で控えたチャンネル ID)
- `SLACK_APPROVERS`(手順3で控えたユーザー ID、カンマ区切り)
- `OKOZUKAI_BUTTON_PIN_A` / `_B` / `OKOZUKAI_BUZZER_PIN` / `OKOZUKAI_LCD_I2C_ADDRESS`
  — 配線を上記と変えた場合はここも合わせる

### タイムゾーンの確認

```bash
timedatectl   # Asia/Tokyo になっているか確認
```

### 動作確認

```bash
# ハードウェア無しでロジックだけ検証(Pi以外の環境でも動く)
python smoke_test.py

# 実機で起動(Ctrl+C で終了)
python main.py
```

まず Slack 無しで配線・DB を確認したい場合は `.env` の
`OKOZUKAI_AUTO_APPROVE=true` を指定する(プロトタイプモード)。ボタンを押すと
即時承認され、LCD 残高が更新される。Slack を使う本番では `false` に戻すこと。

---

## 5. systemd での常駐

```bash
sudo cp systemd/okozukai-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now okozukai-bot
journalctl -u okozukai-bot -f
```

`systemd/okozukai-bot.service` は `User=pi` / `/home/pi/app/pi` を前提に
書いてある。ユーザー名やパス配置を変えた場合は書き換えること。

---

## 6. 月末サマリの cron 登録

```
5 0 1 * * /home/pi/app/pi/.venv/bin/python /home/pi/app/pi/monthly_summary.py >> /home/pi/logs/monthly_summary.log 2>&1
```

cron は毎月1日にしか動かないため、動作確認は Slack 上で `/okozukai summary`
を実行するとよい(即時投稿される)。

---

## コマンド一覧

| コマンド/操作 | 内容 |
|---|---|
| (物理ボタン A / B) | 申請作成。同日重複はタスクごとに設定可能 |
| `/okozukai help` | 使い方一覧を表示 |
| `/okozukai add <金額> <メモ>` | 任意金額の追加・訂正(マイナス可、その場合メモ必須) |
| `/okozukai config` | タスク名・金額・同日重複可否をモーダルで変更 |
| `/okozukai history [YYYY-MM \| YYYY-MM-DD YYYY-MM-DD]` | 記帳履歴(ephemeral) |
| `/okozukai summary` | 月末サマリを即時投稿(cron の動作確認用) |
| `/okozukai debug` | Bot Token の疎通確認 + テスト記帳の一括削除ボタン |

`/okozukai press` はこのバージョンには無い(実機ボタンがあるため)。
Cloudflare のテスト版だけに存在するコマンド。

---

## トラブルシューティング

### 書き込み後、しばらく待っても SSH に繋がらない(`connection refused`)

1. まず `ping <ホスト名>.local` で応答があるか確認する。応答が無ければ
   ネットワーク接続(特に Wi-Fi)自体が失敗している可能性が高い。
   ルーターの管理画面で DHCP リース一覧を確認し、Pi らしき端末
   (MAC アドレスが `b8:27:eb` / `dc:a6:32` / `d8:3a:dd` などで始まる)が
   見えるか確認する。見えなければ Wi-Fi 設定(SSID・パスワード)を疑う。
   有線 LAN を一時的に使うと切り分けが早い。
2. ping は通るのに SSH だけ拒否される場合、SD カードの `bootfs` パーティションで
   `user-data` の中身を確認する(上記「1. SD カードの準備」参照)。
   設定がコメントアウトされたテンプレートのままなら書き込みからやり直す。
3. 一度正しく設定を書き込んだはずなのに直らない場合、Pi 側に
   **cloud-init の実行済みキャッシュ**が残っていて、新しい設定を
   「既に処理済み」として無視している可能性がある。SD カードを PC に
   戻し、root 権限で以下を実行してからブートし直すと解消することがある。

   ```bash
   sudo rm -rf /media/<ユーザー名>/rootfs/var/lib/cloud
   ```

   (`rootfs` パーティションのマウント先はディストリビューションにより異なる)

### `i2cdetect` にアドレスが出ない

- LCD の配線(特に GND・VCC)を再確認する
- `sudo raspi-config nonint get_i2c` で I2C が有効か確認する(`0` が有効)
- ブレッドボードの穴自体が劣化していることもあるので、別の行に挿し直してみる

### ボタンを押しても Slack に反応が無い

- 同じタスクを同日 2 回目以降押すと、`allow_duplicate_same_day` が
  `0`(デフォルト)の場合は正常に「重複」としてブロックされる(ブザーが
  短音2回鳴る)。これはバグではない
- `journalctl -u okozukai-bot -f` を実行しながら押してみて、
  `ボタン押下を検知しました` のログが出るか確認する。出なければ
  ソフトウェアではなく配線(特にブレッドボードの接触不良)を疑う。
  タクトスイッチの4本足のうち正しい2本(短絡していない対角ではない
  組み合わせ)を使っているかも確認する

### ブザーが GPIO の状態に関係なく鳴り続ける

上記「2. 配線」のブザーの項を参照。VCC が 5V に繋がっていないか確認する。
`sudo gpioset -c gpiochip0 22=1`(HIGH に固定)・`22=0`(LOW に固定)を
それぞれ数秒実行して、鳴り方が変わるか確認すると原因の切り分けになる。

---

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
  という1つのキューに積み、専用スレッドだけが I2C バスと LCD を触る**設計。
- `sqlite3.Connection` はスレッドを跨げないため、`db.py` は `threading.local()`
  でスレッドごとに接続を持つ。`PRAGMA busy_timeout=5000` を設定しているので、
  複数スレッドが同時に書き込んでも `database is locked` にはならず待機する。
- 日付境界は SQLite の `date(x, 'localtime')` を使わず、Python 側で
  `zoneinfo("Asia/Tokyo")` から JST 文字列を作って bind している
  (`created_at` 自体が JST 文字列で保存されているため、`'localtime'` を使うと
  二重に9時間ずれる)。

## オフライン対策の実装

- **投稿の取りこぼし対策**: `requests` は先に `slack_ts=NULL` で INSERT
  してから Slack へ投稿する。投稿に失敗しても行は `pending` のまま残し、
  20秒ごとの再送ワーカー(`services.retry_unposted_requests`)が
  `slack_ts IS NULL AND status='pending'` を拾って再送する。
- **起動時・定期の棚卸し**: 起動時と5分ごとに、作成から30分以上
  経過した `pending` 件数を LCD に一時表示する(Bolt の低レベルな
  再接続イベントには依存せず、定期実行で代替している)。
- **冪等性**: `approve`/`reject` は `WHERE status='pending'` 条件付き
  UPDATE、`pay_all` は毎回最新の残高を取得してから精算するため、
  再送・再試行で重複処理は起きない。

## この開発機など、Pi 以外での動作確認について

`OKOZUKAI_HARDWARE=dummy` にすると GPIO/I2C を使わず、LCD 表示・ブザーは
ログに出力するだけになる。`smoke_test.py` はこのモードでロジック層
(申請・重複チェック・承認/却下・全額支払い・任意追加・履歴・月末サマリ・
再送/棚卸しワーカー・記帳履歴の一括削除)を一通り検証する。**実機の
GPIO・I2C・タクトスイッチの物理的な動作は Pi 実機でのみ確認できる**。
