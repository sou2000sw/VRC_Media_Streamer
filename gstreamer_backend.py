# -*- coding: utf-8 -*-
"""GStreamer direct screen/window capture backend for VRC Media Streamer.

Constructs single GStreamer pipelines (video + audio -> HLS or RTMP)
and manages GStreamer runtime resolution and validation.
"""

import os
import re
import sys
import logging
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

REQUIRED_GSTREAMER_ELEMENTS = [
    "d3d11screencapturesrc",
    "d3d11convert",
    "cudaupload",
    "nvh264enc",
    "wasapi2src",
    "dshowaudiosrc",
    "audiomixer",
    "audioconvert",
    "audioresample",
    "avenc_aac",
    "h264parse",
    "aacparse",
    "hlssink2",
    "flvmux",
    "rtmpsink",
]

_VALIDATION_CACHE: Dict[str, Tuple[bool, str]] = {}


@dataclass
class GStreamerPlan:
    cmd: List[str]
    env: Dict[str, str]
    display_target: str
    output_mode: str


def escape_gst_prop_string(s: Optional[str]) -> str:
    """Quotes and escapes string property values for GStreamer CLI property assignment."""
    if s is None:
        return '""'
    escaped = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def redact_rtmp_url(url: Optional[str]) -> str:
    """Redacts secret stream keys from RTMP URLs for safe display and logging."""
    if not url:
        return ""
    if "://" not in url:
        return "[REDACTED]"
    parts = url.split("://", 1)
    scheme = parts[0]
    rest = parts[1]
    slash_parts = rest.split("/")
    if len(slash_parts) >= 2:
        slash_parts[-1] = "***"
        return f"{scheme}://{'/'.join(slash_parts)}"
    return f"{scheme}://{rest}"


def redact_gstreamer_log(text: Optional[str]) -> str:
    """Redact RTMP(S) URLs embedded in a GStreamer diagnostic line."""
    value = str(text or "")
    return re.sub(
        r"rtmps?://[^\s\"']+",
        lambda match: redact_rtmp_url(match.group(0)),
        value,
        flags=re.IGNORECASE,
    )


def resolve_gstreamer_binary(runtime_dir: str, exe_name: str) -> Optional[str]:
    """
    Resolves the real GStreamer executable path within runtime_dir.

    Prefers the real packaged executable at runtime_dir/gstreamer_cli/bin/{exe_name} over
    the root runtime_dir/bin/{exe_name} (which may be a PyPI console script launcher wrapper
    that leaves child processes orphaned when terminated).
    Fallback to root bin is only used if gstreamer_cli is not present.
    """
    if not runtime_dir:
        return None
    norm_dir = os.path.abspath(runtime_dir)
    real_cli_path = os.path.join(norm_dir, "gstreamer_cli", "bin", exe_name)
    if os.path.isfile(real_cli_path):
        return real_cli_path

    fallback_path = os.path.join(norm_dir, "bin", exe_name)
    if os.path.isfile(fallback_path):
        return fallback_path
    return None


def get_gst_launch_path(runtime_dir: str) -> Optional[str]:
    """Resolves path to gst-launch-1.0.exe, preferring gstreamer_cli/bin/ to avoid wrapper orphans."""
    return resolve_gstreamer_binary(runtime_dir, "gst-launch-1.0.exe")


def get_gst_inspect_path(runtime_dir: str) -> Optional[str]:
    """Resolves path to gst-inspect-1.0.exe, preferring gstreamer_cli/bin/."""
    return resolve_gstreamer_binary(runtime_dir, "gst-inspect-1.0.exe")


def get_gstreamer_runtime_dir(override_path: Optional[str] = None) -> Optional[str]:
    """
    Resolves GStreamer runtime root directory in order:
    1. Explicit override_path (if provided and valid)
    2. APP_DIR / gstreamer
    3. BASE_PATH / .gstreamer_runtime
    Returns the absolute directory path containing resolved gst-launch-1.0.exe, or None.
    """
    candidates = []
    if override_path:
        candidates.append(os.path.abspath(override_path))

    if getattr(sys, 'frozen', False):
        app_dir = os.path.dirname(sys.executable)
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
        app_dir = base_path

    candidates.append(os.path.join(app_dir, "gstreamer"))
    candidates.append(os.path.join(base_path, ".gstreamer_runtime"))

    for path in candidates:
        if path and os.path.isdir(path):
            if get_gst_launch_path(path):
                return os.path.abspath(path)
    return None


def get_gstreamer_env(runtime_dir: str) -> Optional[Dict[str, str]]:
    """
    Constructs child environment for GStreamer by temporarily adding runtime_dir to sys.path
    and importing gstreamer_libs. Does NOT mutate global os.environ.
    """
    if not runtime_dir or not os.path.isdir(runtime_dir):
        return None

    norm_dir = os.path.abspath(runtime_dir)
    sys_path_inserted = False
    if norm_dir not in sys.path:
        sys.path.insert(0, norm_dir)
        sys_path_inserted = True

    try:
        import gstreamer_libs
        res = gstreamer_libs.gstreamer_env()
        if isinstance(res, tuple):
            env_dict = res[0]
        elif isinstance(res, dict):
            env_dict = res
        else:
            return None
        return dict(env_dict)
    except Exception as e:
        logger.warning(f"[GStreamer] Failed to construct environment from {norm_dir}: {e}")
        return None
    finally:
        if sys_path_inserted and norm_dir in sys.path:
            sys.path.remove(norm_dir)


