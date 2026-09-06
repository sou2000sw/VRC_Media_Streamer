# 🔮 将来の機能拡張案・バックログ (Future Ideas & Backlog)

本ドキュメントは、VRC_Media_Streamer のバージョンアップ計画、タスク進捗状況、および将来の設計案を記録するバックログです。

---

## 📋 タスク進捗一覧・ステータス表 (Roadmap & Implementation Status)

| No. | カテゴリ | タスク名 / 機能概要 | バージョン | 状態 |
| :---: | :--- | :--- | :--- | :---: |
| **1** | 📻 ラジオ機能 | **YouTubeサムネイル＆ラジオ番組風カード画面の自動生成** (Radio Card Visualizer) | v2.2.0 | 🟢 **実装完了 ✅** |
| **2** | 🔒 セキュリティ | **Webリモコンのパスワード/PIN認証保護機能** (Password Protection) | v2.3.0 | 🟢 **実装完了 ✅** |
| **3** | 🔀 キュー操作 | **キューの表示専用ソート＆種別絞り込み機能** (Display Sort & Filtering) | v2.3.0 | 🟢 **実装完了 ✅** |
| **4** | 📊 帯域・診断 | **配信ビットレート・遅延・FPSのリアルタイム診断表示** (Diagnostics Dashboard) | v2.4.0 | 🟢 **実装完了 ✅** |
| **5** | 📱 UI/統合 | **スマホ向け写真・スクショ一括アップロード機能** (Batch Photo Upload) | v2.4.0 | 🟢 **実装完了 ✅** |
| **6** | 🖼️ 背景選択 | **BGM/ラジオモード時の背景切り替え機能** (Radio Background Selector) | **v2.7.0(再修正)** | 🟢 **実装完了 ✅** |
| **7** | 🎬 互換性 | **実機検証済み対応動画元・プラットフォームの仕様明記** (Platform Compatibility) | v2.5.0 | 🟢 **実装完了 ✅** |
| **8** | 🧩 プラグイン | **Webリモコン＆VRCBeaconプラグインUIの完全統合＆UI正本配置整理** (Integrated UI) | v2.6.0 | 🟢 **実装完了 ✅** |
| **9** | 📻 モード分離 | **再生モード3分岐 ＆ 写真・動画キュー完全分離 ＆ スライドショー安定化** (Playback Modes) | **v2.7.0** | 🟢 **実装完了 ✅** |
| **10** | 📱 QRオーバーレイ | **待機画面・通常動画・ラジオ全画面でのQRコード表示モード統括・修正** (QR Overlay) | **v2.7.0** | 🟢 **実装完了 ✅** |
| **11** | ⏰ 時計表示 | **配信実時刻（LIVE時計）オーバーレイ機能の修正・堅牢化** (Live Clock Overlay) | **v2.7.0** | 🟢 **実装完了 ✅** |
| **12** | 🏷️ 名称変更 | **アプリの名称変更およびREADME・ウィンドウタイトル・UI表記の刷新** (App Renaming) | **v2.8.0** | 🟢 **実装完了 ✅** |
| **13** | 🎬 動画対応 | **写真に加えてMP4等のローカル動画ファイルアップロード・再生対応** (Local Video Upload) | **v2.8.0** | 🟢 **実装完了 ✅** |
| **14** | 📡 配信経路 | **配信先（HLS/TopazChat/汎用RTMP）の選択制対応** (Selectable Streaming Destination) | **v2.9.0** | 🟢 **実装完了 ✅** |
| **15** | 🔄 外部依存 | **外部ソース（yt-dlp等）の自動更新・メンテナンス機能** (External Tools Auto-Update) | 未定 | 🔵 **検討中 📋** |
| **16** | 🎨 GUI刷新 | **ホストソフトGUIのモダン化・リデザイン** (Host GUI Modernization) | v2.9.4 | 🟢 **実装完了 ✅** |
| **17** | 🎵 ラジオ | **ラジオモード時の曲間フェード** (Smooth Fade) | v2.9.9 | 🟡 **実装完了・実機未確認** |
| **18** | ⚡ 性能 | **FFmpeg ハードウェアエンコード（NVENC / QSV / AMF）対応** (HW Encoding) | develop | 🟢 **実装完了 ✅** |
| **19** | 🛠️ CLI | **CLI 引数・環境設定オーバーライド機構の総点検・堅牢化** (CLI Overrides Overhaul) | **v2.9.0** | 🟢 **実装完了 ✅** |
| **20** | 🌐 UI/権限 | **通常ブラウザ利用時のサーバー操作ボタン（再起動・起動）非表示化** (Button Visibility) | v2.6.0 | 🟢 **実装完了 ✅** |
| **21** | 🛡️ Web制御 | **Webリモコン機能の無効化・ホスト専用スタンドアロンモード** (Disable Web Remote / Host-Only Mode) | develop | 🟢 **実装完了 ✅** |
| **22** | 🎙️ 音声配信 | **PC出力音声（ループバック）＆マイク入力音声の取り込み・配信** (PC Audio & Mic Capture) | develop | 🟡 **実装完了・VRC実機未確認** |
| **23** | 🖥️ 画面配信 | **PCデスクトップ画面・ウィンドウのリアルタイムキャプチャ配信** (Desktop Screen Share) | feature/task23-screen-share | 🟡 **実装完了・VRC実機未確認** |
| **24** | 🎤 参加型 | **Webリモコンからの参加型カラオケ・楽器セッション機能** (Remote Karaoke & Session) | 未定 | 🔵 **検討中 📋** |
| **25** | 🎚️ 音声配信 | **アプリ単位の音声取り込み（WASAPIプロセスループバック）** (Per-Application Audio Capture) | feature/task25-app-audio-capture | 🔵 **設計完了・実装未着手 📐** |

---

## 1. 📻 YouTubeサムネイル＆ラジオ番組風カード画面の自動生成 (Radio Card Visualizer) 【実装完了 ✅】

### 概要
BGM/ラジオモード再生時、YouTubeから取得したサムネイル画像（アルバムアート風）と動画タイトル・アーティスト情報を1枚の洗練された **「1920x1080 ラジオ番組風カード画面」** として自動合成・生成する機能。

### 実装設計
1. **背景レイヤー**:
   - YouTubeサムネイルを拡大＋ガウスぼかし（Gaussian Blur）し、ダーク調のグラデーション・オーバーレイを重ねたリッチで落ち着いた背景
2. **左側（アルバムアート領域）**:
   - `yt-dlp` で取得した高画質サムネイル（`maxresdefault` / `hqdefault` / `webp` / `jpg`）
   - 角丸（Corner Radius）＋繊細なドロップシャドウ/ボーダー
3. **中央〜右側（楽曲情報領域）**:
   - 楽曲タイトル（Bold、日本語フォント自動解決: `meiryo.ttc` / `msgothic.ttc` / `arial.ttf`）
   - アーティスト名 / チャンネル名の明瞭なタイポグラフィ
   - ※波形イコライザー・QRコード・シークバーは除外し、超低負荷＆余計な外部アクセス・ズレのないシンプルなアルバムカードデザインを採用
4. **極小帯域配信の維持**:
   - 静止画（PIL合成）として生成し、FFmpegで超低帯域（`libx264` 200kbps, 2fps）＋AAC音声（128kbps）でエンコード。
   - 合計ビットレート約300kbpsのまま、高画質・高音質・バッファ詰まりゼロの配信を実現。
5. **高速キャッシュ**:
   - `hls_output/images/radio_cache/` に動画IDごとに保存し、次回以降即時ロード。

---

## 2. 🔒 Webリモコンのパスワード/PIN認証保護機能 (Web Remote Password Protection) 【実装完了 ✅】

### 概要
Webリモコン（スマホブラウザ等）に簡単なパスワード（数字4〜6桁のPINコードや文字列）を設定し、パスワードを知っているユーザーのみがリモコン画面の閲覧・操作を行えるようにする機能。
不特定多数からのアクセスや定期ポーリング（`/api/status`）によるホストPCのCPU/ネットワーク負荷を防ぐ。

### 仕様・動作フロー
1. **ホスト側の設定**:
   - `config.json` に `"web_password": ""`（デフォルト: 空文字列＝認証なし）。
   - GUI（`gui_streamer.py`）の設定画面に「Webリモコン パスワード」入力欄を追加。
   - 空欄の場合は従来通り誰でもアクセス可能（オプトイン設計）。
   - ホスト本人（localhost / ループバック）からのアクセスは常に認証不要（パスワード入力なしで全操作可能）。

2. **ゲストのアクセスフロー（スマホ / PCブラウザ）**:
   - `web_password` が設定されている場合：
     1. Webリモコン画面（`/`）を開くと、操作UIを隠した状態で「パスワード入力モーダル（PIN入力）」を表示。
     2. **モーダル表示中は `/api/status` の定期ポーリングを完全停止**（ホスト負荷ゼロを維持）。
     3. 正しいパスワードを入力すると、ブラウザのセッション（`sessionStorage`）に記憶して通常のリモコン画面を開く。
        - **タブを閉じる、または次回ソフト起動（新URL発行）で自動消滅**（長期間残り続けない安全設計）。
        - 同一タブ内でのリロード時は再入力不要。
     4. 誤ったパスワードの場合は「パスワードが違います」と表示してブロック。
     5. UI内に「ログアウト（認証情報クリア）」ボタンを配置。

3. **サーバー側（API）の負荷・セキュリティ対策**:
   - ゲストからの全APIリクエスト（`/api/status`, `/api/queue`, `/api/control`, `/api/upload` 等）について、リクエストヘッダー（`X-Web-Password`）を検証。
   - 未認証またはパスワード不一致の場合、キュー処理やシリアライズを行わず **即座に `401 Unauthorized` を返却**。
   - ※**VRChat内の動画プレイヤー（`/stream.m3u8`, `*.ts`）は認証対象外**とし、プレイヤー側への影響なくストリーム再生を維持。

### 変更対象予定ファイル
- `streamer_core.py`（デフォルト設定 `web_password: ""` の追加、ステータスデータに `has_web_password: bool` を含める）
- `config.dist.json`（配布用設定テンプレートへの追加）
- `api_server.py`（`X-Web-Password` ヘッダー検証、401返却、認証除外パスのハンドリング）
- `ui/index.html`（パスワード入力モーダルUI、ローカルストレージ保存、APIリクエストヘッダー付与、ポーリング制御）
- `gui_streamer.py`（ホストGUI設定画面にパスワード入力欄を追加）

---

## 9. 📻 再生モード3分岐 ＆ 写真・動画キュー完全分離 ＆ スライドショー安定化 (Playback Modes & Photo Pool Separation) 【実装完了 ✅】

### 概要
動画・ラジオ・スライドショーの3大再生モードへの明確な分岐、写真プール（アルバム）と動画キューの完全分離、および写真0枚時のフォールバック案内表記（パターンA）を導入し、スライドショー再生の動作安定化とキュー混在による不具合を根本解決。

### 実装内容
1. **3つの再生モード（`playback_mode`）の明確化**:
   - 🎬 **動画モード (`video`)**: 動画キューを通常再生。**写真は一切混入しない**。
   - 📻 **ラジオモード (`radio`)**: 動画キューの音声のみ抽出＋背景（カード / 写真プール全件スライドショー / 待機画面）を極小帯域（~300kbps）で配信。
   - 🖼️ **スライドショーモード (`slideshow`)**: 写真プール内の写真を指定秒数ごとに自動巡回配信（無音）。
2. **動画キュー (`play_queue`) と 写真プール (`photo_pool`) の完全分離**:
   - アップロードされた写真は写真プールに保持され、動画を再生しても消滅しない。動画キューへの写真混入を完全防止。
3. **写真プール（UI / API）での並び替え・削除機能**:
   - WebリモコンおよびGUI上で写真の「個別削除」「並び替え（前へ/次へ）」「全削除（クリア）」が可能。
4. **写真0枚時のフォールバック案内（パターンA）**:
   - 写真が0枚のときは待機画面に下部案内バー（`📷 スライドショー写真が未登録です（Webリモコンから写真をアップロードできます）`）を Pillow で合成表示。写真が投稿され次第即座にスライドショーへ復帰。
