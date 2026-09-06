# window_capture

タスク26（ウィンドウ単位キャプチャ）用のネイティブ補助 exe。

**設計・契約は [../../docs/TASK26_ウィンドウ単位キャプチャ_設計.md](../../docs/TASK26_ウィンドウ単位キャプチャ_設計.md) が正本。**
ここには置き場所とビルド方法だけを書く。

## これは何か

指定した HWND のウィンドウの中身だけを `Windows.Graphics.Capture` で取り込み、
**生 BGRA フレームを壁時計基準で吐き続ける**だけの小さな exe。
**手前に重なった別ウィンドウが映らないこと**が全目的。

FFmpeg には `-f rawvideo -pixel_format bgra -video_size WxH -i \\.\pipe\NAME` として食わせる。

ffmpeg に WGC 入力は無いので、この exe が必要になる。

## 構成

```
native/window_capture/
  build.bat     ビルド（vswhere で MSVC を自動検出）
  src/main.cpp  実体
  build/        成果物。.gitignore の build/ で除外される
```

## ビルド

```bat
native\window_capture\build.bat
```

前提（2026-09-07 にこのPCで確認済み）:

- MSVC x64 — VS18 Community / `cl.exe 19.50.35728`
- Windows SDK 10.0.26100.0（C++/WinRT ヘッダを含むもの）
- Windows 10 build 1903 以上（黄色い枠の抑止は 22000 以上。実機は 11 の 26200）

## 注意

- **`.gitignore` の `*.exe` により成果物はコミットされない。** リリース同梱は
  `build_exe.py` / `VRC_Media_Streamer.spec` 側で明示的に拾うこと
- **`ID3D11Multithread` は `d3d11.h` ではなく `d3d11_4.h` にある。**
  `d3d11.h` だけを include すると C2065 で落ちる
- **フレームは stdout ではなく名前付きパイプへ流す。** stdout は取り込み側FFmpegの
  `pipe:0` がタスク25のアプリ音声で埋まっているため使えない。ログは stderr へ
- **`[wincap] ready size=WxH format=bgra` の1行が Python 側とのハンドシェイク。**
  書式を変えると `streamer_core.py` 側が待ちぼうけになる
