# VRC_Media_Streamer

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
**面倒なサーバー構築やエンコード知識は不要。**
**EXEを起動してURLを貼るだけで、ワールド内の動画プレイヤーにYouTubeが流れ始めます。**

※ 無料枠と有料枠（支援用）の内容は完全に同一です。お金を払っても機能やサポートは増えませんのでご注意ください。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 【ツール概要】

『**VRC_Media_Streamer**』は、YouTubeの動画・プレイリストを自分専用のHLSライブストリーム（`.m3u8`）に変換し、VRChat内の各種動画プレイヤー（iwaSync3, YPlay, ProTV, YamaPlayer 等）でシームレスに再生するためのWindowsアプリケーションです。

もともと作者が自分で使うために個人的に作成したものです。
AIバイブコーディング製のため手厚いサポートはできませんが、「動いたらラッキー」くらいの気持ちで気軽にご利用ください。

- **ソースコード / GitHub**: [https://github.com/sou2000sw/VRC_Media_Streamer](https://github.com/sou2000sw/VRC_Media_Streamer)

---

## ✨ 主な機能と特徴

* **起動してURLを貼るだけ — 事前準備ゼロ**
  Python・FFmpeg・その他ランタイムの事前インストールは一切不要です。ZIPを解凍して EXE を起動するだけですぐに使えます。
* **YouTube動画＆プレイリストの連続再生**
  YouTube URLを入力するだけで、動画の取得 → HLS変換 → ストリーミング配信を自動で行います。プレイリストURLを入れれば一括展開＆連続再生されます。
* **キューのドラッグ＆ドロップ並び替え**
  各行の「☰」マークまたはタイトルをドラッグして直感的に順番を変更できます。リストの上下端に持っていくと自動スクロール。「▲」「▼」ボタンも併用可能です。
* **ループ再生＆シャッフル再生**
  - 🔁 **Loop**: 再生終了した動画をキュー末尾に自動再登録しループ再生。
  - 🔀 **Shuffle**: キューからランダムに次の曲を選出して再生。ループと併用でランダム巡回も可能。
  - 🔀 **Shuffle List**: 現在のキューを一瞬でランダム順に並べ替え。
* **📡 配信先を選べる（TopazChat / HLS + Cloudflare Tunnel / 汎用RTMP）**
  - **TopazChat**（既定・低遅延 約1〜2秒）: RTMPで配信し、ワールドのプレイヤーには `rtspt://` のURLを貼ります。配信には**ストリームキー**が必要です（初回起動ガイドで設定できます）。
  - **HLS + Cloudflare Tunnel**（ストリームキー不要）: 起動するだけで外部アクセス可能な `.m3u8` URLが自動生成されます。ポート開放やDDNSの設定は不要です。
  - **汎用RTMP**: 任意の配信先URL＋キーを手入力。

  配信先へ到達できない場合は自動でローカルHLSへ退避するため、配信自体は途切れません（復帰も指数バックオフで自動試行）。詳細は「[配信先（ストリーミング出力先）の切り替え](#-配信先ストリーミング出力先の切り替え)」を参照してください。
* **🧭 初回起動ガイド（ホストPCの画面にだけ表示）**
  初めて起動したときだけ、ストリームキーの確認・入力から「ワールドの動画プレイヤーに貼るURL」のコピーまでを案内するカードが出ます。キーを使わない「HLS / Cloudflare で始める」「あとで設定する」も選べます。2回目以降は表示されません（設定画面からいつでも変更できます）。
* **📱 スマホQRコードでフレンドからリクエスト受付**
  キューが空になると、待機画面にQRコード＆WebURLが表示されます。フレンドがスマホで読み取ると、Webリモコン画面から動画のリクエストを送れます。アプリ画面上にもQRコード＆WebURLは常時表示されています。
* **🖥 ホスト画面もWebリモコンと同じモダンUI**
  ホストPCのアプリ画面は、スマホで開くWebリモコンとまったく同じ画面です（サイドバーナビ、配信プレビュー、キュー操作、QR共有）。ホスト画面からは加えて、**容量上限なしでPC内の動画・写真を直接追加**でき、待機画像の選択やサーバー設定（ポート・トンネル・Webリモコンの権限やパスワード等）も行えます。
  ※WebView2 が使えない環境では、従来のデスクトップ画面が自動的に開きます（`--classic-ui` で明示指定も可能）。
* **🌐 Webリモコン＆ブラウザ再生**
  ブラウザで `http://localhost:8000/`（またはトンネルURL）にアクセスすると、HLS Web Player による配信プレビューとキュー操作・動画/写真追加が可能です。スマホ縦画面にも最適化されたレスポンシブUIです。
  UIに必要な部品（CSS・アイコン・プレイヤー）はすべてEXEに同梱されているため、ホストPCがインターネットに繋がっていない場面や、外部CDNが遮断された回線でも画面が崩れません。
* **📻 BGM / ラジオモード（超低帯域配信 & サムネイル自動生成）**
  YouTube動画から高音質音声ストリームのみを抽出し、自動生成された「サムネイル＆楽曲情報カード画面」（または待機画面/写真スライドショー）と合成して超低帯域（約250〜350kbps、通常動画比90%以上削減）でHLS配信。VRChatでのバッファ詰まりや多人数インスタンスでの遅延を極小化します。
  曲の変わり目は、頭をフェードイン・終わりをフェードアウトして滑らかに繋ぎます（既定3秒 / `config.json` の `radio_crossfade_duration` で 0〜5秒。0で無効）。
* **🖼️ 写真・画像アップロード＆スライドショー配信**
  スマホやPCから複数枚の画像（JPEG, PNG, WebP等）をまとめてキューへ追加可能。表示秒数切り替え（5s〜120s）や自動送りON/OFFをGUI/Webリモコンからリアルタイム操作できます。
* **🎬 ローカル動画ファイルの配信（MP4 / MOV / WebM 等）**
  YouTube等のURLだけでなく、PC・スマホ内の動画ファイルをそのままキューへ追加してHLS配信できます。追加ルートは2通りで、それぞれ容量上限が異なります。
  - **ホストアプリから追加（容量上限なし）**: GUIの「🎬 Add Video」ボタンから動画ファイルを選択（複数選択可）。ファイルをコピーせず元の場所を直接参照して配信するため、実質的なファイルサイズ上限はありません。
  - **Webリモコン経由でアップロード（容量上限あり）**: スマホ/PCのブラウザからファイル選択またはドラッグ＆ドロップでアップロード。デフォルト上限は **200MB / 1ファイル**（`config.json` の `max_video_upload_mb` で変更可能）。フレンドからの投稿もこちらを使います。

  対応拡張子: `.mp4` / `.mov` / `.webm` / `.mkv` / `.avi` / `.m4v` / `.ts` / `.flv`
  BGM/ラジオモードと併用すると、ローカル動画から音声だけを抽出して超低帯域配信することもできます。
* **⚙ 設定画面 (Settings)**
  サーバーポート、HLSセグメント秒数、動画切り替え待機秒数、Web Player同期バッファ数、Loop/Shuffleのデフォルト設定などをGUIから変更・保存可能。設定画面内にAPI仕様リファレンスも内蔵。
* **🤖 ヘッドレス / APIサーバーモード**
  GUIを表示せずバックグラウンドで動作するAPIサーバーモードを搭載。外部アプリからHTTP JSON API経由で状態取得・キュー追加・再生制御が可能です。
* **🛡️ セキュリティ（多層防御）**
  停止・設定変更などの管理操作はホストPC限定。フレンド向けの操作権限（動画追加 / キュー編集 / 再生制御）は設定画面からON/OFF可能。SSRF防止、連投制限、CSRF対策、キュー上限など基本的な保護機能を備えています。
  - Webリモコン（ゲスト側）には**「配信・QR設定」タブを一切出しません**。ストリームキー・パスワード・権限設定が読めてしまうためで、`/api/status` でもストリームキーはゲストには伏せ字で返します。
  - リモコンURLと共有QRを載せた「接続 & スマホ共有」タブは**既定で非公開**。ホストが `allow_web_share_info` を有効にしたときだけゲストに表示されます（`/api/qrcode` も同じ判定で 403）。
  - 許可フラグが取得できない場合は**非表示側に倒す**（fail-closed）設計です。
  - **🛡️ ホスト専用モード**: `enable_web_remote: false`（設定画面のトグル、または起動時の `--host-only`）で、
    ホストPC以外からのリモコン画面・APIを**すべて 403 で遮断**します。QRオーバーレイと待機画面のQR案内も自動で消えます。
    VRChatが再生に使う `stream.m3u8` / `*.ts` だけは開けたままなので、**配信は止まりません**
    （逆に、視聴そのものを止めたい場合はRTMP押し出し + トンネル無効を選んでください）。
* **🎬 多様な動画元・SNSプラットフォームに対応（実機検証済み）**
  YouTube動画だけでなく、YouTubeショート、YouTubeライブ、X（旧Twitter）動画、Instagramリール動画等、幅広いWeb動画の再生に対応しています。

---

## 🎬 実機動作確認済みの対応動画元・プラットフォーム

内部の `yt-dlp` 解析エンジンにより、以下の動画・配信サービスからのURL抽出およびストリーミング配信が実機で動作確認されています：

| プラットフォーム / ソース | 対応状況 | 補足・詳細 |
|---|---|---|
| **YouTube 通常動画** | ✅ **対応** | 通常動画URL、短縮URL (`youtu.be`)、再生リスト一括追加に対応 |
| **YouTube Shorts（ショート動画）** | ✅ **対応** | `youtube.com/shorts/...` URLをそのままキューへ投入可能 |
| **YouTube Live（ライブ配信）** | ✅ **対応** | 進行中のYouTubeライブ配信のリアルタイム中継・同期配信に対応 |
| **X (旧 Twitter) 動画** | ✅ **対応** | ポスト（ツイート）に含まれる動画URLの自動抽出・再生に対応 |
| **Instagram (インスタグラム) 動画 / Reels** | ✅ **対応** | 投稿動画およびリール（Reels）動画の再生に対応 |
| **Twitch (ツイッチ)** | ⚠️ **一部対応** | 配信チャンネル・クリップにより再生できるものと再生できないものがあります（仕様・DRM等の差異により一部制限あり） |
| **ニコニコ動画** | ❌ **非対応** | ニコニコ動画のURLは現在ご利用いただけません（非対応） |
| **静止画 / 写真ファイル** | ✅ **対応** | JPEG, PNG, WebP 等の写真アップロードおよびスライドショー配信 |
| **ローカル動画ファイル** | ✅ **対応** | MP4, MOV, WebM, MKV, AVI, M4V, TS, FLV。ホストアプリからの追加は容量上限なし／Webリモコン経由は既定200MBまで |

---

## 📦 導入方法

1. **ZIPを展開し、フォルダごと書き込み可能な場所に配置してください。**
   （例: デスクトップ、ドキュメント、`D:\Tools\` など）
   > [!WARNING]
   > `C:\Program Files` や `C:\Program Files (x86)` 直下では権限の都合上、正常に動作しません。必ずユーザー権限で書き込み可能なフォルダに配置してください。

2. **「`VRC_Media_Streamer.exe`」（または同梱のバッチファイル）を起動する。**
   初回だけセットアップの案内が表示されます。既定の TopazChat で配信する場合はここでストリームキーを決め、表示されたURLをワールドの動画プレイヤーへ貼ってください。キーを使いたくない場合は「HLS / Cloudflare で始める」を選べます。

3. **VRChat側の設定を確認する**
   VRChat内のメニューで「信頼されていないURLを許可 (Allow Untrusted URLs)」を有効にしてください。
   （設定: `Settings` ＞ `Downloads & Share` または `快適性とセーフティ`）

> [!NOTE]
> 初回起動時に Windows SmartScreen の警告（「WindowsによってPCが保護されました」）が出る場合があります。個人開発のためコード署名を行っていないことが原因です。「詳細情報」をクリックし、「実行」を選択して起動してください。

---

## 📦 内容物

- `VRC_Media_Streamer.exe`（本体アプリケーション）
- `ffmpeg.exe` / `ffprobe.exe`（動画変換エンジン／同梱必須・同じフォルダに置いてください）
- `config.json`（設定ファイル／初期状態。起動後にアプリが自動で書き換えます）
- `VRC_Media_Streamer (Normal).bat`（通常起動バッチ）
- `VRC_Media_Streamer (Local Test).bat`（ローカル検証用バッチ）
- `VRC_Media_Streamer (Headless Test).bat`（ヘッドレスAPIサーバー用バッチ）
- `README.txt`（説明書）
- `FFmpeg_LICENSE.txt` / `THIRD_PARTY_LICENSES.txt`（ライセンス表記）

> [!NOTE]
> `hls_output` フォルダと `vrc_media_streamer.log` は起動時に自動生成されます（配布物には含まれません）。
> 更新履歴は同梱していません。このリポジトリの [CHANGELOG.md](CHANGELOG.md) を参照してください。

---

## 💻 動作環境

- **対応OS**: Windows 10 / 11 (64bit)
- **ネットワーク**: 安定したインターネット接続（アップロード帯域を使用します）
- **VRChat側**: iwaSync3, YPlay, ProTV, YamaPlayer, KineLister 等、HLS（.m3u8）対応のワールド動画プレイヤー
- **事前インストール**: 不要（必要なランタイム・バイナリは同梱済み）

---

## 🚀 起動方法・起動オプション

### 1. GUIモードで起動
```bash
VRC_Media_Streamer.exe
# または開発時:
python gui_streamer.py
```

### 2. ヘッドレス / APIサーバーモードで起動
```bash
VRC_Media_Streamer.exe --headless --port 8080
# または開発時:
python gui_streamer.py --headless --port 8080
```

#### コマンドライン引数一覧
| 引数 | 説明 | デフォルト値 |
| :--- | :--- | :--- |
| `--headless` / `-hl` | GUIを起動せずバックグラウンドAPIサーバーとして動作 | なし (GUI起動) |
| `--no-tunnel` / `-nt` | Cloudflareトンネルを起動せずローカルテストモードで動作 | なし (トンネル起動) |
| `--tunnel` | Cloudflareトンネルを明示的に有効化 | 有効 (デフォルト) |
| `--port` / `-p` | APIサーバーおよびHLS配信サーバーのポート番号 | `8000` (または `config.json`) |
| `--host` | サーバーのホストアドレス (LAN内共有時は `0.0.0.0`) | `127.0.0.1` |
| `--config` | 使用する `config.json` のパス | 実行ファイルと同じ場所 |
| `--output-mode` | 配信先を一時的に指定 (`hls` / `topaz` / `generic_rtmp`) | `config.json` の値 |
| `--resolution` | RTMP出力の解像度 (`1280x720` 形式) | `1280x720` |
| `--bitrate` | RTMP映像ビットレート (kbps) | `1500` |
| `--fps` | RTMP出力のフレームレート | `30` |
| `--radio` / `--no-radio` | BGM/ラジオモードで起動する / しない | `config.json` の値 |
| `--set KEY=VALUE` | `config.json` の任意の項目を一時的に上書き（複数回指定可） | なし |

#### 設定の優先順位

**CLI引数 ＞ 環境変数 ＞ `config.json` ＞ 既定値** の順で強く、上の層が下の層を上書きします。

> [!IMPORTANT]
> **CLI引数・環境変数で指定した値は「その起動限り」で、`config.json` には保存されません。**
> `--no-tunnel` でローカル検証したあと設定画面から別の項目を保存しても、トンネル設定が
> 書き換わることはありません。逆に、設定画面でその項目自体を明示的に変更した場合は
> 通常どおり保存され、その起動中も変更が反映されます。

環境変数は `VRCMS_` に続けて設定キーを大文字にした名前で指定します
（例: `VRCMS_PORT=8080`、`VRCMS_ENABLE_TUNNEL=0`）。

> [!WARNING]
> ストリームキーやWebリモコンのパスワード（`topaz_stream_key` / `generic_rtmp_key` /
> `web_password`）は **`--set` では指定できません**。コマンドライン引数はOSのプロセス一覧から
> 他の利用者に見えてしまうためです。これらは環境変数
> （`VRCMS_TOPAZ_STREAM_KEY` 等）でのみ指定できます。

```bash
# 例: ローカル検証用に、ポートと配信先だけをその場で変える
VRC_Media_Streamer.exe --no-tunnel --port 8080 --output-mode hls

# 例: config.json の任意の項目を一時的に上書きする
VRC_Media_Streamer.exe --set loop_queue=true --set image_display_duration=30
```

---

## 📡 HTTP API エンドポイント仕様 (JSON / CORS対応)

すべてのエンドポイントで `Access-Control-Allow-Origin: *` が有効です。

### 1. ストリーマー状態取得
* **Method**: `GET`
* **Path**: `/api/status`
* **Response**:
```json
{
  "status": "streaming",
  "status_detail": "Active (Streaming)",
  "tunnel_url": "https://xxxx.trycloudflare.com",
  "stream_url": "https://xxxx.trycloudflare.com/stream.m3u8",
  "video_url": "rtspt://topaz.chat/live/<KEY>",
  "remote_url": "https://xxxx.trycloudflare.com",
  "output_mode": "topaz",
  "active_output_mode": "topaz",
  "current_video": {
    "title": "Rick Astley - Never Gonna Give You Up",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "duration": 213
  },
  "queue": [
    {
      "title": "Next Video Title",
      "url": "https://www.youtube.com/watch?v=...",
      "duration": 180
    }
  ],
  "loop_queue": true,
  "shuffle": false,
  "is_image": false,
  "image_paused": false,
  "image_display_duration": 15,
  "image_auto_advance": false,
  "overlay_qr_enabled": false,
  "overlay_qr_mode": "bottom-right",
  "enable_web_remote": true,
  "permissions": {
    "allow_web_queue_add": true,
    "allow_web_queue_edit": true,
    "allow_web_playback_control": true,
    "enable_web_remote": true
  }
}
```
*(※ `status`: `"offline"` / `"buffering"` / `"streaming"` / `"finishing"` / `"error"`)*

### 2. キュー追加 (URL)
* **Method**: `POST`
* **Path**: `/api/queue`
* **Body**: `{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}`

### 3. メディアアップロード（写真・ローカル動画／単一・複数対応）
* **Method**: `POST`
* **Path**: `/api/upload`
* **Content-Type**: `multipart/form-data` または `image/*` / `video/*`
* **Body**: 画像または動画バイナリ（単一ファイル、または `files[]` による複数ファイル一括送信）
* **サイズ上限**:
  * 画像: **20MB / ファイル**
  * 動画: **200MB / ファイル**（`config.json` の `max_video_upload_mb` で変更可能）
* 画像／動画の判別は拡張子・Content-Type・ファイル先頭シグネチャから自動で行われます。上限超過時は `413` を返します。
* ※ ホストPC上のローカル動画をアップロードなしで再生したい場合は、GUIの「🎬 Add Video」から追加してください（ファイルを直接参照するため容量上限がありません）。

### 4. 再生・キュー制御
* **Method**: `POST`
* **Path**: `/api/control`
* **Body アクション一覧**:
  * **スキップ (次へ)**: `{"action": "skip"}`
  * **📻 BGM/ラジオモードON/OFF**: `{"action": "set_radio_mode", "enabled": true}`
  * **📻 ラジオ背景ソース切替**: `{"action": "set_radio_bg_source", "source": "card"}` *(card / standby / slideshow)*
  * **写真スライドショー一時停止 / 再開トグル**: `{"action": "toggle_image_pause"}`
  * **写真表示秒数変更**: `{"action": "set_image_duration", "duration": 15}` *(5〜120秒)*
  * **写真自動送りON/OFF**: `{"action": "set_image_auto_advance", "enabled": true}`
  * **キュー全消去**: `{"action": "clear_queue"}`
  * **停止＆キュー消去**: `{"action": "stop"}`
  * **キュー即時シャッフル**: `{"action": "shuffle"}`
  * **ループ再生のON/OFF**: `{"action": "set_loop", "enabled": true}`
  * **シャッフル再生のON/OFF**: `{"action": "set_shuffle", "enabled": true}`
  * **指定インデックスの動画/写真削除**: `{"action": "delete_item", "index": 0}`
  * **動画/写真の並べ替え**: `{"action": "move_item", "from_index": 0, "to_index": 2}`

### 5. 接続用 QR コード画像取得
* **Method**: `GET`
* **Path**: `/api/qrcode`
* **Response**: PNG 画像ストリーム

### 6. 設定の取得・更新
* **GET `/api/config`**: 現在の設定JSONを取得
* **POST `/api/config`**: 設定JSONを更新して保存（`config.json` に永続化）

### 7. 配信先の操作（ローカルホスト限定）
* **Method**: `POST`
* **Path**: `/api/destination`
* **Body**:
  * `{"action": "generate_key"}` … TopazChat のストリームキーを新規生成
  * `{"action": "reveal_key"}` … 生のストリームキーを取得（ホスト本人のみ）
  * `{"action": "retry"}` … HLSへ退避中の状態から本来の配信先へ即時復帰を試みる

### 8. サーバー終了
* **Method**: `POST`
* **Path**: `/api/shutdown`

---

## 📡 配信先（ストリーミング出力先）の切り替え

`config.json` の `output_mode`、またはWebリモコン「配信・QR設定」タブ／ホストGUIの設定画面から切り替えます。

| モード | 位置付け | VRChat側の遅延 | 備考 |
| :--- | :--- | :---: | :--- |
| `hls`（既定） | **Cloudflare Quick Tunnel 経由**で配信。他経路が失敗したときの退避先 | 約9〜12秒 | 従来どおりの動作。トンネルを無効(`enable_tunnel: false`)にすると同一LAN内のみの配信になる |
| `topaz` | TopazChat（VRChat向けRTMP→RTSP中継） | 約1〜2秒 | AVProプレイヤーで `rtspt://topaz.chat/live/<KEY>` を再生 |
| `generic_rtmp` | 自前の nginx-rtmp / MediaMTX 等（上級者向け） | 任意 | URLとキーを手入力。規約・著作権の順守は利用者の責任 |

- **接続できないときは自動的に `hls` へ退避**し、配信自体は途切れません（復帰は指数バックオフで再試行）。
- **ストリームキー**は32文字以上のランダム値を自動生成します。短いキーは第三者に配信を乗っ取られます。
  キーは `/api/status` や設定画面ではマスク表示され、生の値はホスト本人のみが取得できます。
- **TopazChat について**: 本ソフトは TopazChat の公式ツールではありません。TopazChat は個人運営の
  無償サービスであり、**法人が運営主体のイベント・番組制作等での利用には別途 TopazChat への問い合わせが
  必要**です。映像は最大2Mbps・音声は最大320kbpsで、超過すると配信が強制切断されます（本ソフトは
  この上限を超える設定値を保存時に自動で丸めます）。
  参考: [TopazChat 公式サイト](https://topaz.chat/) / [GitHub](https://github.com/TopazChat/TopazChat)

---

## ℹ️ 仕様・制限事項

- **URLの再生成**: Cloudflareの一時トンネルを使用しているため、ツールを再起動するたびにストリームURLが変わります。起動中は同じURLで利用できます。
- **YouTubeの仕様変更**: YouTube側の更新により、動画の取得やプレイリストの展開が一時的にできなくなることがあります。
- **ウイルス対策ソフトの誤検知**: コード署名を行っていないため、一部のウイルス対策ソフトが誤検知する場合があります。
- **短時間の大量リクエストによる一時制限**: 短時間に大量の動画URLを連続追加したり、巨大なプレイリストを一気に読み込ませると、YouTube側またはCloudflare側から一時的なアクセス制限（レートリミット / 429エラー）がかかり、一時的に動画が取得できなくなる場合があります。その場合は連投を控え、数分〜10分程度時間を置いてから再度お試しください。（※制限の解除を待つか、回線IPの変更で復旧します）
- **ローカル動画の容量上限**: Webリモコン経由のアップロードは既定で200MB/ファイルまでです（`config.json` の `max_video_upload_mb` で変更可能）。大容量の動画はホストPCのGUI「🎬 Add Video」から追加してください（元ファイルを直接参照するため容量上限はありませんが、その動画ファイルを再生中に移動・削除しないでください）。
- **推奨用途**: 本ツールは常時稼働を想定したものではありません。ワールド内プレイヤーの不調時やURLが読み込めない場合など、一時的なトラブル回避や個人・少人数での検証用途としての利用を推奨します。

---

## ∥ 免責事項

- **個人開発**: 本ツールは個人が自分用に開発したものを公開しているものであり、商用製品ではありません。
- **自己責任の原則**: 本ツールの使用によって生じたいかなる損害・損失・トラブルについて、製作者は一切の責任を負いません。自己責任においてご利用ください。
- **動作保証の範囲**: 特定の環境・動画・プレイリストでの動作を完全に保証するものではありません。作者の環境ではだいたい動いています。
- **外部サービスへの依存**: YouTube・Cloudflareなど外部サービスの仕様変更・障害により、ツールの機能が利用できなくなる場合があります。これらは製作者の管理外です。
- **サポートについて**: 個人の趣味開発のため、不具合報告は受け付けますが、対応時期や修正をお約束するものではありません。
- **非公式ツール**: 本ツールはYouTube・VRChat・Cloudflareの公式ツールではありません。各サービスの利用規約は利用者ご自身でご確認ください。

---

## ⚖️ ライセンス / LICENSE

本パッケージには、動画変換処理を行う外部ツールとして **FFmpeg（GPL v3）** の実行ファイルが同梱されています。本アプリはFFmpegのバイナリを改変せず、独立した外部プロセスとして呼び出しています。
→ 詳細は同梱の「`FFmpeg_LICENSE.txt`」を参照してください。

その他、以下のオープンソースソフトウェア・ライブラリを利用しています：
- **cloudflared** (Apache-2.0)
- **yt-dlp** (The Unlicense)
- **Python / Tcl/Tk**
- **CustomTkinter** (MIT License)
- **Pillow** (HPND License)
- **qrcode** (BSD License)
- **hls.js** (Apache-2.0)
→ 詳細は同梱の「`THIRD_PARTY_LICENSES.txt`」を参照してください。
