# -*- coding: utf-8 -*-
"""Unit tests for GStreamer backend module and StreamerCore integration."""

import os
import sys
import subprocess
import threading
from unittest.mock import MagicMock, patch
import pytest

import gstreamer_backend
from gstreamer_backend import (
    get_gstreamer_runtime_dir,
    get_gstreamer_env,
    validate_gstreamer_runtime,
    clear_validation_cache,
    escape_gst_prop_string,
    redact_rtmp_url,
    redact_gstreamer_log,
    build_gstreamer_screen_capture_plan,
    get_gst_launch_path,
    get_gst_inspect_path,
    resolve_gstreamer_binary,
)
import streamer_core
from streamer_core import StreamerCore, DEFAULT_CONFIG


def test_escape_gst_prop_string():
    assert escape_gst_prop_string("Microphone") == '"Microphone"'
    assert escape_gst_prop_string('マイク (Realtek)') == '"マイク (Realtek)"'
    assert escape_gst_prop_string('Device "With" Quotes') == '"Device \\"With\\" Quotes"'
    assert escape_gst_prop_string('C:\\Path\\To\\Device') == '"C:\\\\Path\\\\To\\\\Device"'
    assert escape_gst_prop_string(None) == '""'


def test_redact_rtmp_url():
    assert redact_rtmp_url("rtmp://topaz.chat/live/mysecretkey123") == "rtmp://topaz.chat/live/***`".rstrip("`")
    assert redact_rtmp_url("rtmp://topaz.chat/live/mysecretkey123") == "rtmp://topaz.chat/live/*** "[:-1]
    assert "mysecretkey123" not in redact_rtmp_url("rtmp://topaz.chat/live/mysecretkey123")
    assert redact_rtmp_url("") == ""
    assert redact_rtmp_url("invalid_url") == "[REDACTED]"


def test_redact_gstreamer_log_preserves_diagnostic_and_masks_url():
    line = "ERROR: failed to open rtmp://topaz.chat/live/secret-key"
    redacted = redact_gstreamer_log(line)
    assert redacted.startswith("ERROR: failed to open ")
    assert "secret-key" not in redacted
    assert redacted.endswith("rtmp://topaz.chat/live/***")
    assert redact_gstreamer_log("WARNING: device was removed") == "WARNING: device was removed"


def test_get_gstreamer_runtime_dir_resolution(tmp_path, monkeypatch):
    custom_dir = tmp_path / "custom_gst"
    bin_dir = custom_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "gst-launch-1.0.exe").touch()

    assert get_gstreamer_runtime_dir(str(custom_dir)) == str(custom_dir)

    # When no candidate directory exists
    monkeypatch.setattr(os.path, "isdir", lambda p: False)
    assert get_gstreamer_runtime_dir(str(tmp_path / "nonexistent")) is None


def test_gstreamer_executable_resolver_prefers_real_binary_over_wrapper(tmp_path):
    """Asserts that executable resolvers prefer gstreamer_cli/bin/ over root bin/ to avoid wrapper process orphans."""
    rt_dir = tmp_path / "gst_runtime"
    root_bin = rt_dir / "bin"
    cli_bin = rt_dir / "gstreamer_cli" / "bin"
    root_bin.mkdir(parents=True)
    cli_bin.mkdir(parents=True)

    # Touch wrapper executables in root bin
    (root_bin / "gst-launch-1.0.exe").touch()
    (root_bin / "gst-inspect-1.0.exe").touch()

    # Touch real binary executables in gstreamer_cli/bin
    real_launch = cli_bin / "gst-launch-1.0.exe"
    real_inspect = cli_bin / "gst-inspect-1.0.exe"
    real_launch.touch()
    real_inspect.touch()

    resolved_launch = get_gst_launch_path(str(rt_dir))
    resolved_inspect = get_gst_inspect_path(str(rt_dir))

    assert resolved_launch == os.path.abspath(str(real_launch))
    assert resolved_inspect == os.path.abspath(str(real_inspect))
    assert "gstreamer_cli" in resolved_launch

    # Assert GStreamerPlan uses the real executable in cmd[0]
    plan = build_gstreamer_screen_capture_plan(runtime_dir=str(rt_dir))
    assert plan.cmd[0] == os.path.abspath(str(real_launch))
    assert "gstreamer_cli" in plan.cmd[0]

    # Test fallback to root bin when gstreamer_cli is not present
    real_launch.unlink()
    real_inspect.unlink()

    fallback_launch = get_gst_launch_path(str(rt_dir))
    fallback_inspect = get_gst_inspect_path(str(rt_dir))

    assert fallback_launch == os.path.abspath(str(root_bin / "gst-launch-1.0.exe"))
    assert fallback_inspect == os.path.abspath(str(root_bin / "gst-inspect-1.0.exe"))
    assert "gstreamer_cli" not in fallback_launch


