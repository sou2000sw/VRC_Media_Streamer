# GStreamer Direct Screen-Capture Backend

## Overview

The GStreamer backend (`gstreamer_backend.py`) is an experimental single-pipeline capture architecture for VRC Media Streamer (`v2.11.0-gst-beta.1`).

It captures video and application/system audio in a single GStreamer pipeline and outputs directly to HLS (`hlssink2`) or RTMP (`flvmux` + `rtmpsink`). This bypasses the Python MPEG-TS relay and the persistent second FFmpeg sink, eliminating double encoding overhead and improving latency and framerate stability.

The existing FFmpeg capture implementation remains fully functional as a automatic fail-soft fallback.

## Architecture & Control Flow

```
+-------------------------------------------------------------------------+
|                        GStreamer Pipeline                               |
|                                                                         |
|  [Display / Window] -> d3d11screencapturesrc ! d3d11convert !           |
|                          cudaupload ! nvh264enc ! h264parse ----+       |
|                                                                 |       |
|  [App Audio]        -> wasapi2src (loopback) ----------------+  |       |
|  [Mic / Loopback]   -> dshowaudiosrc (or silent fallback) --+  |  |       |
|                                                             v  v  v       |
|                                                      [audiomixer]       |
|                                                             |           |
|                                                             v           |
|                                                        [avenc_aac]      |
|                                                             |           |
|                                                             v           |
|                                                         [aacparse]      |
|                                                             |           |
|                                     +-----------------------+           |
|                                     |                                   |
|                                     v                                   |
|                          +--------------------+                         |
|                          | Output Sink        |                         |
|                          | HLS: hlssink2      |                         |
|                          | RTMP: flvmux/sink  |                         |
|                          +--------------------+                         |
+-------------------------------------------------------------------------+
```

### Video Branch
- **Display capture**: `d3d11screencapturesrc monitor-index=N show-cursor=... do-timestamp=true`
- **Window capture**: `d3d11screencapturesrc capture-api=wgc window-handle=HWND show-border=false show-cursor=... do-timestamp=true`
- Hardware processing: `D3D11 BGRA caps ! d3d11convert ! cudaupload ! CUDA BGRA caps ! nvh264enc (CBR, zerolatency, bframes=0) ! h264parse`

### Audio Branch
- **Application Audio**: `wasapi2src loopback=true low-latency=true continue-on-error=true do-timestamp=true loopback-target-pid=PID loopback-mode=include-process-tree|exclude-process-tree`
- **Mic / System Loopback**: `dshowaudiosrc device-name="..." do-timestamp=true`
- **Silent Fallback**: `audiotestsrc is-live=true wave=silence do-timestamp=true` if no audio source is active.
- **Mixer & Encoder**: `audiomixer name=mix ! capsfilter caps="audio/x-raw, rate=44100, channels=2" ! audioconvert ! audioresample ! avenc_aac bitrate=... ! aacparse`

### Output Modes
- **HLS**: Links video/audio to request pads of `hlssink2` (`location=.../seg_%05d.ts`, `playlist-location=.../stream.m3u8`, bounded `max-files`).
- **RTMP**: Muxes video/audio queues into `flvmux streamable=true enforce-increasing-timestamps=true ! rtmpsink location=...`.

## Runtime Resolution & Validation

GStreamer binaries are executed out-of-process via `subprocess.Popen(args, shell=False, env=env)`. GStreamer is not embedded in the PyInstaller executable.

Resolution Order:
1. Explicit `--gstreamer-root` CLI argument / `override_gstreamer_root` parameter.
2. `APP_DIR/gstreamer` (packaged distribution directory next to `VRC_Media_Streamer.exe`).
3. Repository `.gstreamer_runtime` (development environment).

Environment Construction:
Child process environment dictionaries are constructed by importing `gstreamer_libs` and calling `gstreamer_libs.gstreamer_env()`. Global `os.environ` is never mutated.

Runtime Validation & Fallback:
Runtime validation caches results per runtime directory. Required elements verified:
`d3d11screencapturesrc`, `d3d11convert`, `cudaupload`, `nvh264enc`, `wasapi2src`, `dshowaudiosrc`, `audiomixer`, `audioconvert`, `audioresample`, `avenc_aac`, `h264parse`, `aacparse`, `hlssink2`, `flvmux`, `rtmpsink`.

Fallback Scenarios to FFmpeg:
- GStreamer runtime directory missing or validation fails.
- Karaoke voice routing is active (`karaoke.enabled = True`).
- Pipeline plan construction or process launch fails.
- Direct capture suppression avoids restarting the persistent FFmpeg sink while GStreamer is active.

## Configuration & Status API

Configuration Key:
`"screen_capture_backend"`: `"gstreamer"` (default on beta branch) or `"ffmpeg"`.

Status API (`/api/status`):
- `screen_capture_backend`: Configured backend.
- `active_screen_capture_backend`: Currently active backend (`"gstreamer"` or `"ffmpeg"`).
- `gstreamer_available`: Boolean indicating runtime availability and validation status.
- `gstreamer_fallback_reason`: Detailed reason string if falling back to FFmpeg (or `None`).

## Packaging & Licensing

- **Bundle Source**: PyPI `gstreamer-bundle==1.28.6` (~331 MiB).
- **Distribution Layout**: Packaged under `gstreamer/` adjacent to `VRC_Media_Streamer.exe` in `dist/`, `releases/VRC_Media_Streamer_v2.11.0-gst-beta.1/`, and `plugin/bin/gstreamer/`.
- **License**: GStreamer runtime components are licensed under LGPL v2.1+ / GPL for restricted plugins. Refer to `THIRD_PARTY_LICENSES.txt` for details.