5. **`photo_pool` の完全クリーンアップ（セッション限定・残骸ゼロ）**:
   - ソフト終了時および次回起動時に、`hls_output/images/` 配下の全キャッシュ画像を完全削除。PC内に一時写真が残留しない安全設計。
6. **Web UI / GUI / 単体テストの完備**:
   - Webリモコン（3ボタントグル＋写真プール管理カード）、デスクトップGUI（3モードセグメントボタン）、包括的単体テスト（`test_playback_modes.py` 全6件通過）。

### 変更ファイル
- `streamer_core.py`（`playback_mode` 実装、キューと写真プールの完全分離、写真0枚フォールバック案内バー合成、再生ループ3分岐制御）
- `api_server.py`（`/api/status`, `/api/control`, `/api/upload` の 3モード・写真プールCRUD対応）
- `ui/index.html` / `plugin/ui/index.html`（3ボタントグルUI、写真プール管理カード・操作ロジック追加）
- `gui_streamer.py`（GUIヘッダーに3モードセグメントボタン追加、設定同期）
- `config.dist.json`（`playback_mode: "video"` 追加）
- `test_playback_modes.py`（3モード動作・写真プール分離・案内バー合成の単体テスト）
- `test_radio_unit.py`（写真プール対応への修正）

---

## 10. 📱 待機画面・通常動画・ラジオ全画面でのQRコード表示モード統括・修正 (QR Code Overlay & Standby Modes) 【実装完了 ✅】

### 概要
待機画面（Standby）、通常動画再生時、ラジオモード時のすべてにおいて、Webリクエスト用QRコードおよび接続URLのオーバーレイ表示が意図通りに動作しない、またはFFmpegフィルタエラーで配信が落ちる不具合を解消し、全配信モードでの設定仕様を完全統一。

### 実装内容
1. **待機画面固定画像モード (`standby_mode: "image"`) での QR 合成対応**:
   - `standby_mode == "image"` 時に `overlay_qr_enabled: true` の場合、Pillow (`alpha_composite`) で待機画像（カスタム画像 / デフォルト画像 / フォールバック画面）上にQRオーバーレイを合成して保存するよう修正。
2. **堅牢な FFmpeg フィルタグラフビルダーの導入 (`_build_video_filter_complex`)**:
   - 音声ストリームの有無による入力インデックス（`qr_idx`）や `scale2ref` / `overlay` / `drawtext`（時計）の組み合わせを安全に組み立てる共通ビルダーメソッドを整備。
3. **ラジオモードの QR オーバーレイ対応 (`play_radio`)**:
   - `card` / `standby` 背景使用時、`overlay_qr_enabled` が有効な場合は動画再生時と同様に FFmpeg `-filter_complex` でQRコードを合成して配信。
   - スライドショー（`slideshow`）は `get_image_for_playback()` でPillow合成済みのため、二重合成を自動防止するガードを装備。
4. **単体テスト整備**:
   - `test_standby.py`（待機画面QR合成検証2件）および `test_qr_overlay.py`（ビルダー・QR画像生成検証9件）を追加し、全テストパスを確認。

---

## 11. ⏰ 配信実時刻（LIVE時計）オーバーレイ機能の修正・堅牢化 (Live Clock Overlay & Sync Marker) 【実装完了 ✅】

### 概要
配信映像（通常動画・ラジオ画面・静止画/スライドショー・待機画面）において、配信実時刻（JST）をオーバーレイ表示し、VRChat内プレイヤーとの遅延可視化とリシンク判断を可能にする機能において、設定フラグを厳格に尊重するパイプライン制御を実装し、無効時の不要なフィルタ負荷やフォント起因のFFmpegエラーを解消。

### 実装内容
1. **設定フラグ（`overlay_clock_enabled` / `overlay_clock_video`）の厳格な尊重**:
   - `play_radio`、`play_image`、`play_standby_loop` において、設定が無効な場合は FFmpeg に一切の `-vf`（`drawtext`）を付与せずバイパス。
   - 設定が有効な場合のみ、リアルタイム時刻を描画する `drawtext` フィルタを適用。
2. **位置設定共通ヘルパーの導入 (`get_clock_filter_for_config`)**:
   - `overlay_clock_position`（`top-right`, `top-left`, `bottom-right`, `bottom-left`）に応じた座標計算と `drawtext` 文字列生成を共通関数化し、全配信パイプラインで一元管理。
3. **フォントパス解決とエスケープの堅牢化 (`get_drawtext_font_path`)**:
   - Windows・Linux・macOSのフォント探索候補を拡充し、パス区切り文字およびコロンのエスケープ（`C\:/...`）を安全に処理。
4. **包括的な単体テスト整備**:
   - `test_clock_features.py` に時計フィルタヘルパー、位置座標計算、`-filter_complex` ビルダー組み合わせ、および各配信パイプラインでのフラグチェック検証（計8項目）を追加し、全テストパスを確認。

### 変更ファイル
- `streamer_core.py`（`get_clock_filter_for_config`, `get_drawtext_font_path`, `play_radio`, `play_image`, `play_standby_loop`, `play_video`）
- `test_clock_features.py`（位置座標・ビルダー組み合わせ・パイプラインフラグ検証テスト拡充）
- `FUTURE_PLANS.md`（タスク11完了記録）

### 🐛 実機NG → 原因特定・修正（2026-08-27）

**症状**: 全モードで時計がまったく表示されない（配信は正常、単体テスト8件は全通過）。

**根本原因**: `drawtext` の text に書いていた時刻書式のコロンのエスケープが、
フィルタグラフ解析の段階で外れてしまうこと。

- 生成していた文字列: `text='● LIVE %{localtime\:%H\:%M\:%S} JST'`
- FFmpeg がフィルタ記述をアンエスケープするため、drawtext の展開器には
  `%{localtime:%H:%M:%S}` として渡り、コロンが引数区切りと解釈されて4引数になる。
- 結果 `[Parsed_drawtext_0] %{localtime} requires at most 1 arguments` が出て
  **text全体が空になり、何も描画されない**。
- **FFmpegの終了コードは 0 のまま**（＝配信は落ちないので気づきにくい）。

**修正**: 時刻書式に生のコロンを書かず、strftime の `%T`（＝`%H:%M:%S`）を使用。
`text='● LIVE %{localtime\:%T} JST'` に変更（[streamer_core.py:169](streamer_core.py)）。

**検証**: 実際に FFmpeg を起動して1フレーム描画し、4方向の表示位置すべてで
`● LIVE HH:MM:SS JST` が描画されること、QRオーバーレイ併用（`-filter_complex`）でも
描画されることを確認済み。

**テストの盲点と対策**: 既存テストはコマンド文字列に `drawtext=` が含まれるかを見るだけで、
FFmpegを一度も起動していなかったため素通りしていた。
`test_clock_features.py` に **実際にFFmpegを起動して描画結果を検証する回帰テスト**
（`test_drawtext_filter_actually_renders`）を追加。旧文字列ではこのテストが落ちることを確認済み。

**残作業**: VRChat実機での最終確認（表示位置・視認性・遅延把握の実用性）。

---

## 12. 🏷️ アプリの名称変更およびREADME・ウィンドウタイトル・UI表記の刷新 (App Renaming & Rebranding) 【実装完了 ✅】

### 概要
アプリケーションの正式名称変更に伴い、ドキュメント（`README.md`、`README.txt`）、デスクトップGUIウィンドウタイトル（`gui_streamer.py`）、WebリモコンUIタイトル（`ui/index.html`）、ビルド設定、バッチファイル、プラグイン等の各所に存在する旧アプリ名の表記を一括で更新・統一するタスク。

### 検討・改訂対象箇所
1. **ドキュメント類の改訂**:
   - `README.md` / `README.txt`: アプリ名、概要説明、起動手順、各種設定ファイルの説明を新名称に更新。
   - `HANDOVER_*.md` / ドキュメント内の名称リンクやタイトルの整理。
2. **GUI / Web UI の表示刷新**:
   - `gui_streamer.py`: ウィンドウタイトル（`self.title("...")`）、ヘッダーラベル（`title_label`）、各種ダイアログのタイトル表記。
   - `ui/index.html` / `plugin/ui/index.html`: ブラウザタブタイトル（`<title>`）、Webリモコンヘッダーロゴ・名称。
   - `api_server.py`: UIアセット未検出フォールバック画面のタイトル・メッセージ。
3. **ビルドおよび起動スクリプト**:
   - `build_exe.py` / `VRC_Media_Streamer.spec`: 出力EXE名、ZIPアーカイブ名、バッチファイル内の文言および起動コマンド。
   - `Start_Normal.bat` / `Start_LocalTest.bat`: 表示ログや起動メッセージ。
4. **プラグイン・連携部分**:
   - `vrcbeacon-plugin` 側のマニフェスト、UI、表示名の整合性確保。

### 変更対象予定ファイル
- `README.md` / `README.txt`
- `gui_streamer.py`
- `ui/index.html` / `plugin/ui/index.html`
- `api_server.py`
- `build_exe.py` / `VRC_Media_Streamer.spec`
- `Start_Normal.bat` / `Start_LocalTest.bat`
- `FUTURE_PLANS.md`

---

## 13. 🎬 写真に加えてMP4等のローカル動画ファイルアップロード・再生対応 (Local Video File Upload & Playback) 【実装完了 ✅】

### 概要
Webリモコン（スマホブラウザ / PC）およびホストPCのデスクトップGUIから、画像（写真・スクショ）だけでなく **MP4 / MOV / WebM などのローカル動画ファイル** を直接アップロード（またはドラッグ＆ドロップ）し、動画キュー（`play_queue`）に追加してVRChat向けにHLS配信できる機能。

### 背景と利点
- **現状**: 動画再生はYouTube等のオンラインURL（`yt-dlp` 解析）が前提であり、ローカルメディアは写真プール（静止画）のみの対応となっている。
- **利点**:
  - スマホで撮影した動画やPC内の録画ファイルをYouTubeにアップロードすることなく、即座にVRChatワールド内の大画面・プレイヤーで皆と共有・鑑賞可能。
  - ローカルファイルのため `yt-dlp` による抽出処理が不要で、キュー追加から再生開始までのラグが極小。

### 仕様・実装設計
1. **アップロードAPIの動画対応拡張 (`/api/upload`)**:
   - MIMEタイプ（`video/mp4`, `video/quicktime`, `video/webm`, `video/x-matroska` 等）および拡張子による動画判別。
   - **アップロード上限・チャンク対応**:
     - 静止画上限（20MB）と分離し、ローカル動画用の上限（例: 100MB〜500MB、設定可能）を設定。
   - **保存場所とサニタイズ**:
     - `hls_output/videos/`（または一時メディアディレクトリ）にUUIDベースの安全なファイル名で保存。
     - セッション終了時または再生完了時に一時動画を自動クリーンアップする安全設計。
2. **キュー統合と再生パイプライン (`StreamerCore`)**:
   - キューアイテムの種別として `type: "local_video"` を追加（`title`, `url` に代わり `file_path`, `duration` を保持）。
   - `play_video` / `play_radio` 実行時、URL抽出を行わずローカルファイルパスを直接 FFmpeg の入力（`-i <path>`）として渡すことで即時トランスコード配信。
3. **UI / 操作性の拡張**:
   - **Webリモコン (`ui/index.html`)**:
     - メディア投稿エリアに「動画を追加（MP4/MOV）」オプションを追加（または写真/動画の自動判別）。
     - 動画アップロード進捗バー（ProgressBar）を表示。
   - **ホストGUI (`gui_streamer.py`)**:
     - 「動画ファイルを追加」ボタンおよびウィンドウへの動画ドラッグ＆ドロップ対応。
4. **セキュリティ・負荷対策**:
   - ゲストからの動画アップロードに対する容量制限・レートリミットおよびパスワード認証の徹底。

### 変更対象予定ファイル
- `streamer_core.py`（ローカル動画アイテムのキュー処理、FFmpeg入力パイプライン、動画削除クリーンアップ）
- `api_server.py`（動画アップロード受付、MIME/サイズ判定、レートリミット分離）
- `ui/index.html` / `plugin/ui/index.html`（動画アップロードUI、プログレスバー、キュー表示）
- `gui_streamer.py`（ローカル動画選択ダイアログ、D&D対応）
- `config.dist.json`（動画アップロードサイズ上限等の設定項目）
- `tests/test_local_video.py`（ローカル動画アップロード・キュー・再生単体テスト）