def test_get_gstreamer_env_construction(tmp_path):
    fake_env = {"PATH": "C:\\fake\\bin", "GST_PLUGIN_PATH": "C:\\fake\\lib"}
    fake_mod = MagicMock()
    fake_mod.gstreamer_env.return_value = (fake_env, "C:\\fake\\bin")

    orig_env = dict(os.environ)
    with patch.dict(sys.modules, {"gstreamer_libs": fake_mod}):
        env = get_gstreamer_env(str(tmp_path))
        assert env == fake_env
        assert os.environ == orig_env


def test_validate_gstreamer_runtime_and_caching(tmp_path, monkeypatch):
    clear_validation_cache()

    rt_dir = tmp_path / "gst_rt"
    bin_dir = rt_dir / "bin"
    bin_dir.mkdir(parents=True)

    ok, err = validate_gstreamer_runtime(str(rt_dir))
    assert ok is False
    assert "Missing gst-launch-1.0.exe" in err

    (bin_dir / "gst-launch-1.0.exe").touch()
    (bin_dir / "gst-inspect-1.0.exe").touch()

    clear_validation_cache()
    fake_env = {"PATH": "C:\\fake\\bin"}
    monkeypatch.setattr(gstreamer_backend, "get_gstreamer_env", lambda d: fake_env)

    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = b"d3d11screencapturesrc d3d11convert"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: mock_run)

    ok, err = validate_gstreamer_runtime(str(rt_dir))
    assert ok is False
    assert "Missing required GStreamer elements" in err

    clear_validation_cache()
    all_elems = " ".join(gstreamer_backend.REQUIRED_GSTREAMER_ELEMENTS)
    mock_run.stdout = all_elems.encode("utf-8")

    ok, err = validate_gstreamer_runtime(str(rt_dir))
    assert ok is True
    assert err == "OK"
    assert validate_gstreamer_runtime(str(rt_dir)) == (True, "OK")


def test_argv_token_packing_and_caps_structure():
    """Asserts that element names and properties are emitted as separate argv tokens,

    -q and -e flags are present, and caps strings are single no-whitespace tokens.
    """
    plan = build_gstreamer_screen_capture_plan(
        runtime_dir="C:/gst",
        source_type="display",
        display_index=0,
        width=1920,
        height=1080,
        fps=30,
        bitrate_kbps=4000,
        output_mode="hls",
        hls_dir="C:/tmp/hls",
    )
    cmd = plan.cmd
    assert cmd[0].endswith("gst-launch-1.0.exe")
    assert cmd[1] == "-q"
    assert cmd[2] == "-e"

    # Element names and properties must be separate tokens
    assert "d3d11screencapturesrc" in cmd
    assert "monitor-index=0" in cmd
    assert "hlssink2" in cmd
    assert "name=sink" in cmd

    # Assert no token packs element name together with property string
    invalid_packed_prefixes = ["d3d11screencapturesrc ", "hlssink2 ", "wasapi2src ", "flvmux "]
    for token in cmd:
        for prefix in invalid_packed_prefixes:
            assert not token.startswith(prefix), f"Token '{token}' has packed element+property!"

    # Assert caps tokens contain no whitespace
    caps_tokens = [t for t in cmd if t.startswith("video/x-raw") or t.startswith("caps=audio/x-raw")]
    assert len(caps_tokens) > 0
    for caps in caps_tokens:
        assert not any(c.isspace() for c in caps), f"Caps token '{caps}' contains whitespace!"


def test_rtmp_output_mode_mapping_and_bitrate(monkeypatch, tmp_path):
    """Asserts StreamerCore maps topaz/generic_rtmp to output_mode='rtmp' and uses rtmp_video_bitrate_kbps."""
    core = StreamerCore(override_port=8991, override_enable_tunnel=False)
    try:
        core.config["screen_capture_backend"] = "gstreamer"
        core.config["rtmp_output_mode"] = "topaz"
        core.config["rtmp_video_bitrate_kbps"] = 3500
        core.config["screen_capture_bitrate_kbps"] = 5000

        monkeypatch.setattr(core, "is_gstreamer_available", lambda **k: True)
        monkeypatch.setattr(streamer_core, "get_gstreamer_runtime_dir", lambda *a: str(tmp_path))
        monkeypatch.setattr(streamer_core, "validate_gstreamer_runtime", lambda d: (True, "OK"))
        monkeypatch.setattr(core, "get_rtmp_publish_url", lambda m: "rtmp://topaz.chat/live/key123")
        monkeypatch.setattr(core, "probe_rtmp_endpoint", lambda u: (True, ""))

        captured_kwargs = {}

        def fake_build_plan(**kwargs):
            captured_kwargs.update(kwargs)
            return gstreamer_backend.GStreamerPlan(
                cmd=["gst-launch-1.0.exe", "-q", "-e"],
                env={},
                display_target="Topaz RTMP",
                output_mode=kwargs.get("output_mode", "hls"),
            )

        fake_proc = MagicMock()
        fake_proc.stderr = MagicMock()
        fake_proc.stderr.readline.return_value = b""
        fake_proc.poll.return_value = None

        monkeypatch.setattr(streamer_core, "build_gstreamer_screen_capture_plan", fake_build_plan)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: fake_proc)

        stop_event = core.play_screen_capture()
        assert stop_event is not None
        assert captured_kwargs.get("output_mode") == "rtmp"
        assert captured_kwargs.get("bitrate_kbps") == 3500
    finally:
        core.shutdown()


