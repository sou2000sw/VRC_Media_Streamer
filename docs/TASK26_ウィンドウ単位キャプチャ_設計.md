# タスク26 ウィンドウ単位キャプチャ（WGC） — 設計

対象ブランチ: `feature/task26-wgc-window-capture`
状態: **設計。P0（原理確認）の一部は実測済み。**

OBS の「ウィンドウキャプチャ (Windows 10)」と同じことをする。
**選んだウィンドウの中身だけ**を取り込み、**手前に重なった別ウィンドウを映さない**。

タスク23で入れた現行方式（合成済みデスクトップをウィンドウ矩形で切り出す）は、
[CHANGELOG.md](../CHANGELOG.md) に書いたとおり **重なりがそのまま映る**。
プライバシー上ここが一番効く欠点で、それを潰すのがこのタスク。

---

## 1. なぜ ffmpeg だけでは無理か

| 方式 | 取得単位 | 重なり | 現行での扱い |
|---|---|---|---|
| `ddagrab`（DXGI Desktop Duplication） | **出力（モニタ）単位** | 合成後の絵しか無く排除不能 | ディスプレイ取り込みの既定 |
| `gdigrab -i "title=..."` | ウィンドウDCから BitBlt | 重なりは消えるが**GPU合成ウィンドウが真っ黒/真っ白**（実測: Chrome/Electron `mean=0.0`、Unity `mean=255.0`） | タスク23で**使用禁止**にした |
| `gdigrab -i desktop` + 矩形切り出し | 合成済みデスクトップの一部 | **そのまま映る** | 現行のウィンドウ取り込み |

引数の工夫で届く場所ではない。`Windows.Graphics.Capture`(WGC) は DWM から
**そのウィンドウのコンテンツだけ**を受け取るが、**ffmpeg に WGC 入力は存在しない**。

したがってタスク25（アプリ音声）とまったく同じ形 — **ネイティブの補助 exe** が要る。

---

## 2. 前提条件の実測（2026-09-07 / このPCで確認済み）

| 項目 | 必要 | 実測 | 判定 |
|---|---|---|---|
| OS ビルド | WGC は Win10 1903 以上、`IsBorderRequired` は 22000 以上 | Windows 11 `10.0.26200` | ✅ 余裕あり |
| C++ コンパイラ | MSVC x64 | タスク25の `build.bat` がそのまま通る環境 | ✅ |
| **ffmpeg が名前付きパイプから rawvideo を読めるか** | この設計の生命線 | **通った**（下記） | ✅ |

### 2.1 名前付きパイプの実測（★この設計の前提）

**stdin は使えない。** タスク25のアプリ音声補助exeが取り込み側FFmpegの `pipe:0` を
既に占有しており（[streamer_core.py:532](../streamer_core.py) `build_app_audio_input`）、
画面共有モードでもアプリ音声は同時に動く。映像には**別の経路**が要る。

Python 側で `CreateNamedPipeW` した `\\.\pipe\vrcms_wgc_probe` へ
320x240 BGRA を60フレーム書き、ffmpeg に読ませた結果:

| 項目 | 結果 |
|---|---|
| `ConnectNamedPipe` | 成功（ffmpeg 側がクライアントとして接続してきた） |
| 転送バイト数 | **18,432,000 = 60 × 320 × 240 × 4 に厳密一致** |
| 出力mp4 | `width=320 height=240 avg_frame_rate=30/1 nb_read_frames=60` |
| 画素 | 書いた `BGRA(0,0,255,255)` が `RGB(253,0,0)` で復元 → **バイト順も正しい** |
| ffmpeg rc | 0 |

- 切断時に `Error during demuxing: Invalid argument` が出るが、これは EOF の出方であって
  失敗ではない（rc=0、フレーム数も一致）。**このログを見て「壊れている」と判断しないこと。**
- 検証スクリプトは `scratchpad/pipe_probe.py`（リポジトリには入れない）。

**環境要因のブロッカーは無い。実装に進める。**

---

## 3. 構成

```
window_capture.exe                        streamer_core.py
  HWND
   → IGraphicsCaptureItemInterop
        ::CreateForWindow
   → Direct3D11CaptureFramePool
        (CreateFreeThreaded)
   → staging texture → Map → memcpy
   → 名前付きパイプへ生BGRAを一定間隔で書く
                     │
                     │  \\.\pipe\vrcms_wincap_<pid>
                     ▼
  ffmpeg -f rawvideo -pixel_format bgra -video_size WxH -framerate N -i \\.\pipe\...
         （音声は従来どおり pipe:0 / dshow。ここは一切触らない）
```

置き場所はタスク25に揃える。

