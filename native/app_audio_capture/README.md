# app_audio_capture

タスク25（アプリ単位の音声キャプチャ）用のネイティブ補助 exe。

**設計・契約は [../../docs/TASK25_アプリ音声キャプチャ_設計.md](../../docs/TASK25_アプリ音声キャプチャ_設計.md) が正本。**
ここには置き場所とビルド方法だけを書く。

## これは何か

指定した PID のプロセス（およびそのプロセスツリー）が鳴らしている音だけを
WASAPI のプロセスループバックで取り込み、**生PCM を stdout に流し続ける**だけの小さな exe。
FFmpeg には `-f s16le -ar 48000 -ac 2 -i pipe:0` として食わせる。

ffmpeg にはこの Windows API のバインディングが無いので、この exe が必要になる。

## 構成

```
native/app_audio_capture/
  build.bat     ビルド（vswhere で MSVC を自動検出）
  src/main.cpp  実体（未実装 / フェーズP0で作る）
  build/        成果物。.gitignore の build/ で除外される
```

## ビルド

```bat
native\app_audio_capture\build.bat
```

前提（2026-09-06 にこのPCで確認済み）:

- MSVC x64 — VS18 Community / MSVC 14.50.35717
- Windows SDK 10.0.26100.0（`audioclientactivationparams.h` を含むもの）
- Windows 10 build 20348 以上（実機は 11 の 26200）

## 注意

- **`.gitignore` の `*.exe` により成果物はコミットされない。** リリース同梱は
  `build_exe.py` / `VRC_Media_Streamer.spec` 側で明示的に拾うこと
- stdout は生PCM専用。ログを混ぜてはいけない。ログは stderr へ