---

## 14. 📡 配信先（HLS / TopazChat / 汎用RTMP）の選択制対応 (Selectable Streaming Destination) 【実装完了 ✅】

### 概要
現在ハードコードされている配信経路「ローカルHLS生成 → Flask配信 → Cloudflare Quick Tunnel（`*.trycloudflare.com`）」を抽象化し、**配信先（destination）を設定で切り替えられる**ようにする。特に VRChat 向けに設計された **TopazChat（RTMP入力 → `rtsp://` 出力）** を第一候補として追加する。

### 背景と目的
- **現状の課題（ToS）**: 動画実体そのものを Cloudflare Quick Tunnel 経由で流しており、Cloudflare の非HTMLコンテンツ制限（ToS 2.8）に対してグレーな利用形態。Quick Tunnel も本来は開発用途で、恒常運用を前提としていない。
- **現状の課題（遅延）**: `hls_segment_time: 3` × プレイヤー側バッファ約3セグメントで、VRChat 側の実効遅延は **約9〜12秒**。ワールドで複数人が同時視聴する用途では反応のズレが大きい。
- **狙い**: 映像を TopazChat 等へ逃がすことで、
  1. 遅延を **1秒未満〜2秒** に短縮、
  2. Cloudflare トンネルの役割を **Webリモコンの HTML / JSON（制御系）のみ** に縮小し、ToS上のグレーさを実質解消する。

### 方針（重要な設計判断）
本タスクは「3つの配信先を同列に並べる」ものではない。優先度と扱いを明確に分ける。

| 配信先 | 位置付け | VRChat側遅延 | 備考 |
| :--- | :--- | :---: | :--- |
| **`hls`（現行）** | **既定値・フォールバック** | 約9〜12秒 | Cloudflare Quick Tunnel 経由（トンネル無効時のみローカル完結）。他経路の失敗時の退避先として必ず残す |
| **`topaz`（TopazChat）** | **本命・最優先実装** | 1秒未満〜2秒 | VRChat向け設計。AVProで `rtspt://topaz.chat/live/<KEY>` を直接再生。映像2Mbps / 音声320kbps の上限あり |
| **`generic_rtmp`** | 上級者向けオプトイン | 任意 | 自前 nginx-rtmp / MediaMTX 等。URL＋キーを手入力 |

- **YouTube Live は推奨destinationとして提供しない。** 理由:
  1. 本アプリは `yt-dlp` で取得した他者の YouTube 動画を再生する設計であり、それを自チャンネルへ再送出すると Content ID・著作権警告の直撃対象となる。リスクの質が「トンネルが止まる」から **「ユーザー本人の Google アカウント / チャンネルが停止」** に悪化する。
  2. 遅延が15〜30秒とHLS直より更に悪化し、視聴側でも `yt-dlp` 解決を要するため依存が増える。
  3. **QRオーバーレイ（タスク10）との相性が致命的** — Webリモコンのトンネル URL を画面に焼いているため、公開ライブへ流すとリモコンURLが全世界へ露出し、PIN認証（タスク2）だけが最後の防壁になる。
  - どうしても使う場合は `generic_rtmp` の枠内で、UI上に明示的な自己責任警告を出したうえで利用者が自分でURLを入力する形に留める。

### TopazChat の公式仕様・規約上の制約（2026-08-28 公式README確認）