```
native/window_capture/
  build.bat     ビルド（vswhere で MSVC を自動検出。/utf-8 必須）
  src/main.cpp  実体
  build/        成果物。.gitignore の build/ で除外される
  README.md
```

---

## 4. 補助exeの契約（正本）

### 4.1 起動引数

```
window_capture.exe --hwnd <N> --pipe <\\.\pipe\NAME>
                   [--fps 30] [--draw-mouse 0|1] [--no-border 1]
                   [--parent-pid N] [--stats SEC] [--connect-timeout 15]
```

| 引数 | 既定 | 意味 |
|---|---|---|
| `--hwnd` | 必須 | 取り込み対象。**タイトルではなくハンドルで受ける**（タイトルは不安定。タスク23で実証済み） |
| `--pipe` | 必須 | 出力先の名前付きパイプ名。exe がサーバ側を作る |
| `--fps` | 30 | 壁時計基準の送出レート。1〜60 |
| `--draw-mouse` | 1 | `GraphicsCaptureSession.IsCursorCaptureEnabled` |
| `--no-border` | 1 | `IsBorderRequired=false`（黄色い枠を消す）。失敗しても続行 |
| `--parent-pid` | なし | 親の死活監視。**タスク25で実際に2回、補助exeだけが残った** |
| `--stats` | 0 | N秒ごとに実効fps等を stderr へ |
| `--connect-timeout` | 15 | この秒数以内にクライアントが繋がらなければ終了 |

### 4.2 stdout / stderr

- **フレームは名前付きパイプへ。stdout は使わない**（タスク25は stdout が生PCM専用だったが、
  こちらは経路が違う。stdout に何か書いてもよいが、ログは stderr に統一する）
- **stderr は Python が必ず読み続ける。** 読まないとバッファが詰まって止まる（タスク25の教訓）

### 4.3 ハンドシェイク（★これが無いと組めない）

出力フレームの寸法は Python が事前に知り得ない。`GetWindowRect` は DWM の影や枠を含み、
WGC の item size と一致する保証が無い。**exe が決めて、Python に伝える。**

パイプを作り、item size を確定した直後に、stderr へ**ちょうど1行**:

```
[wincap] ready size=1920x1080 format=bgra pipe=\\.\pipe\vrcms_wincap_1234
```

Python はこの行を最大5秒待ってから ffmpeg を起動する。順序は必ず
**exe起動 → ready受信 → ffmpeg起動 → exeがConnectNamedPipeを抜ける**。
逆順にすると ffmpeg が存在しないパイプを開きに行って落ちる。

### 4.4 終了コード

| コード | 意味 | Python 側の扱い |
|---|---|---|
| 0 | 正常終了 | — |
| 2 | 引数不正 | 現行方式へフォールバック |
| 3 | WGC が使えない（OS/GPU/API） | 現行方式へフォールバック |
| 4 | ウィンドウが無効・閉じられた | 既存の「対象消失 → 待機画面」経路へ |
| 5 | パイプ生成・接続の失敗 | 現行方式へフォールバック |

---

## 5. 設計判断（ここを外すと三度払う）

### 5.1 フレームは壁時計で送る。WGC の到着に同期させてはいけない

**WGC は「変化があったときだけ」フレームを配る。** 静止した画面では供給が止まり、
そのまま流すと ffmpeg への入力が途切れて HLS が痩せる。

→ **FrameArrived は「最新フレーム」バッファを更新するだけ**にし、
**別スレッドが 1/fps の壁時計間隔で最新バッファをパイプへ書く**。
新しいフレームが来ていなければ**直前のフレームをそのまま再送**する。

タスク25では「無音埋めは不要だった」という実測結果が出たが、**あれは音声の話で、
ここには適用できない。** WASAPI は無音でもパケットを供給するが、WGC は供給しない。
同じ理屈で省略しないこと。

副次的な利点として、この形は backpressure も自然に処理する。ffmpeg が詰まって
`WriteFile` がブロックしたら、その間に届いた中間フレームは黙って捨てられる。

### 5.2 フレーム寸法はセッション中ずっと固定。リサイズは切り貼りで吸収する

`-video_size` は起動時に固定される。途中で寸法が変わると ffmpeg が壊れる。

ウィンドウがリサイズされたら frame pool は作り直すが、**パイプへ書く寸法は起動時の
WxH のまま**。新しい絵は中央寄せで、はみ出しは切り、足りない分は黒で埋める。
**拡大縮小（リサンプル）はしない** — CPU で品質のある縮小をやると重く、
GPU でやるには VideoProcessor が要る。どちらも初手では割に合わない。
最終的な寸法合わせは ffmpeg 側の `scale`+`pad` が既にやっている
（[streamer_core.py:1261](../streamer_core.py) `build_screen_video_filter`）。