def validate_gstreamer_runtime(runtime_dir: str) -> Tuple[bool, str]:
    """
    Validates GStreamer runtime directory and checks for required elements using gst-inspect-1.0.exe.
    Results are cached per runtime_dir path.
    """
    if not runtime_dir or not os.path.isdir(runtime_dir):
        return False, "Runtime directory does not exist"

    norm_dir = os.path.abspath(runtime_dir)
    if norm_dir in _VALIDATION_CACHE:
        return _VALIDATION_CACHE[norm_dir]

    gst_launch = get_gst_launch_path(norm_dir)
    gst_inspect = get_gst_inspect_path(norm_dir)
    if not gst_launch:
        res = (False, f"Missing gst-launch-1.0.exe in {norm_dir}")
        _VALIDATION_CACHE[norm_dir] = res
        return res
    if not gst_inspect:
        res = (False, f"Missing gst-inspect-1.0.exe in {norm_dir}")
        _VALIDATION_CACHE[norm_dir] = res
        return res

    env = get_gstreamer_env(norm_dir)
    if not env:
        res = (False, f"Failed to get GStreamer environment for {norm_dir}")
        _VALIDATION_CACHE[norm_dir] = res
        return res

    creation_flags = 0x08000000 if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            [gst_inspect],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
            timeout=15,
        )
        if proc.returncode != 0:
            res = (False, f"gst-inspect-1.0 exited with code {proc.returncode}")
            _VALIDATION_CACHE[norm_dir] = res
            return res
        inspect_out = proc.stdout.decode("utf-8", errors="ignore")
        missing_elements = [elem for elem in REQUIRED_GSTREAMER_ELEMENTS if elem not in inspect_out]
        if missing_elements:
            res = (False, f"Missing required GStreamer elements: {', '.join(missing_elements)}")
            _VALIDATION_CACHE[norm_dir] = res
            return res
    except Exception as e:
        res = (False, f"Runtime inspection error: {e}")
        _VALIDATION_CACHE[norm_dir] = res
        return res

    res = (True, "OK")
    _VALIDATION_CACHE[norm_dir] = res
    return res


def clear_validation_cache():
    """Clears the runtime validation cache (for testing)."""
    _VALIDATION_CACHE.clear()