出典: [TopazChat/TopazChat (GitHub)](https://github.com/TopazChat/TopazChat)

| 項目 | 内容 | ソフト側の対応 |
| :--- | :--- | :--- |
| RTMP投稿先 | `rtmp://topaz.chat/live` | **ハードコードせず `config.dist.json` に置く**（個人運営のためホスト変更・終了があり得る。タスク15と同じ思想でリビルド不要に） |
| RTSP再生URL | `rtspt://topaz.chat/live/<StreamKey>`（TCP強制版を既定とする） | ワールド貼付用URLとして生成・表示 |
| 映像上限 | **2Mbps**（推奨1500kbps） | **ソフト側のハードリミットとして実装。設定で上限超過を許可しない** |
| 音声上限 | **AAC 320kbps ステレオ**（推奨192kbps） | 同上。既定は推奨値 |
| 超過時の挙動 | 「大きく上回ると配信が強制的に切断されます」 | 上限を超える設定値は保存時点で拒否 or クランプ |
| 利用条件 | **個人利用は無償。法人が運営主体のイベント・番組制作等の法人利用は有償（要問い合わせ）** | **UIに「法人利用の場合は別途TopazChatへ問い合わせが必要」の注記を表示**。本ソフトは配布物であり、黙って法人利用を可能にすると規約違反を助長するため |
| 運営形態 | 個人運営・無償提供（サーバ費は開発者負担、PixivFANBOXでカンパ募集） | **UIにFANBOX / 公式サイトへのリンクを設置**。既定destinationは `hls` のままとし、TopazChatは明示的に選ばせる（配布ソフトが全ユーザーの帯域を無断で他者の善意サーバへ向けない） |
| サードパーティツール | 公式READMEに可否の記載なし（OBSの手順のみ記載。禁止規定も明示的許可もなし） | 禁止されていないため実装可。ただし **公式を騙らない**: ロゴ・ブランド素材は使用せずテキスト名のみ、「本ソフトはTopazChatの公式ツールではありません」を明記 |
| 再接続 | 記載なし | **指数バックオフ**で実装。無限リトライで相手サーバを叩かない |

### 仕様・実装設計
1. **シンク（出口）の抽象化**:
   - 現状、配信先を定義しているのは `streamer_core.py` の `ensure_hls_receiver()` **ただ1箇所**。永続FFmpegが `pipe:0` から MPEG-TS を読み、各再生アイテムのFFmpegが `current_stdin` へ流し込む構造のため、**シンクだけを差し替えれば destination 化できる**（継ぎ目が1関数に閉じている）。
   - `ensure_hls_receiver()` → `ensure_stream_sink()` へ改称し、`config["output_mode"]`（`"hls"` / `"topaz"` / `"generic_rtmp"`）で出力引数を分岐させる。
2. **コーデック方針（TopazChat経路では再エンコード必須／確定）**:
   - 現行シンクは `-c:v copy -c:a copy`。HLS はセグメント境界の不連続に寛容だが、**RTMP は再生アイテム切替時のタイムスタンプ跳躍・解像度/パラメータ変化でサーバ側から切断されやすい**。
   - さらに TopazChat には **映像2Mbps / 音声320kbps の明確な上限があり、超過すると強制切断される**（上記「公式仕様・規約上の制約」参照）。元動画のビットレートが上限を超えていれば接続した瞬間に切られるため、**`-c copy` の素通しは成立しない**。
   - → **RTMP系destinationではシンク側での再エンコードを必須とする**（`-c:v libx264 -b:v <上限内> -maxrate -bufsize -g <固定GOP> -keyint_min <同値> -c:a aac -b:a <上限内>`）。これは推測ではなく公式仕様から導かれる確定事項であり、**実測が必要なのはCPUコストの方のみ**（タスク18のハードウェアエンコード対応と併せて検討）。
3. **destination別プロファイルの分離**:
   - `hls_segment_time` / `hls_list_size` は RTMP では意味を持たない。設定を destination ごとのプロファイルに分離し、RTMP側は ビットレート / GOP長 / 再接続リトライ間隔 を持つ。
4. **フォールバック設計（fail-safe）**:
   - TopazChat は有志運営の無料サービスであり、可用性の保証がない。**接続失敗・切断検知時に自動で `hls` へフォールバック**し、配信自体は途切れさせない。
   - RTMP 切断・再接続ループは、ローカルHLSには存在しなかった **新規の障害モード** として明示的にハンドリングする。
5. **ストリームキーの機密扱い・自動生成**:
   - `config.json` は `.gitignore` 済み（`.gitignore:47`）のためリポジトリ流出の心配はないが、**`/api/status` レスポンス・`log_print` のログ出力・GUI表示・QRコードの全経路でマスク必須**。
   - **TopazChat のストリームキーは任意文字列で、公式に決め方の記載がない。** 同じキーで誰でも RTMP 投稿できるため、`test` のような短いキーだと **第三者に配信を乗っ取られる**。初回設定時に **長いランダム文字列（32文字以上）をソフト側で自動生成**し、手入力は上書き可能なオプションとする。
6. **URL概念の分離**:
   - `get_status()` が返す `tunnel_url` / `public_url`（`streamer_core.py:543` 付近）は現在「動画URL」と「リモコンURL」を兼ねている。destination 導入後は両者が別物になるため、**「ワールドの動画プレイヤーに貼るURL」と「Webリモコンを開くURL」を別フィールドとして明確に分離**する。QRオーバーレイが焼くのは後者のみ。
   - Cloudflare トンネル自体は **Webリモコンのために引き続き必要**であり、全廃はしない。

### 実装フェーズ
- **Phase 1**: `output_mode: "hls" | "topaz"` の2択のみ実装。TopazChatキー入力UI＋失敗時のHLS自動フォールバックまで。これで遅延とToSの両課題が解決する。
- **Phase 2**: `generic_rtmp`（RTMP URL＋ストリームキー手入力）を上級者向けに追加。自己責任警告表示を伴う。

### 事前確認が必要な事項（設計前に実測すること）
- **CPUコストの実測**: シンク側再エンコード（`libx264` 2Mbps上限）を常時走らせた場合のホストPC負荷。ラジオモードの超低負荷設計（200kbps / 2fps 静止画）との共存可否を含めて計測する。→ 負荷が問題になる場合はタスク18（NVENC / QSV / AMF）の前倒しを検討。
- **アイテム切替時のRTMP接続維持**: 再生アイテム切替（解像度・フレームレート変化）をまたいで RTMP セッションが維持できるか。維持できない場合は、シンク側で解像度・fps を固定（`scale` + `fps` フィルタ）してパラメータ変化そのものを消す。
- **VRChat側の再生可否**: `rtspt://` を再生できるのは AVPro プレイヤーのみ（Unity Video Player 不可）である点の、対象ワールドでの成立確認。

### 変更対象予定ファイル
- `streamer_core.py`（`ensure_hls_receiver()` のシンク抽象化、destination分岐、再接続・フォールバック、`get_status()` のURL分離）
- `api_server.py`（`/api/status` でのストリームキーのマスク、destination切替API）
- `ui/index.html` / `plugin/ui/index.html`（配信先選択UI、キー入力欄のマスク表示、現在の配信先表示）
- `gui_streamer.py`（配信先選択・キー入力の設定画面、接続状態表示）
- `config.dist.json`（`output_mode`、TopazChatのRTMP/RTSPエンドポイント（ハードコード禁止）、destination別プロファイル、ビットレート上限、キー項目の追加）
- `tests/test_destination.py`（destination切替・フォールバック・キーマスクの単体テスト）

### 依存・前提
- タスク11（LIVE時計オーバーレイ）の実機確認は **2026-08-28 完了**。本タスクの着手ブロッカーは解消済み。
- タスク18（ハードウェアエンコード対応）と設計上の関連あり（RTMP再エンコードが必要となった場合、NVENC等の適用でCPUコストを相殺できる可能性）。

### 実装記録（2026-08-28 / ブランチ `feature/task14-stream-destination`）

Phase 1（`hls` / `topaz`）と Phase 2（`generic_rtmp`）を同時に実装した。
シンクの分岐は1箇所に閉じており、`generic_rtmp` は同じRTMP経路の宛先違いに過ぎないため、
分割するより一度に入れた方が差分が小さく済むと判断した。

- `ensure_hls_receiver()` → **`ensure_stream_sink()`** へ改称し、`build_sink_command(mode)` で
  出口だけを差し替える構造にした。旧名は別名として残してある（プラグイン・既存テスト互換）。
- RTMP系は設計どおり**再エンコード必須**（`scale`+`pad`+`fps` 固定 → `libx264` / `aac`、
  GOP = `fps × rtmp_gop_seconds`）。TopazChat の 2Mbps / 320kbps は保存時クランプで担保。
- ストリームキーは `secrets.token_urlsafe(30)`（40文字）で自動生成。`/api/status`・
  `/api/config`・POSTボディのログの全経路でマスクし、生キーは localhost 限定の
  `/api/destination`（`reveal_key`）でのみ取得できる。
- `get_status_data()` に `video_url`（ワールドに貼る）と `remote_url`（Webリモコン）を分離して追加。
  QRが焼くのは従来どおり後者のみで、この点は変更していない。

#### ★実測でひっくり返った設計前提（2026-08-28）

当初は「RTMPシンクは接続失敗時に即座に終了するので、起動直後の生存確認で失敗を検知できる」
という前提で組んだが、**誰も listen していないポートを宛先にしても FFmpeg は2秒間平然と生きていた**。
原因は入力が `pipe:0` であること — 入力データが流れ始めてストリーム情報が確定するまで、
FFmpeg は出力側のRTMPハンドシェイクを開始しない。つまり起動直後の生存は接続成功を意味しない。

対策として **投稿先へのTCP到達性を起動前に確認**（`probe_rtmp_endpoint()`）する方式へ変更した。
併せて、失敗計数を呼び出しをまたいで持ち越すようにした（毎回リセットすると
「起動しては数秒で切断」を繰り返す相手に対して永遠に再接続し、退避条件へ到達できない）。
回帰防止として `test_destination.py` に「到達できない宛先にFFmpegを起動しないこと」を追加済み。

#### ★「音は出るが映像が乱れる」の原因（2026-08-30 実機報告 → 実測で3件特定）

TopazChat配信で映像だけが破綻するとの報告を受けて調査。手元でRTMP経路を再現し、
シンクFFmpegの入出力ログと送出ペースの実測から、独立した3件の欠陥を特定した。

1. **累積PTSオフセットが効いていなかった**
   `-output_ts_offset` は**出力**オプションで、`-i` より前に置くと黙って無視される
   （実測: 10秒指定しても出力PTSは1.47秒＝素通し。出力側なら11.4秒で反映）。
   4箇所すべてが入力側にあり、アイテム切替のたびPTSが0付近へ巻き戻って
   「DTS out of order」「Packet corrupt」を誘発していた。HLSは寛容で表面化しない。

2. **`-tune zerolatency` が画質を1dB削っていた**
   同一1500kbpsでの実測: 現行 SSIM 0.9751 / PSNR 36.61dB → tune除去で 0.9805 / 37.55dB。
   ビットレートを2000kへ増やすのと同等の改善が、帯域を増やさず得られる。
   利得の出所はBフレーム（`-bf 0` にすると 36.56dB まで戻る）。

3. **HLS用の15秒先読みをRTMPにも流用していた**（本命）
   実測: 経過4秒の時点で約14秒ぶんを送出（実時間の3.5倍）。RTMPはライブ投稿であり、
   相手サーバーへ一気に押し込む形になっていた。低遅延目的でTopazChatを使いながら
   15秒先行させており、遅延の面でも本末転倒だった。RTMP系は実時間ペース(1秒)へ変更。

#### 実機確認の結果（2026-08-30）

- **実際のTopazChatへの投稿**: 成功。送出→`rtsp://`受信の往復で 30.1fps / デコードエラー0
- **VRChat（AVPro）での `rtspt://` 再生**: 利用者環境で正常に再生されることを確認
- **end-to-end 遅延**: 焼き込んだLIVE時計と実時刻の差で **約2〜3秒**（受信側バッファ込み）
- **アイテム切替をまたぐRTMPセッション維持**: 維持される（切替点に corrupt packet が1つ出るのみ）

#### 引き続き未計測

- **再エンコードのCPUコスト**（`libx264` 常時稼働。ラジオモードとの共存可否を含む）
  → 参考値として、720p/1500kbps のエンコード速度は単体で約9倍速（tune除去後）

---

## 15. 🔄 外部ソース（yt-dlp等）の自動更新・メンテナンス機能 (External Tools Auto-Update & Maintenance) 【検討中 📋】

### 概要
YouTube側のプレイヤー仕様変更や暗号化シグネチャ変更（n-sig/JSチャレンジ/PO-Token等）に伴い、動画・音楽の解析・抽出ができなくなる問題を防止するため、`yt-dlp` 等の外部依存バイナリをアプリ本体の再インストールなしで自動的またはワンクリックで最新版へ更新できる機能。

### 背景と課題
- **現状**: `yt_dlp` は PyInstaller によって `VRC_Media_Streamer.exe` の内部に静的バンドルされている。
- **課題**: YouTube側の仕様変更により再生不能になった場合、アプリ全体のリビルドおよび新バージョンの再配布・全ユーザーによる再ダウンロードが必要となり、ダウンタイムと保守負担が大きい。

### 仕様・実装設計
1. **外部バイナリ（`yt-dlp.exe`）方式への移行**:
   - `ffmpeg.exe` と同様に、アプリ同階層（または `bin/`）に独立した `yt-dlp.exe` を同梱・配置。
   - `streamer_core.py` の URL 展開・メタデータ取得処理を `yt-dlp.exe` の CLI（JSON出力 `--dump-single-json`）呼び出しに移行、または外部バイナリ優先参照とする。
   - アプリ本体の EXE サイズ削減にも寄与。

2. **更新トリガー**:
   - **① 起動時バックグラウンド自動チェック**:
     - `config.json` の `"auto_update_ytdlp": true`（既定値: 有効）に基づき、起動時に非同期スレッドで最新版の有無を確認・自動更新（起動処理をブロックしない）。
   - **② Webリモコン / GUI からの手動ワンクリック更新**:
     - Web リモコン UI の設定画面およびデスクトップ GUI に「yt-dlp を更新」ボタンを設置。
     - 更新進捗（ダウンロード中・完了・最新です 等）をトースト通知やステータスログに表示。
   - **③ 再生エラー時の自動リカバリ試行**:
     - YouTube ストリーム取得時に特定のエラー（ExtractorError, HTTP 403, Sign in required 等）を検知した場合、バックグラウンドで `yt-dlp.exe -U` を試行して再取得を試みる。

3. **他コンポーネントの更新ポリシー**:
   - `yt-dlp`: 頻繁な更新が必要なため自動/手動更新を実装。
   - `ffmpeg.exe`: 安定しており大容量（~80MB）なため、自動更新は行わず同梱版を固定利用。
   - `cloudflared.exe`: 安定しているため現状の管理を維持。
   - `VRC_Media_Streamer 本体`: GitHub Releases API を照会し、「最新バージョン vX.X.X が公開されています」の通知のみ表示。

### 変更対象予定ファイル
- `streamer_core.py`（外部 `yt-dlp.exe` 呼び出し、JSONパース、`-U` 実行/更新マネージャー、エラー時のリカバリ処理）
- `api_server.py`（`/api/system/update_ytdlp` エンドポイント、バージョン情報の返却）
- `build_exe.py`（`yt-dlp.exe` の配布パッケージ同梱処理、PyInstaller からのモジュール除外最適化）
- `config.dist.json`（`auto_update_ytdlp: true` 設定項目の追加）
- `gui_streamer.py`（設定タブに yt-dlp バージョン表示＆「今すぐ更新」ボタン追加）
- `ui/index.html`（Webリモコン設定モーダルに更新ボタン＆バージョン表示追加）
- `README.md` / `README.txt`（構成ファイルの説明に `yt-dlp.exe` を追加）

---

## 16. 🎨 ホストソフトGUIのモダン化・リデザイン (Host Software GUI Modernization) 【検討中 📋】

### 概要
現行の CustomTkinter ベースのデスクトップホスト画面（`gui_streamer.py`）を、Webリモコンと同等以上の洗練されたモダンデザイン・操作性（サイドバーナビゲーション、リアルタイム配信プレビュー、直感的なドラッグ＆ドロップキュー操作、Windows 11 親和性等）へと刷新する検討案。

### 現状と課題
- **現状**: `customtkinter` によるダークテーマUIを採用しているが、画面内にコントロール・URL・QRコード・ログが縦積みに密集しており、機能追加に伴って設定ウィンドウ等への動線が複雑化している。
- **課題**:
  - Webリモコン（スマホブラウザ向けUI）の洗練されたデザインとホストデスクトップUIにギャップがある。
  - 配信中の映像/カード画面のローカルプレビュー機能がない。
  - キューの直感的なドラッグ＆ドロップ並び替えや、複数ファイルの一括投入が難しい。

### 検討アプローチ
1. **アプローチA: WebView2 / pywebview による Web 技術統合（★ 推奨）**:
   - ホスト画面も Web 技術（HTML/CSS/JS または React/Tailwind 等）でレンダリングし、Windows 標準の WebView2 ランタイム経由で表示。
   - **メリット**: Web リモコンとデザイン資産・コンポーネントを共通化でき、超美麗なアニメーション・グラスモーフィズム・配信プレビュー（`<video>` タグでの HLS 再生）が容易に実現可能。
2. **アプローチB: CustomTkinter の全面レイアウト刷新（軽量維持）**:
   - Python 標準の依存関係を保ちつつ、レイアウトを「サイドバー（ナビゲーション）＋メインパネル（プレビュー＆キュー）＋右サイド（QR・ステータス）」の3ペイン構成に再構築。
   - **メリット**: 新たな依存ライブラリの追加が不要で、既存の PyInstaller ビルド構成を維持可能。
3. **アプローチC: PyQt6 / PySide6 / PyQt-Fluent-Widgets（ネイティブ Fluent Design）**:
   - Windows 11 の Mica / Acrylic マテリアルにネイティブ適合したデスクトップUI。

### 導入したい新機能・UX改善案
- **📺 リアルタイム配信プレビュー**: ホスト画面上で現在 VRChat 向けに送出されている映像（動画/ラジオカード/写真）を常時モニタリング。
- **🎛️ サイドバーナビゲーション**:
  - `Now Playing` (現在再生中・プレイヤー操作)
  - `Queue Manager` (ドラッグ＆ドロップ並び替え・検索・一括追加)
  - `Media Library` (写真・待機画像の管理)
  - `Settings` (タブ別・カテゴリ別に整理された設定)
  - `Logs & Diagnostics` (リアルタイムログ・接続状況)
- **📊 リアルタイムステータスパネル**:
  - 接続中のゲスト数、Cloudflare Tunnel 状態（Latency / URL）、CPU負荷、エンコードFPS等のビジュアルメーター。
- **📂 ドラッグ＆ドロップ対応**:
  - 動画ファイルや画像ファイルをホストウィンドウにドラッグ＆ドロップするだけでキューに即追加。

### 進捗
- **STEP① 第三者アセットのローカル同梱: 完了 ✅ (v2.9.4)**
  - アプローチAではホスト画面も `ui/index.html` を描画するため、CDN 直リンクのままだと
    「オフラインのホストPCでホスト画面が崩れる」＝ツールが起動不能に等しい状態になる。
    先に `ui/vendor/`（Tailwind 3.4.16 / Remix Icon 4.2.0 / hls.js 1.5.17）へ同梱し、
    `/vendor/` から配信するようにした。A/B どちらへ進んでも無駄にならない前提整備。
- **STEP② Web側へホスト専用設定の追加: 完了 ✅ (v2.9.4)**
  - 設定の網羅性が非対称。ホストGUIは8セクション（サーバー/配信先/再生/写真/ラジオ/
    待機画面/オーバーレイ/Webリモコン権限）、Web側は5項目程度しかない。
    ホスト画面をWeb化する前に、ここを埋めないと機能が退行する。
    ゲストに見せてはいけない項目（ポート・パスワード・待機画像パス等）は
    `is_local` でのゲーティングが必須。
- **STEP③ pywebview シェル + ネイティブブリッジ: 完了 ✅ (v2.9.4 / `host_window.py`)**
  - 容量無制限のローカル動画追加（ネイティブファイルダイアログ）、待機画像選択、
    アプリ終了、ストリームキーのマスク解除は Web 側だけでは実装できない。
    UI側は既に `window.electron.ipcRenderer` の有無で「起動/再起動」を出し分ける
    分岐を持つ（VRCBeacon 用）ので、そこにホスト用ブリッジを合流させる。
  - 配布上の判断が必要: WebView2 ランタイム＋pythonnet 依存が増え、
    「解凍してEXEを起動するだけ」という前提に条件が1つ乗る。

---

## 17. 🎵 ラジオモード時の曲間フェード (Smooth Fade in Radio Mode) 【実装完了・実機未確認 🟡】

### 概要
ラジオモード（音声＋アルバムアートカード/スライドショー）再生時、曲の終了と次の曲の開始がブツ切り・無音にならず、設定した秒数（例: 2〜4秒）で前の曲をフェードアウトしながら次の曲をフェードインして滑らかにシームレス遷移する機能。

### 仕様・実装設計
1. **先読み（prefetch）との連携**:
   - 既に実装されている `prefetch_item` により次曲のオーディオストリームURLは事前取得済み。
   - 再生中の曲の終了残り \(N\) 秒（クロスフェード秒数）のタイミングで次曲のエンコード・音声結合処理を起動。
2. **クロスフェード処理方式**:
   - **方式A (FFmpeg `acrossfade` / `afade` フィルター)**:
     - 曲末尾と曲頭のオーディオストリームを `acrossfade=d=3:c1=tri:c2=tri` 等でオーバーラップ合成し、HLS セグメントシーケンス番号（`sequence_offset`）の連続性を維持して送出。
   - **方式B (セグメントレベル・ボリュームカーブ合成)**:
     - 前曲末尾セグメントに `volume='1.0-t/d':eval=frame`、次曲頭セグメントに `volume='t/d':eval=frame` を適用してシームレスに結合。
3. **設定とUI**:
   - `config.json`: `"radio_crossfade_duration": 3`（0で無効、1〜5秒で調整可能）。
   - Webリモコン / ホスト設定画面に「クロスフェード秒数」スライダーを追加。

### 実装結果（feature/task17-radio-crossfade）

**方式Aの「重ねるクロスフェード」は採用していない。現構造では成立しないため。**
送出は 1曲 = 1本の送信FFmpegで、永続シンクの `pipe:0` へ MPEG-TS を流し込んでいる。
2本を同時に同じ pipe へ流せば多重化が壊れるので、前曲末尾と次曲頭を重ねるには
1本のFFmpegの中で作るしかなく、送出構造そのものの再設計を伴う。
上の方式Bも「前曲末尾セグメント」を独立に扱える前提で書かれており、同じ理由で不成立。

採用したのは**重ねない afade 方式**（曲頭フェードイン＋曲尾フェードアウト）。
重ねなくても目的はほぼ達する: 次曲のPTSは `accumulated_pts` から続くため、
プロセス起動やキュー処理の実時間はストリームの時間軸に現れず、曲間の無音は 0.1 秒程度。
耳に付いていたのは**波形の断ち切り**の方だった。

- 設定は `radio_crossfade_duration`（既定3秒 / 0で無効 / 最大5秒）。
- ホットリロード復帰（`seek > 0`）ではフェードインを掛けない。掛けると
  **設定を保存するたびに再生中の曲の音量が落ちて上がる**。
- 曲長の1/4を上限にフェード幅を縮め、0.5秒未満になるなら掛けない。
- 長さ不明の曲はフェードインのみ（`-shortest` で切れる瞬間は事前に読めない）。
- 残課題: **実機（VRChat）で曲の変わり目を実聴していない**。
  真の重なりが欲しくなった場合は、入曲側FFmpegに前曲末尾（`-ss duration-N`）を
  第2入力として与える案があるが、YouTube音声URLの末尾シーク・URL失効・
  skip / ホットリロード / ループとの相互作用・累積PTSの補正がすべて絡む。

### 変更対象ファイル
- `streamer_core.py`（`build_radio_audio_filter` / `normalize_radio_crossfade`、`play_radio` の `-af`、ステータス公開）
- `config.dist.json`（`radio_crossfade_duration: 3` 追加）
- `gui_streamer.py` / `ui/index.html` / `plugin/ui/index.html`（設定UI）
- `test_radio_crossfade.py`（新規・25件）

---

## 18. ⚡ FFmpeg ハードウェアエンコード（NVENC / QSV / AMF）対応 (Hardware-Accelerated Video Encoding) 【実装完了 ✅】

### 概要
ホストPCで通常動画モード（1080p60 / 720p60）を高画質配信する際、CPU負荷を大幅に低減し、省電力かつ高フレームレート・低遅延を維持するため、GPUによるハードウェアエンコード（NVIDIA NVENC, Intel QSV, AMD AMF）を自動検出・選択可能にする機能。

### 仕様・実装設計
1. **対応エンコーダー**:
   - `auto` (自動検出: NVENC → QSV → AMF → `libx264` ソフトウェアフォールバック)
   - `h264_nvenc` (NVIDIA GeForce / Quadro / RTX)
   - `h264_qsv` (Intel Core CPU 内蔵 Iris Xe / UHD Graphics / Arc)
   - `h264_amf` (AMD Radeon)
   - `libx264` (CPU ソフトウェアエンコード、高互換性)
2. **自動検出（Probe）機構**:
   - アプリ起動時に `ffmpeg -encoders` を実行し、ホスト環境で利用可能なエンコーダーを自動チェック・キャッシュ。
   - GPUエンコーダーが使用不可・エラーを返した場合は、自動的に安全な `libx264` へフォールバック。
3. **モード別の最適化**:
   - **通常動画モード**: 指定された GPU エンコーダー（NVENC/QSV/AMF）を使用して高速・低負荷エンコード。
   - **ラジオモード**: 静止画＋音声のため、従来通り極小帯域（2fps / 200kbps）の `libx264` で超軽量稼働。
4. **設定とUI**:
   - `config.json`: `"video_encoder": "auto"`
   - Webリモコン設定モーダル / ホスト設定画面に「動画エンコーダー（自動 / CPU / NVENC / QSV / AMF）」選択セレクトボックスを追加。

### 実装結果（develop）
- **実測 1.4倍軽い**: 待機配信のFFmpeg CPUが 36.39 → 25.54 秒/60秒（1コアの61%→43%）。
  単体では動画再エンコード経路 1.9倍・静止画ループ 1.5倍。詳細は CHANGELOG の同項目。
- **可否判定は実エンコード**: `ffmpeg -encoders` は GPU が無くても3種すべてを列挙するため
  一覧では判定できない（このPCでも一覧に4種出たが、実際に通ったのは NVENC と libx264 だけ）。
- **エンコーダーごとに完全に別の引数一覧を返す**。x264 の `-preset ultrafast` を
  NVENC に渡すと起動できない。`-level 3.1` も 1080p では NVENC に拒否される。
- ラジオモードは仕様どおり libx264 のまま（2fps/200k で元から極小負荷）。
- QSV / AMF はこのPCに該当GPUが無く**実機未検証**。誤っていてもプローブが落として
  libx264 へ退避するため、配信が止まることはない。

### 変更対象ファイル
- `streamer_core.py`（エンコーダー自動プローブ、引数生成、4経路の差し替え、ステータス）
- `config.dist.json` / `config_overrides.py`（既定値と `--video-encoder`）
- `gui_streamer.py` / `ui/index.html` / `plugin/ui/index.html`（選択UIと実動作の表示）
- `conftest.py`（テストが開発機のGPU有無で結果を変えないよう libx264 に固定）
- `test_hw_encoding.py`（新規・24件）

---

## 19. 🛠️ CLI 引数・環境設定オーバーライド機構の総点検・堅牢化 (CLI Arguments & Config Overrides Overhaul) 【実装完了 ✅】

### 概要
CLI 引数（`--port`, `--host`, `--no-tunnel`, `--resolution`, `--bitrate` 等）や `StreamerCore` 初期化時のオーバーライド引数（`override_port`, `override_host`, `override_enable_tunnel` 等）が、設定ファイル（`config.json`）の読み込み・保存や GUI / Web API（`/api/config`）からの動的設定更新と干渉し、CLI による一時指定が意図せず上書きされたり無効化される問題の総点検と再設計。

### 現状と課題
- **設定優先順位の曖昧さ**: `load_config()` や `update_config()` の実行時に、CLI で指定されたオーバーライド値が `config.json` の値で上書きされたり、逆に一時的な CLI 指定値が `config.json` に永続保存されてしまうリスクがある。
- **対応パラメータの不足**: 現状のオーバーライド機構が一部の主要パラメータ（port, host, enable_tunnel）に限定されており、他の設定項目（解像度、ビットレート、ラジオモード、QRオーバーレイ等）を CLI や一時引数から確実にオーバーライドする一貫した仕組みが不足している。

### 仕様・実装設計
1. **設定優先順位の厳格な階層化 (Configuration Precedence)**:
   - **優先度1 (最高)**: CLI 引数・環境変数・初期化時オーバーライド（明示的に指定された場合のみ、セッション中常に最優先）
   - **優先度2**: `config.json` に保存されたユーザー設定
   - **優先度3 (最低)**: システム既定値（デフォルト値）
2. **オーバーライド値の保護と `config.json` 永続化の分離**:
   - `self._cli_overrides` ディクショナリで CLI / 一時オーバーライド値を独立保持。
   - `get_config(key)` 参照時はオーバーライド値を返しつつ、`save_config()` 実行時は元の永続設定を破損させないクリーンな分離構造を確立。
3. **網羅的な単体テストの整備**:
   - CLI 引数指定時、設定ファイル読み込み時、API からの設定更新時における優先順位と動作を検証する自動テスト（`test_config_overrides.py`）を追加。

### 変更対象予定ファイル
- `streamer_core.py`（設定管理クラス / `_cli_overrides` メカニズムの刷新、`get_config` / `update_config` の整理）
- `gui_streamer.py`（CLI 引数パースと `StreamerCore` へのオーバーライド伝達の統合）
- `tests/test_config_overrides.py`（オーバーライド優先順位と永続化分離の単体テスト）

### 実装記録（2026-08-31 / ブランチ `feature/task19-config-overrides`）

#### ★着手前の調査で確定した不具合2件

- **GUIの設定保存が、CLI一時指定を config.json へ焼き付けていた**（設計意図と実装の食い違い）
  - `StreamerCore.__init__` のコメントは「CLI指定は焼き付けない」と宣言していたが、
    その担保は「保存直前に元の値へ戻す」`_cli_override_baseline` 方式だった。
  - GUIの設定画面はフォーム**全体**を送り返す（`gui_streamer.py` の `new_cfg`）。
    ウィジェットにはCLI上書き後の**実効値**が入っているため、`save_config()` の
    `for key in [k for k in baseline if k in new_config]: del baseline[key]` が
    「利用者が変更した」と誤認し、baseline から外して永続化していた。
  - 再現: `Local Test.bat`（`--no-tunnel`）で起動 → 設定画面で無関係な項目を1つ変える →
    保存 → `enable_tunnel: false` が config.json に永久に残る。
  - 実際に手元の `config.json` がこの状態になっていた。**README が「起動するだけで
    外部アクセス可能なURLが自動生成」と書いている挙動と矛盾する**（EXE直起動時）。
- **単体テストが利用者の実 `config.json` を書き換えていた**
  - `CONFIG_FILE` がモジュール定数の絶対パスで、`StreamerCore` が実ファイルへ保存していた。
  - 証拠: `standby_image_path` に `pytest-of-soufm/pytest-82/.../custom_test.png` という
    存在しない一時パスが焼き付いていた（テスト実行のたびに番号が進んでいた）。

#### 実装した設計

- **3層構造 `LayeredConfig`（`dict` のサブクラス）**
  優先順位は **CLI/環境変数 > `config.json` > `DEFAULT_CONFIG`**。
  `self.config` の参照が全体で212箇所あるため dict 自体は差し替えず、
  中身を常に「実効値」に保つサブクラスにした。既存の読み書きは無修正で動く。
  - `cfg[key] = value` … 利用者の設定変更 → 永続層へ記録
  - `set_override(key, value, source)` … その起動限りの指定 → 永続層に触れない
  - `persistable()` … `config.json` へ書く内容。**上書きは構造的に含まれない**ので、
    「保存直前に戻す」細工が不要になった（`_cli_override_baseline` は廃止）。
- **エコー判定**（Bug-1 の恒久対策）
  `save_config()` の入口で、上書き中のキーが**実効値と同じ値**で返ってきたら
  「利用者は触っていない」とみなして永続化しない。異なる値なら意図的な変更として
  永続化し、その起動でも反映されるよう当該キーの上書きを解除する。
- **`enable_tunnel` を property 化**。3箇所で代入されており設定と食い違う余地があった。
- **`config_path` を差し替え可能に**。テスト汚染の根本原因。
- **`config_overrides.py` を新設**（GUI非依存）。`--config` / `--output-mode` /
  `--resolution WxH` / `--bitrate` / `--fps` / `--radio` / `--no-radio` /
  `--set KEY=VALUE`、および環境変数 `VRCMS_*` を追加。
  - `--set` は `DEFAULT_CONFIG` の型で変換し、**未知のキーは通さない**。
    設定名の打ち間違いが「指定したのに効かない」という最も分かりにくい形で出るため。
  - **bool は int の派生**なので判定順を固定（逆にすると `loop_queue=true` が壊れる）。
  - `topaz_stream_key` / `generic_rtmp_key` / `web_password` は **`--set` では拒否**。
    コマンドライン引数はプロセス一覧から第三者に見えるため、環境変数のみ受け付ける。
  - 環境変数の未知キー・変換失敗は**そのキーだけ無視**（偶然の衝突で起動を止めない）。
- **`conftest.py` を新設**し、autouse フィクスチャで `config.json` をテスト専用の
  一時ファイルへ差し替える。個々のテストに `config_path=` を書き足す方法では
  **新しく書かれたテストが同じ穴を再び開ける**ため、共通フィクスチャで塞いだ。

#### 隔離して初めて露見した既存テストの問題

`test_destination.py` の `make_core()` が**開発者の手元の `config.json`（`output_mode: hls`）に
依存**していた。既定値（`topaz`）で走らせると、配信先キーを含む `save_config()` のたびに
実在しないホストへの到達性チェックが走って退避状態に入り、`get_video_url()` がHLSのURLを
返してURL組み立ての検証が別要因で落ちる。`make_core()` を `hls` 起点に固定して解消。
既定値そのものは `test_default_destination_and_fallback_safety` が `DEFAULT_CONFIG` に
対して直接検証しているため、カバレッジは失われていない。

#### テスト

`test_config_overrides.py` を新設（21件）。全90件通過（新規21 + 既存69）。
主な検証: エコー値を永続化しないこと / 明示的変更は永続化かつ即反映すること /
上書きが `persistable()` に混ざらないこと / 秘匿キーが `--set` で拒否されること /
別の `config_path` を指定したコアが既定の `config.json` を触らないこと。

#### この対応で解決しないもの（別途判断が必要）

- **`config.dist.json` の `enable_tunnel: false`**。機構は直ったが、配布物の**既定値**を
  どうするかは方針の決定であって実装の問題ではない。EXE を直接起動した場合は
  依然としてトンネルが立たない（`(Normal).bat` は `--tunnel` を渡すので立つ）。
- **`config.dist.json` の `output_mode: topaz` と README の「`hls`（既定）」の食い違い**。

---

## 20. 🌐 通常ブラウザ利用時のサーバー操作ボタン（再起動・起動）非表示化 【実装完了 ✅】

### 概要
WebリモコンUI（`ui/index.html`）を通常のブラウザ（Chrome / Edge 等）から開いた際、IPC権限を持たず機能しない「再起動」「サーバー起動」ボタンを非表示にし、ローカルアクセス（localhost）での「サーバー終了（停止）」操作は維持するよう表示ロジックを最適化。

### 仕様・実装内容
1. **実行環境判定の整理 (`isIpcAvailable()`)**:
   - `Boolean(window.electron && window.electron.ipcRenderer)` で VRCBeacon（Electron IPC環境）を判定。
2. **通常ブラウザ環境での挙動**:
   - **ヘッダーボタン**:
     - `btnHeaderStop`（サーバー終了）: ローカルホストアクセス時（`isLocal === true`）のみ表示（通常ブラウザでも利用可能）。
     - `btnHeaderRestart`（再起動）: VRCBeacon（IPC環境）かつ `isLocal` の場合のみ表示（通常ブラウザでは非表示）。
     - `btnHeaderLaunch`（起動）: VRCBeacon（IPC環境）かつ `isLocal` の場合のみ表示（通常ブラウザでは非表示）。
   - **オフラインバナー (`offlineBanner`)**:
     - `btnOfflineLaunch`（VRC_Media_Streamer を起動する）: VRCBeacon（IPC環境）のみ表示。
     - 通常ブラウザ（localhost）では「ホストPCで VRC_Media_Streamer.exe を起動してください」という案内と「状態を再確認」ボタンのみを表示。
     - リモート（ゲスト）では「配信サーバーに接続できません / ホストの再開をお待ちください」案内のみを表示。

### 変更対象ファイル
- `ui/index.html`（環境判定ロジックおよびライフサイクルボタンの表示制御）
- `plugin/ui/index.html`（自動同期）

---

## 21. 🛡️ Webリモコン機能の無効化・ホスト専用スタンドアロンモード (Disable Web Remote / Host-Only Mode) 【実装完了 ✅】

### 概要
ホストPCのデスクトップGUIのみで配信操作を完結させたいユーザー（VJ、イベント配信、プライベート鑑賞等）向けに、Webリモコン画面（`/`）やゲスト向け操作APIへのアクセスを遮断し、完全スタンドアロン（ホスト専用）で運用可能にする機能。

### 背景と目的
- **前提の訂正（実装時の調査で判明）**: 「トンネルを切ってもLANからリモコンが見える」は既定構成では起きない。
  `APIServer.start()` は config の `host` をそのまま bind し、既定は `127.0.0.1` のため LAN からは接続自体ができない。
  この機能が実際に効くのは次の2ケース。
  1. `host: "0.0.0.0"` にして LAN 公開しているとき。
  2. **HLS配信 + トンネル** — VRChatが `stream.m3u8` を取りに来るためポートを公開せざるを得ず、
     その副作用としてリモコン画面まで公開されるとき（**本命**）。
- **さらに判明した点**: `start_tunnel()` は `output_mode` を見ずに無条件で起動する。
  そのため既定構成（`output_mode: "topaz"` = RTMP押し出し + `enable_tunnel: true`）では、
  **配信はRTMPで出ているのに、トンネルはリモコン画面を配るためだけに公開URLを立てている**。
  ここで本機能をオフにすると、公開URLに残るのは403だけになる。
- **目的**:
  1. 他者からの操作・リクエスト受付を完全に拒絶する。
  2. QRオーバーレイやリモコンURL表示を自動で無効化し、クリーンな配信画面を維持する。

### 実装（v2.9.7+ / develop）
1. **設定項目**: `enable_web_remote`（既定 `true`）。
   - 未設定は `true` として扱う。既存ユーザーの `config.json` にキーが無いため、
     ここを fail-closed にすると更新しただけで全員のリモコンが黙って死ぬ。
   - GUI（`gui_streamer.py` の「📱 Webリモコン」節）とホストWeb UI（`hostEnableWebRemote`）の両方にトグル。
   - CLI: `--host-only` / `--web-remote`（両方指定時は安全側＝閉じる）。`VRCMS_ENABLE_WEB_REMOTE` も可。
2. **アクセス制御（`api_server.py`）**: `reject_if_web_remote_disabled()` を
   `do_GET` / `do_POST` の**認証判定より前**に置く。閉じているなら、パスワードが合っているかも
   `allow_web_*` で何が許されているかも問う必要がないため。
   - **ホスト判定は厳格なループバックのみ**（`_client_is_strict_loopback()`）。
     `is_local_request()` を流用しないのは `trust_lan_clients` を見ないため。「ホスト専用」なら
     同一LANの別端末も他人。
     **`CF-Connecting-IP` / `X-Forwarded-For` の確認は必須**: cloudflared はこのPCの `127.0.0.1` へ
     繋いでくるので、接続元IPだけを見るとトンネル経由の全員がホスト扱いになりゲートが素通りする。
   - **通すのは許可リスト方式**で `*.m3u8` / `*.ts` / `*.m4s` / `*.mp4` / `*.aac` のみ。
     `HLS_DIR` には写真プール `/images/*` が同居しており、「静的ファイルなら通す」にすると
     共有済みの写真が外へ出る。
   - ゲストへの応答: リモコン画面は **403 + 案内HTML**（バージョン・製品名を載せない／`/vendor/*` も
     閉じるためCSSは直書き）、それ以外は **403 JSON**。
3. **QR・ステータスの自動連動（`streamer_core.py`）**:
   - `generate_qr_overlay_image()` の冒頭で `None` を返す。**唯一の生成口**なので、
     動画・写真・ラジオ・待機画面の5箇所を個別に直す必要がない。
   - `standby_mode: "qr"`（QR案内画面）は画像モードへフォールバック。
   - `/api/status` の `overlay_qr_*` は消灯を返し、`remote_url` は空。**config の値そのものは
     書き換えない**ため、再度有効化すれば元の設定に戻る。
4. **トンネル遊休の警告（自動停止はしない）**: ホスト専用 + RTMP押し出し + HLSフォールバック無効の
   構成では、トンネルは403を返すだけになる。設定画面に警告を出すに留めた。
   `rtmp_fallback_to_hls` が有効な間はHLS退避にトンネルが要るうえ、クイックトンネルは張り直すと
   URLが変わり、ワールドに貼ったURLが死ぬため。

### 変更対象ファイル
- `streamer_core.py`（`enable_web_remote` の管理、QR生成のスキップ、待機画面フォールバック、ステータス反映）
- `api_server.py`（ゲートと403応答）
- `gui_streamer.py` / `ui/index.html` / `plugin/ui/index.html`（トグルとトンネル遊休警告）
- `config.dist.json` / `config_overrides.py`（既定値とCLI）
- `test_host_only_mode.py`（新規・34件）

### 負荷の実測（2026-09-04 / Intel 12コア, FFmpeg 8.1.2）
詳細は CHANGELOG の同項目。**効いたのはQRオーバーレイの停止だけで、それが桁違いだった。**

| 項目 | 実測 |
|---|---|
| **QR停止で FFmpeg がコピー経路へ戻る** | 49.14 → **0.55 CPU秒**（映像60秒あたり / **89.9倍**の差） |
| HLS視聴者のさばき（経路を絞ると消える分） | 1人あたり CPU 0.16秒/60秒（1コアの0.27%）・**上り1.56 Mbps** |
| ゲスト10人のポーリング | +0.48秒/60秒（**1コアの0.8%** = 想定よりずっと小さい） |
| 403に落としても1リクエスト 2.87ms（200は3.08ms） | ハンドラでなくHTTPの受け口が支配的 |

**注意**: QRの効果は「元からQRを点けていた場合」に限る（既定は `overlay_qr_enabled: false`）。
また**時計オーバーレイが点いていると、QRを消しても再エンコードは続く**（同じ分岐の別条件）。

### 残った制約（設計上の限界）
- **視聴は防げない**。HLS配信中は `stream.m3u8` / `*.ts` を開けておく必要があるため、
  URLを知る第三者の再生までは止められない。完全に inbound をゼロにしたい場合は
  RTMP押し出し（topaz / generic_rtmp）+ `enable_tunnel: false` + `host: 127.0.0.1` を選ぶ。
- ポート自体は開いており、403を返す。スキャンの対象にはなる（レートリミットは既存のものが効く）。

---

## 22. 🎙️ PC出力音声（ループバック）＆マイク入力音声の取り込み・配信 (PC Audio & Mic Capture) 【検討中 📋】

### 概要
ホストPC上で再生されている任意の音声（DAW、Spotify/Apple Music、ブラウザ、Discord通話、ゲーム音など）や、PCに接続されたマイク・オーディオインターフェースの入力音声を直接キャプチャし、BGM/ラジオモードや通常配信の音声ソースとしてVRChatワールドへリアルタイム配信する機能。

### ユースケース
1. **ホストDJ / DAWリアルタイム演奏**:
   - PCのDAW（FL Studio, Ableton Live等）やDJソフト（rekordbox, Traktor等）の出力をそのまま高音質配信。
2. **生実況・MC・ラジオトーク**:
   - ホストのマイク音声を取り込み、BGMやラジオカード画面・写真スライドショーに乗せてリアルタイム配信。
3. **PC内アプリ音声の共有**:
   - YouTube等のURL化されていないローカルプレイヤーやWebブラウザ上の音声をそのまま共有。

### 技術方式と実装設計
1. **Windows オーディオキャプチャ方式（FFmpeg）**:
   - **WASAPI ループバック（PC出力音）**:
     - `ffmpeg -f wasapi -i "default"` または `-f dshow -i audio="virtual-audio-capturer"`
     - Windows 10/11 標準の WASAPI を直接利用することで、仮想オーディオミキサー（VB-Audio等）の追加インストールなしでデスクトップ音声を直接取り込み可能。
   - **WASAPI / DirectShow マイク入力（PC入力音）**:
     - `ffmpeg -f wasapi -i "audio=マイク名"` または `-f dshow -i audio="マイク (Realtek High Definition Audio)"`
2. **ミキシングと音量バランス (`amix` フィルタ)**:
   - マイク音声（入力）とデスクトップ音声（出力）を同時に取り込み、`amix=inputs=2:weights='1 0.7'` 等でリアルタイム合成。
   - GUI/Webリモコン上でマイク音量・BGM音量スライダーを提供。
3. **映像との組み合わせ**:
   - 音声キャプチャ中も、静止画（ラジオカード、アルバム写真、待機画面）や時計・QRオーバーレイと結合して安定送出。

### 検討課題・留意点
- **デバイス名の動的取得**: ホストPCに接続されているマイク・スピーカーのデバイス一覧を列挙（`ffmpeg -list_devices true -f dshow -i dummy` 等）し、GUIで選択できる仕組みが必要。
- **TopazChat（低遅延）との併用**: 音声のみの生配信ではバッファ遅延（HLSの9〜12秒）が会話のボトルネックになるため、TopazChat（RTSP 1〜2秒）との併用が実用的。

### 実装記録（2026-09-06 / ブランチ `feature/task22-audio-capture`）

#### ★実測でひっくり返った設計前提（2026-09-06）

上の「技術方式と実装設計」に事実誤認が2件あった。同梱 ffmpeg 8.1.2-full (gyan.dev) で実測して判明。

1. **`-f wasapi` というデマクサは存在しない。** `ffmpeg -devices` で使える音声入力は
   `dshow` と `openal` のみ。WASAPI ループバックを使いたければ ffmpeg 単体では不可能で、
   Python 側（`pyaudiowpatch` 等）で掴んで PCM を stdin へ流す構成になる。**採用せず。**
2. **「仮想オーディオミキサー不要でデスクトップ音声が録れる」も成立しない。**
   開発機の `-list_devices` 実測では汎用の `Stereo Mix` も `virtual-audio-capturer` も存在せず、
   ループバック相当は `What U Hear (Sound Blaster X5)`（ハード固有）、
   `マイク (Virtual Desktop Audio)`、`Voicemeeter Out A1〜B3`（VB-Audio）のみだった。
   dshow でPC出力音を録るには、ハード固有機能か第三者製仮想デバイスへの依存が必須。

→ **方式は dshow 一本に確定。** 新規の pip 依存は追加していない。

#### タスク23（画面共有）と地続きにするための構造

タスク23は `ddagrab`/`gdigrab`（どちらも ffmpeg ネイティブ入力。同梱 ffmpeg に存在を確認済み）で
「1本の ffmpeg にライブ映像入力とライブ音声入力を並べる」形になる。音声も dshow なら `-i` が1本増える
だけで、A/V同期は ffmpeg 側のタイムスタンプが面倒を見る。Python PCM 経路を選ぶと同期・ドリフト・
アンダーランを自前で持つことになり、タスク23で作り直しになるため避けた。

そのため音声入力の組み立ては `build_dshow_audio_inputs()`（`self` に触らない純粋関数）へ切り出し、
`play_live_audio()` は「映像＝静止画」という一事例として実装している。タスク23は映像ソースを
差し替えるだけで済む。

#### 実装したもの

- `enumerate_dshow_audio_devices()` / `parse_dshow_audio_devices_output()` / `is_loopback_candidate()`
- `build_dshow_audio_inputs()` — 0/1/2デバイス、`volume` と `amix=inputs=2` の組み立て
- `StreamerCore.play_live_audio()` / `set_live_audio_devices()`、再生モード `"live"` の追加
- `queue_monitor_loop` の「モード0: ライブ音声取り込み」分岐（キューを消費しない）
- `GET /api/audio_devices`（localhost限定）、`POST /api/control` の `set_live_audio`（localhost限定）
- **UI（`ui/index.html`）**: 再生モードピルに「ライブ音声」を追加、設定タブに
  「ライブ音声取り込み」カード（マイク／ループバックのデバイス選択・音量スライダー2本・
  デバイス再スキャン）。どちらもホストPC（localhost）からのみ表示する。
  ★`plugin/ui/index.html` は `ui/index.html` と**バイト一致**していなければ
  `test_host_only_mode.py::test_plugin_ui_is_in_sync` が落ちる。UIを触ったら必ずコピーすること。
- `test_live_audio.py`（8ケース）

#### ★踏み抜くと分かりにくい罠（実装時に潰したもの）

- **`-vf` と `-filter_complex` は併用できない。** 時計オーバーレイ有効＋`amix` 有効のとき、
  時計フィルタを `[0:v]<clock>[vout]` として同じ `-filter_complex` に統合しないと起動しない。
  4通りの分岐すべてに回帰テストを置いた。
- **`-shortest` を付けてはいけない。** ライブ入力に終端が無いため。
- **`-max_interleave_delta 0` は必須。** ライブ入力2本は必ずドリフトし、既定の10秒を超えると
  受信側HLS multiplexer がセグメント出力を止める（タスク17で実際に起きた事故と同じ経路）。
- **`relay_stream_data` は `is_paced=False`。** 実時間駆動なのでペーシングを掛けない。
- **`-thread_queue_size 1024` と `-audio_buffer_size 50` を各 dshow 入力に付ける。**
  前者はライブ入力のフレーム落ち対策、後者は会話用途の遅延削減（ミリ秒）。
- **デバイス名は日本語で返ってくる。** `-list_devices` の stderr は bytes で受け、
  utf-8 → cp932 → replace の順でフォールバックする。`text=True` で Popen すると壊れる。
- **ffmpeg 8.x は列挙結果の各行に `[in#0 @ 000001c2760f36c0] ` を前置する。** 行頭一致の
  正規表現を書くと1件も取れない。
- **`-list_devices` は必ず非ゼロ終了する**（最後に `Error opening input file dummy.`）。
  returncode で成否を判定してはいけない。
- **ライブモードには「曲の終わり」が無い。** デバイスを掴めないと ffmpeg が即死して同じ分岐へ
  すぐ戻るため、短命終了（3秒未満）を数えて待ち時間を伸ばす後退（最大15秒）を入れている。
  これが無いとプロセス生成の暴走になる。

#### 実機スモークテスト（2026-09-06）

実デバイス2本（`Microphone (3- Razer Seiren V3 Mini)` + `What U Hear (Sound Blaster X5)`）に対し、
時計オーバーレイ＋`amix` を有効にした本番同等のコマンドを `-t 3 -f null -` で実行し、
returncode 0・映像160KiB・音声72KiB の生成を確認。両デバイスが開き、`drawtext` と `amix` が
同一 `-filter_complex` 内で正しく合成されることを実測で確認済み。

なお dshow の音声入力はデバイス稼働時間由来の巨大な開始タイムスタンプ（実測 `start 150410.02`）を
返すが、`_ts_offset_opts()` は `-output_ts_offset` のみで `-copyts` を使わないため影響しない。

#### ホストPCでの通し確認（2026-09-06）

アプリを `--no-tunnel --port 8123` で起動し、UIから実際に操作して確認した。

- `GET /api/audio_devices` が実機で17件を返し、日本語デバイス名が壊れず、
  ループバック候補の判定も正しいことを確認。
- 設定カードにデバイス18項目（「使用しない」含む）が並び、ループバック候補に
  ★マークが付くことをDOM上で確認。
- `set_live_audio` → `set_playback_mode: live` の順に叩き、
  `status=streaming` / `status_detail=Live audio capture` になり、
  HLSセグメントが生成され続けることを確認。
- 生成された `seg_00015.ts` を `ffprobe` にかけ、
  h264 + **aac 44100Hz stereo** の2ストリームが実際に入っていることを確認。

→ ホスト側の経路は通し確認済み。**VRChatワールド内での視聴確認だけが未実施。**

#### ★実機で判明した最大の落とし穴（2026-09-06）

**共有元ウィンドウを隠すと、そのアプリが描画を止める。** 配信がカクついて見えるが
アプリの不具合ではない。VRChatを共有元と同じモニタにフルスクリーンで置くと必ず起きる。

実測（同一ビルド・同一設定・TopazChatのRTSPを直接解析）: 背面 1.4fps / 見えている 29.6fps。

原因究明を何周も遠回りした理由は**測り方の誤り**だった。ffmpeg の `dup=` は
`ddagrab` が内部で複製するぶんを数えないため「29.8fps 出ている」と誤認した。
**実効fpsは「絵が実際に変わっているか」で数えること。** 詳細は
`docs/TASK23_実機テスト手順.md` の冒頭に記載した。

#### 未実装・引き続き必要なもの

- **VRChat実機での視聴確認**（ホスト側の送出までは確認済み。ワールド内での再生は未確認）
- **TopazChat併用時の実遅延の実測**（HLSの9〜12秒では会話が成立しないため、数値を取って記録する）
- 背景は現状 待機画面の静止画のみ。ラジオカード背景・スライドショー背景は未対応。

---

## 23. 🖥️ PCデスクトップ画面・ウィンドウのリアルタイムキャプチャ配信 (Desktop Screen Share) 【実装完了・VRC実機未確認 🟡】

### 概要
ホストPCのデスクトップ画面全体、セカンダリディスプレイ、または特定のアプリケーションウィンドウ（ブラウザ、ゲーム、DAW、プレゼン資料等）をリアルタイムでキャプチャし、VRChatワールド内のプレイヤーへ低遅延で映像配信する画面共有機能。

### ユースケース
1. **VRChat内でのプレゼン・勉強会・スライド発表**:
   - PowerPoint / PDF / ブラウザ画面をワールド内の大画面スクリーンにリアルタイム投影。
2. **ゲーム実況・作業配信・DAW画面共有**:
   - PCゲームのプレイ画面や作曲・モデリング画面をフレンドと一緒に鑑賞。
3. **URL再生に対応していない動画サイト・独自プレイヤーの共有**:
   - DRMや特殊プレイヤーで `yt-dlp` が対応していない動画でも、PC上で再生して画面ごと配信可能。

### 技術方式と実装設計
1. **Windows 画面キャプチャ方式（FFmpeg）**:
   - **DirectX Desktop Duplication API (`ddagrab` / 推奨・超低負荷)**:
     - `ffmpeg -f lavfi -i ddagrab=output_idx=0` (GPUアクセラレーションによる高速キャプチャ、60fpsでもCPU負荷極小)。
   - **GDI Grab (`gdigrab` / 高互換性フォールバック)**:
     - `ffmpeg -f gdigrab -i desktop` または `-f gdigrab -i title="Window Title"`
2. **映像エンコードと配信先**:
   - 画面キャプチャはリアルタイム性が重要なため、**NVENC / QSV によるハードウェアエンコード（タスク18）＋ TopazChat（タスク14）** との組み合わせを標準構成とする。
3. **音声キャプチャとの自動結合**:
   - タスク22の「PC出力音声取り込み」と同時に起動し、映像＋デスクトップ音声を完全同期して配信。

### 検討課題・留意点
- **解像度スケーリング**: 4K/WQHDディスプレイをそのまま配信すると帯域オーバーになるため、TopazChat推奨の 1080p/720p へのスケーリング（`scale=1920:1080:flags=bicubic`）を必須とする。
- **セキュリティ・プライバシー保護**: 個人情報やパスワードの誤配信を防ぐため、特定ウィンドウ限定キャプチャ機能や、キャプチャ開始前のプレビュー・確認ダイアログの提供。

### 実装準備の実測（2026-09-06 / ブランチ `feature/task23-screen-share`）

同梱想定の ffmpeg 8.1.2-full (gyan.dev) を開発機（NVIDIA GPU / 2560x1440 ×2枚）で実測した結果。
**上の「技術方式と実装設計」の記述には、実測で覆った点が2件ある。**

#### 使えることを確認した入力

| 方式 | 実測結果 |
|---|---|
| `-f lavfi -i ddagrab=output_idx=N:framerate=30` | ○ 画面0/1 とも 2560x1440 の **d3d11 ハードウェアフレーム**で取得 |
| `-f gdigrab -i desktop` | ○ ただし**全画面の外接矩形** 5120x1441 が返る（マルチモニタ結合） |
| `-f gdigrab -i "title=VRChat"` | ○ 2021x1121（ウィンドウの実サイズそのまま） |

#### ★実測で覆った前提

1. **「ddagrab は `-f lavfi -i` でも `-filter_complex` でも同じ」ではない。**
   `-init_hw_device d3d11va -filter_complex "ddagrab=...,hwmap=derive_device=cuda,..."` は
   `Failed to created derived device context: -40 (Function not implemented)` で**起動しない**。
   このビルドは d3d11 → cuda の device derive を持たない。
   → **`-f lavfi -i "ddagrab=..."` の入力形にすること。** この形なら
   `-c:v h264_nvenc` が d3d11 フレームを直接受け取り、無変換で通る（実測 RC=0）。
   `scale_cuda` も同じ理由で使えない。

2. **「GPUキャプチャなのでCPU負荷極小」は、そのままでは成立しない。**
   ゼロコピーが成立するのは **無加工でそのまま送るときだけ**。本機能では
   ・TopazChat 向けの 1080p スケーリング（必須。素材は 2560x1440）
   ・LIVE時計オーバーレイ（`drawtext`）
   のどちらも `hwdownload` を挟まないと掛けられない。
   → 実装は `[0:v]hwdownload,format=bgra,scale=...,format=yuv420p,<clock>[vout]` を前提に設計する。
   ゼロコピーは「スケール無し・オーバーレイ無し」の特殊構成としてのみ成立する。

#### 本番同等の通し確認（実測）

タスク22の `build_dshow_audio_inputs()` / `get_clock_filter_for_config()` /
`build_video_encoder_opts("h264_nvenc")` をそのまま呼び、映像を静止画から ddagrab へ
差し替えた形（＝タスク22で意図した「映像ソースの差し替えだけ」）で 3 秒送出した。

```
ffmpeg -f lavfi -i ddagrab=output_idx=0:framerate=30
       -f dshow -thread_queue_size 1024 -audio_buffer_size 50 -i audio=<マイク>
       -f dshow -thread_queue_size 1024 -audio_buffer_size 50 -i audio=<ループバック>
       -filter_complex "[0:v]hwdownload,format=bgra,scale=1920:1080:flags=bicubic,format=yuv420p,<drawtext>[vout];
                        [1:a]volume=1.0[amic];[2:a]volume=0.7[apc];[amic][apc]amix=inputs=2:...[aout]"
       -map [vout] -map [aout] <nvenc opts> -c:a aac -b:a 192k -ar 44100
       -max_interleave_delta 0 -muxdelay 0 -muxpreload 0 -f mpegts ...
```

→ **RC=0 / 1.75MiB / ffprobe で h264 1920x1080 30fps ＋ aac 44100Hz stereo の2本を確認。**
タスク22の設計（映像ソースだけ差し替える）が実際に成立することを実測で確認した。

#### ★踏み抜きそうな罠（実装前に潰しておく点）

- **キャプチャ解像度は奇数になりうる。** 実測で `gdigrab desktop` = 5120x**1441**、
  `gdigrab title=VRChat` = 2021x1121。yuv420p は偶数寸法を要求するので、
  スケール指定が無い経路には `scale=trunc(iw/2)*2:trunc(ih/2)*2` を必ず噛ませる。
  「1080p固定にするから関係ない」ではなく、アスペクト維持のパディング経路でも同じ。
- **`ddagrab` のディスプレイ列挙にきれいなエラーが無い。** `output_idx=2` は
  `Error configuring filter graph: Generic error in an external library` としか言わない。
  枚数はプローブ（`-t 0.5 -f null -` を idx 0 から順に試す）で決めるしかない。
  `-list_devices` 相当は存在しない。
- **`ddagrab` は画面が変化しないとフレームを出さない。** 実測で `dup=59 drop=6`。
  出力fpsは `-r` で固定し、`dup_frames` の既定に頼る。可変fpsのまま HLS へ流さない。
- **`-vf` と `-filter_complex` は併用できない**（タスク22と同じ罠）。音声 `amix` 有効時は
  映像側チェーンも同じ `-filter_complex` に統合すること。
- **`-shortest` を付けない / `-max_interleave_delta 0` は必須**（タスク22と同じ理由）。
- **`relay_stream_data` は `is_paced=False`**（実時間駆動のため）。
- **ウィンドウキャプチャは開始時の寸法で固定される。** 配信中に利用者がウィンドウを
  リサイズしたときの挙動は未確認。UI 側で「開始後はサイズを変えない」旨の注意が要る。
- **プライバシー**: `gdigrab desktop` は通知・パスワードマネージャ等も丸ごと映る。
  既定はデスクトップ全体ではなく**ディスプレイ指定 or ウィンドウ指定**にし、
  開始前にプレビューを見せる（上の「検討課題」の再確認）。

#### 実装方針（この時点の決定）

- 再生モード `"screen"` を追加し、`queue_monitor_loop` の「モード0」分岐を
  ライブ音声と共通化する（どちらもキューを消費しない実時間ソース）。
- 入力の組み立ては `build_screen_capture_input()`（`self` に触らない純粋関数）へ切り出し、
  `build_dshow_audio_inputs()` と同じ粒度で単体テストする。
- 音声はタスク22の設定をそのまま流用する（画面共有時にデスクトップ音も一緒に出るのが既定）。

### 実装したもの（2026-09-06）

- `probe_ddagrab_display()` / `enumerate_capture_displays()` — ddagrab に列挙APIが無いため
  `output_idx` を 0 から実際に起動して数える（最初の失敗で打ち切り・60秒キャッシュ）
- `enumerate_capture_windows()` / `find_capture_window()` — ctypes で `EnumWindows`。
  可視・非最小化・非cloaked・非ツールウィンドウ・160x120以上のみ。新規 pip 依存なし
- `even_dimension()` / `build_screen_capture_input()` / `build_screen_video_filter()`（純粋関数）
- `StreamerCore.play_screen_capture()` / `set_screen_capture_source()`、再生モード `"screen"` の追加
- `queue_monitor_loop` の「モード0b: 画面共有」分岐（短命終了の後退つき）
- `GET /api/capture_sources`（localhost限定）、`POST /api/control` の `set_screen_capture`（localhost限定）
- **UI**: 再生モードピルに「画面共有」、設定タブに「画面共有」カード
  （モニター／ウィンドウの切替・一覧再取得・解像度／fps／ビットレート・カーソル有無・注意書き2行）。
  ★`plugin/ui/index.html` とのバイト一致を維持すること
- `test_screen_capture.py`（14ケース）

### 実機検証（2026-09-06）

`python -m pytest` = **279 passed**。失敗2件（`test_transition` / `test_yt_dlp`）は
**変更前のベースラインでも同じく落ちる**ネットワーク依存テストで、本変更とは無関係。

自作テストは実物を触らないので、別途アプリのコードを直接呼んで実測した:

- `enumerate_capture_displays()` → ディスプレイ2枚（各 2560x1440）を正しく検出（所要 3.4秒）
- `enumerate_capture_windows()` → 可視ウィンドウ3件。日本語タイトル
  （`#ゲームクリップ | bakabakka - Discord`）も壊れない
- `find_capture_window()` → 完全一致は HIT、前方一致は **MISS**（意図どおり）
- **モニター配信**: `ddagrab` + `hwdownload` + 時計オーバーレイ + NVENC →
  rc=0 / 1.27MB / ffprobe で **h264 1280x720 20fps** を確認
- **ウィンドウ配信**: 1294x1399（縦長）のウィンドウを `gdigrab` で取り込み、
  `force_original_aspect_ratio=decrease` + `pad` で 720p へレターボックス →
  rc=0 / 1.17MB / **h264 1280x720 20fps** を確認

→ **ホスト側の送出は、モニター・ウィンドウの両方で通し確認済み。**

### ★設計判断として残しておくこと

- **ウィンドウは完全一致でしか掴めないので、部分一致のフォールバックを入れていない。**
  実測で `GitHub - Google Chrome` がタブ切替により
  `sou2000sw/VRC_Media_Streamer - Google Chrome` へ変わり、開けなくなることを確認した。
  ここで前方一致に逃がすと、似た名前の別ウィンドウ（パスワードマネージャ等）を
  映す事故になりうる。**見つからなければ諦めてエラーを出す**方を選んでいる。
  UI には一覧の再取得ボタンとその旨の注意書きを置いた。
- **ctypes は `argtypes`/`restype` を全関数に必ず指定する。** 省略すると 64bit で HWND が
  `c_int` に切り詰められ、一部のウィンドウが理由も分からず一覧から消える（実装中に踏んだ）。
- ディスプレイ列挙は ffmpeg を実起動するため 3.4秒かかる。60秒キャッシュしているが、
  UI は「再取得」に待ち表示が要る。

### 未実装・引き続き必要なもの

- **VRChat実機での視聴確認**（ホスト側の送出までは確認済み。ワールド内での再生は未確認）
- **TopazChat併用時の実遅延の実測**（プレゼン・実況用途で会話が成立するかは数値を取ってから）
- キャプチャ開始前のプレビュー（「検討課題」に挙げた確認ダイアログ）は未実装。
  現状は注意書きのみで、誤配信の最終防波堤になっていない
- 画面共有中の負荷（CPU/GPU）の実測。1080p60 が現実的かは未測定

---

## 24. 🎤 Webリモコンからの参加型カラオケ・楽器セッション機能 (Remote Karaoke & Live Session) 【検討中 📋】

### 概要
Webリモコン（スマホブラウザやPCブラウザ）を開いているワールド内の参加者が、マイクを使って歌声や楽器演奏をリアルタイムに送信し、ホスト側で伴奏（YouTubeやローカル音源）とミックスしてVRChat内に配信する参加型セッション機能。

### ユースケース
1. **VRChatカラオケ大会・歌枠**:
   - 参加者がスマホをマイク代わりにしてWebリモコンから歌を歌い、ホストが流すカラオケ音源とミックスしてワールド内大画面・スピーカーに流す。
2. **多人数セッション・合奏**:
   - 離れた参加者がそれぞれの楽器（ギター、キーボード等）や歌声をリモコン経由で重ねて合奏。

### 技術方式と実装アーキテクチャの検討
1. **ブラウザ側（Webリモコン）の音声取得**:
   - **Web Audio API (`navigator.mediaDevices.getUserMedia`)**:
     - スマホやPCのマイクから高音質（エコーキャンセラー・ノイズサプレッション設定可能）で音声を取得。
2. **音声の送信・通信方式**:
   - **アプローチA: WebSocket による低遅延 PCM/Opus ストリーミング (★ 推奨)**:
     - ブラウザから WebSocket 接続経由で音声チャンク（Opus / 16bit PCM）をホストサーバー（`api_server.py`）へリアルタイム送信。
   - **アプローチB: WebRTC（低遅延双方向 P2P / SFU）**:
     - 極小遅延（数十ミリ秒）での双方向通信が可能だが、Cloudflare トンネル環境での STUN/TURN やシグナリングサーバーの構築が必要。
3. **サーバー側ミキシングと送出**:
   - ホスト側の Python プロセス（または FFmpeg `amix` パイプ）で、再生中の動画/BGMトラックと受信した参加者の音声をミックス。
   - 歌詞の表示（Webリモコン上での同期歌詞表示や、配信画面へのカラオケテロップ合成）との連動。

### 検討課題・留意点
- **ネットワーク遅延と同期（Latency）**:
   - スマホマイク → ホストPC（WebSocket） → トランスコード → VRChatプレイヤー（TopazChat 1〜2秒、HLS 9〜12秒）の全体遅延が存在するため、歌い手側には「手元で伴奏を聞きながら歌う」ためのモニタリング設計（伴奏先出し・遅延相殺バッファリング）が必要。
- **ハウリング・エコー防止**:
   - スマホのスピーカーから出た音をマイクが再集音しないよう、イヤホン/ヘッドホン利用の推奨アナウンス。