### 5.3 画素形式は BGRA のまま出す。NV12 化は測ってから

BGRA 1920x1080@30 = **約249MB/s**。名前付きパイプはカーネルオブジェクトなので
匿名パイプと同等の速度が出るはずだが、**これは推測であって実測ではない。**

NV12 に落とせば約93MB/s になるが、変換コストが乗る。
**P0 で実効fpsとCPU使用率を測り、必要が示されてから**変える。
先回りして NV12 を入れない（CLAUDE.md: 性能に効く変更を推測で入れない）。

`--pixel-format` を後から足せる形にだけしておく。

### 5.4 失敗したら現行方式へ黙って落ちる（fail-soft）

exe が無い / 起動しない / ready が来ない / rc が 2,3,5 のいずれか
→ **今の `resolve_window_capture_plan()` の結果（ddagrab / gdigrab 切り出し）で配信する。**
配信そのものが落ちる方が、重なりが映るより事故として重い。
ただし**フォールバックしたことは log と status に必ず残す**。黙って画質・
プライバシー特性が変わるのが一番たちが悪い。

### 5.5 誇張しないこと — 「覆われると重くなる」は WGC では直らない可能性がある

現行UIの注意書き（[ui/index.html:852](../ui/index.html)）にある
**「覆われたり背面になると 29.6fps → 1.4fps まで落ちる」は、アプリ自身が描画を
止めることによる**（Chrome の背面タブ抑制、Unity の非アクティブ時フレームレート制限）。
WGC は「合成された結果」を取るだけなので、**アプリが描かなければ絵は更新されない。**

重なりが**映らなくなる**のは確実。**重なっても滑らかに動く**かは別問題で、
P0 で必ず測る。測る前にUIの注意書きを書き換えないこと。

---

## 6. フェーズ

### P0 — 原理確認（これが通らなければ以降は無い）

`window_capture.exe` を作り、**ファイルへ**生BGRAを数秒書き出して検証する。
Python 統合はまだしない。

**合否の判定は「rc=0」でも「バイト数」でもない。絵を見る。**
タスク23で「rc=0 かつ h264 生成済みなのに真っ黒」をすり抜けた前科がある。

| # | 測ること | 合格条件 |
|---|---|---|
| 1 | GPU合成ウィンドウが黒くならないか（Chrome / Electron / Unity(VRChat)） | `mean` が 0.0 でも 255.0 でもない。タスク23の実測値（30.6 / 37.2 / 133.7）と同程度 |
| 2 | **重なりが映らないか** | 対象の上に別ウィンドウを重ねた状態で撮り、**重ねた側の特徴色が出力に現れない**。★この機能の全目的。ここを目視だけで済ませない |
| 3 | 静止画面でフレームが途切れないか | 10秒で `10 × fps` フレームがパイプ/ファイルに出る（±1） |
| 4 | 実効fpsとCPU | 1920x1080@30 で送出fpsが 29.5 以上、CPU が現行方式を上回らない |
| 5 | 覆った状態のfps（5.5の件） | 数値を記録する。**合否ではなく事実の記録** |
| 6 | リサイズ中に寸法が変わらないか | 出力バイト数が常に `W*H*4` の倍数 |
| 7 | 黄色い枠 | `--no-border 1` で出ない |

### P1 — 統合

- `streamer_core.py`
  - `get_window_capture_cmd()`（`get_app_audio_capture_cmd()` と同型）
  - `start_window_capture_helper(hwnd, pipe, fps, draw_mouse)` → `(proc, w, h)` / `None`
  - `build_screen_capture_input()` に `("wgc", pipe, w, h)` の plan を追加。`needs_hwdownload=False`
  - `resolve_window_capture_plan()` を `screen_capture_window_method` で分岐
  - `play_screen_capture()` で helper の起動・stderr の吸い出し・確実な後始末
    （`kill_proc` 漏れは補助exeの残留に直結する。タスク25で2回起きている）
- 設定キー追加: `screen_capture_window_method` = `"auto"` | `"wgc"` | `"desktop_crop"`（既定 `"auto"`）
- `build_exe.py` に `window_capture.exe` の同梱（`get_app_audio_capture_source()` と同型）
- `ui/index.html:852` の注意書きを**実測に合わせて**書き換える
- `test_screen_capture.py` に単体テストを追加

---

## 7. 参考

- タスク25 の設計と契約: [TASK25_アプリ音声キャプチャ_設計.md](TASK25_アプリ音声キャプチャ_設計.md)
- タスク23 の実機テスト手順（重なりの扱いを書き換える対象）: [TASK23_実機テスト手順.md](TASK23_実機テスト手順.md)