def build_gstreamer_screen_capture_plan(
    runtime_dir: str,
    source_type: str = "display",
    display_index: int = 0,
    hwnd: Optional[int] = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    draw_mouse: bool = True,
    bitrate_kbps: int = 4000,
    gop_seconds: float = 2.0,
    app_audio_enabled: bool = False,
    app_pid: Optional[int] = None,
    app_mode: str = "include",
    app_volume: float = 1.0,
    mic_device: str = "",
    mic_volume: float = 1.0,
    loopback_device: str = "",
    loopback_volume: float = 0.7,
    audio_bitrate_kbps: int = 192,
    output_mode: str = "hls",
    hls_dir: Optional[str] = None,
    hls_segment_time: int = 3,
    hls_list_size: int = 15,
    rtmp_url: Optional[str] = None,
) -> GStreamerPlan:
    """
    Builds a pure GStreamer plan containing the argument list for subprocess execution,
    child environment dict, display-safe target description, and output mode.

    Every element and property is emitted as a separate argv token.
    Caps are formatted as a single no-whitespace string token.
    Flags -q and -e are included in the command header.
    """
    gst_launch_exe = get_gst_launch_path(runtime_dir) or os.path.join(runtime_dir, "bin", "gst-launch-1.0.exe")
    env = get_gstreamer_env(runtime_dir) or {}

    fps = max(1, min(60, int(fps)))
    width = max(320, int(width))
    height = max(240, int(height))
    bitrate_kbps = max(500, int(bitrate_kbps))
    gop_size = max(1, int(fps * max(0.5, float(gop_seconds))))
    show_cursor_str = "true" if draw_mouse else "false"

    if source_type == "window":
        hwnd_val = int(hwnd) if hwnd is not None else 0
        vsrc_tokens = [
            "d3d11screencapturesrc",
            "capture-api=wgc",
            f"window-handle={hwnd_val}",
            "show-border=false",
            f"show-cursor={show_cursor_str}",
            "do-timestamp=true",
        ]
    else:
        disp_idx = max(0, int(display_index))
        vsrc_tokens = [
            "d3d11screencapturesrc",
            f"monitor-index={disp_idx}",
            f"show-cursor={show_cursor_str}",
            "do-timestamp=true",
        ]

    v_pipeline = [
        *vsrc_tokens,
        "!", f"video/x-raw(memory:D3D11Memory),framerate={fps}/1",
        "!", "queue", "max-size-buffers=2", "max-size-bytes=0", "max-size-time=0", "leaky=downstream",
        "!", "d3d11convert",
        "!", f"video/x-raw(memory:D3D11Memory),format=BGRA,width={width},height={height},framerate={fps}/1",
        "!", "cudaupload",
        "!", "video/x-raw(memory:CUDAMemory),format=BGRA",
        "!", "nvh264enc", f"bitrate={bitrate_kbps}", "rc-mode=cbr", f"gop-size={gop_size}", "zerolatency=true", "bframes=0",
        "!", "h264parse", "config-interval=-1",
    ]

    active_audio_sources: List[List[str]] = []

    if app_audio_enabled and app_pid is not None and int(app_pid) > 0:
        mode_str = "include-process-tree" if app_mode == "include" else "exclude-process-tree"
        app_src = [
            "wasapi2src", "loopback=true", "low-latency=true", "continue-on-error=true", "do-timestamp=true",
            f"loopback-target-pid={int(app_pid)}", f"loopback-mode={mode_str}",
            "!", "queue", "max-size-buffers=0", "max-size-bytes=0", "max-size-time=2000000000", "leaky=downstream",
            "!", "audioconvert",
            "!", "audioresample",
            "!", "volume", f"volume={float(app_volume)}",
            "!", "mix."
        ]
        active_audio_sources.append(app_src)

    if mic_device and str(mic_device).strip():
        escaped_mic = escape_gst_prop_string(str(mic_device).strip())
        mic_src = [
            "dshowaudiosrc", f"device-name={escaped_mic}", "do-timestamp=true",
            "!", "queue", "max-size-buffers=0", "max-size-bytes=0", "max-size-time=2000000000", "leaky=downstream",
            "!", "audioconvert",
            "!", "audioresample",
            "!", "volume", f"volume={float(mic_volume)}",
            "!", "mix."
        ]
        active_audio_sources.append(mic_src)

    if loopback_device and str(loopback_device).strip():
        escaped_loopback = escape_gst_prop_string(str(loopback_device).strip())
        loopback_src = [
            "dshowaudiosrc", f"device-name={escaped_loopback}", "do-timestamp=true",
            "!", "queue", "max-size-buffers=0", "max-size-bytes=0", "max-size-time=2000000000", "leaky=downstream",
            "!", "audioconvert",
            "!", "audioresample",
            "!", "volume", f"volume={float(loopback_volume)}",
            "!", "mix."
        ]
        active_audio_sources.append(loopback_src)

    if not active_audio_sources:
        silent_src = [
            "audiotestsrc", "is-live=true", "wave=silence", "do-timestamp=true",
            "!", "queue", "max-size-buffers=0", "max-size-bytes=0", "max-size-time=2000000000", "leaky=downstream",
            "!", "audioconvert",
            "!", "audioresample",
            "!", "mix."
        ]
        active_audio_sources.append(silent_src)

    audio_bitrate_bps = max(32000, int(audio_bitrate_kbps) * 1000)
    a_mixer = [
        "audiomixer", "name=mix",
        "!", "capsfilter", "caps=audio/x-raw,rate=44100,channels=2",
        "!", "audioconvert",
        "!", "audioresample",
        "!", "avenc_aac", f"bitrate={audio_bitrate_bps}",
        "!", "aacparse",
    ]

    cmd: List[str] = [gst_launch_exe, "-q", "-e"]

    if output_mode == "rtmp":
        clean_url = str(rtmp_url or "")
        display_target = f"GStreamer Direct Screen Capture -> RTMP ({redact_rtmp_url(clean_url)})"
        cmd.extend(v_pipeline)
        cmd.extend(["!", "queue", "!", "mux.video"])
        for src_tokens in active_audio_sources:
            cmd.extend(src_tokens)
        cmd.extend(a_mixer)
        cmd.extend(["!", "queue", "!", "mux.audio"])
        cmd.extend([
            "flvmux", "name=mux", "streamable=true", "enforce-increasing-timestamps=true",
            "!", "rtmpsink", f"location={clean_url}",
        ])
    else:  # "hls"
        clean_hls_dir = (hls_dir or "").replace("\\", "/")
        seg_loc = f"{clean_hls_dir}/seg_%05d.ts"
        playlist_loc = f"{clean_hls_dir}/stream.m3u8"
        max_files = max(int(hls_list_size) + 5, 20)
        display_target = f"GStreamer Direct Screen Capture -> HLS ({playlist_loc})"

        cmd.extend(v_pipeline)
        cmd.extend(["!", "queue", "!", "sink.video"])
        for src_tokens in active_audio_sources:
            cmd.extend(src_tokens)
        cmd.extend(a_mixer)
        cmd.extend(["!", "queue", "!", "sink.audio"])
        cmd.extend([
            "hlssink2", "name=sink",
            f"location={seg_loc}",
            f"playlist-location={playlist_loc}",
            f"target-duration={int(hls_segment_time)}",
            f"playlist-length={int(hls_list_size)}",
            f"max-files={max_files}",
        ])

    return GStreamerPlan(
        cmd=cmd,
        env=env,
        display_target=display_target,
        output_mode=output_mode,
    )