def test_real_fallback_dispatch_to_ffmpeg(monkeypatch):
    """Asserts that when GStreamer fails preflight, play_screen_capture executes real FFmpeg path."""
    core = StreamerCore(override_port=8992, override_enable_tunnel=False)
    popen_calls = []

    class FakeFFmpegProc:
        returncode = None
        stdin = MagicMock()
        stderr = MagicMock()
        stderr.readline.return_value = b""
        def poll(self): return None
        def wait(self, timeout=None): return 0

    def fake_popen(cmd, **kwargs):
        popen_calls.append(cmd)
        return FakeFFmpegProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(streamer_core, "get_gstreamer_runtime_dir", lambda *a: None)
    monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
    monkeypatch.setattr(streamer_core, "get_ffmpeg_cmd", lambda: "ffmpeg_mock_bin")

    try:
        core.config["screen_capture_backend"] = "gstreamer"
        res = core.play_screen_capture()
        assert res is not None
        assert core.active_screen_capture_backend == "ffmpeg"
        assert core.gstreamer_fallback_reason == "GStreamer runtime directory not found"
        # Assert FFmpeg command was actually launched by fallback
        assert len(popen_calls) > 0
        assert popen_calls[0][0] == "ffmpeg_mock_bin"
    finally:
        core.shutdown()


def test_watcher_process_ownership_guarding(monkeypatch, tmp_path):
    """An old process cannot clear a newer owner, but normal cleanup can release."""
    core = StreamerCore(override_port=8993, override_enable_tunnel=False)
    try:
        p1 = object()
        p2 = object()
        core._direct_capture_active = True
        core.send_proc = p2
        assert core._release_gstreamer_direct_state(p1) is False
        assert core._direct_capture_active is True

        core.send_proc = None
        assert core._release_gstreamer_direct_state(p1) is True
        assert core._direct_capture_active is False
    finally:
        core.shutdown()


def test_is_gstreamer_available_non_blocking_status(monkeypatch, tmp_path):
    """Asserts is_gstreamer_available(validate=False) checks dir without running validate_gstreamer_runtime."""
    core = StreamerCore(override_port=8994, override_enable_tunnel=False)
    try:
        validate_calls = []

        fake_dir = tmp_path / "gst"
        bin_dir = fake_dir / "bin"
        bin_dir.mkdir(parents=True)
        (bin_dir / "gst-launch-1.0.exe").touch()

        monkeypatch.setattr(streamer_core, "get_gstreamer_runtime_dir", lambda *a: str(fake_dir))

        def fake_validate(d):
            validate_calls.append(d)
            return (True, "OK")

        monkeypatch.setattr(streamer_core, "validate_gstreamer_runtime", fake_validate)

        avail = core.is_gstreamer_available(validate=False)
        assert avail is True
        assert len(validate_calls) == 0, "validate_gstreamer_runtime was called on status path!"

        avail_val = core.is_gstreamer_available(validate=True)
        assert avail_val is True
        assert len(validate_calls) == 1, "validate_gstreamer_runtime was NOT called when validate=True!"
    finally:
        core.shutdown()


def test_build_runtime_source_resolution_and_version_name(monkeypatch, tmp_path):
    import build_exe
    import version

    assert "gst" in version.APP_VERSION

    fake_gst = tmp_path / "fake_gst"
    bin_dir = fake_gst / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "gst-launch-1.0.exe").touch()
    (bin_dir / "gst-inspect-1.0.exe").touch()

    monkeypatch.setattr(sys, "argv", ["build_exe.py", "--gstreamer-root", str(fake_gst)])
    monkeypatch.setenv("VRC_MEDIA_STREAMER_GSTREAMER_ROOT", "")
    resolved = build_exe.resolve_gstreamer_build_source()
    assert resolved == str(fake_gst)

    monkeypatch.setattr(sys, "argv", ["build_exe.py"])
    monkeypatch.setenv("VRC_MEDIA_STREAMER_GSTREAMER_ROOT", str(fake_gst))
    resolved_env = build_exe.resolve_gstreamer_build_source()
    assert resolved_env == str(fake_gst)
