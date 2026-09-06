# -*- coding: utf-8 -*-
"""タスク25: アプリ単位の音声取り込み（WASAPIプロセスループバック）"""
from unittest.mock import patch, MagicMock

from streamer_core import (
    StreamerCore, build_app_audio_input, build_audio_inputs,
    build_dshow_audio_inputs, start_app_audio_helper,
    get_app_audio_capture_cmd, _fmt_audio_volume,
)


# ---------------------------------------------------------------- 純粋関数

def test_build_app_audio_input():
    args = build_app_audio_input()
    assert args == ["-f", "s16le", "-ar", "48000", "-ac", "2",
                    "-thread_queue_size", "1024", "-i", "pipe:0"]


def test_build_audio_inputs_disabled_matches_legacy():
    """アプリ音声が無効なら、従来の dshow 経路と完全に同一でなければならない。"""
    for mic, loop in [("", ""), ("Mic A", ""), ("", "Loop B"), ("Mic A", "Loop B")]:
        assert build_audio_inputs(
            app_enabled=False, mic_device=mic, loopback_device=loop,
            mic_volume=0.9, loopback_volume=0.6, start_index=1
        ) == build_dshow_audio_inputs(
            mic_device=mic, loopback_device=loop,
            mic_volume=0.9, loopback_volume=0.6, start_index=1
        )


def test_build_audio_inputs_app_only():
    args, filt, amap = build_audio_inputs(app_enabled=True, app_volume=1.0, start_index=1)
    assert args == build_app_audio_input()
    # 単独なら amix を挟まない（無駄な遅延を乗せない）
    assert "amix" not in filt
    assert filt == "[1:a]volume=1.0[aout]"
    assert amap == "[aout]"


def test_build_audio_inputs_app_plus_mic():
    args, filt, amap = build_audio_inputs(
        app_enabled=True, app_volume=0.8, mic_device="Mic A",
        mic_volume=0.5, start_index=1)
    # アプリ音声が先頭(1)、dshow がその後(2)
    assert args[:10] == build_app_audio_input()
    assert args[10:] == ["-f", "dshow", "-thread_queue_size", "1024",
                         "-audio_buffer_size", "50", "-i", "audio=Mic A"]
    assert "[1:a]volume=0.8[aapp]" in filt
    assert "[2:a]volume=0.5[amic]" in filt
    assert "amix=inputs=2:duration=longest:dropout_transition=0[aout]" in filt
    assert amap == "[aout]"


def test_build_audio_inputs_all_three():
    args, filt, amap = build_audio_inputs(
        app_enabled=True, app_volume=1.0, mic_device="Mic A",
        loopback_device="Loop B", start_index=1)
    assert "[1:a]" in filt and "[2:a]" in filt and "[3:a]" in filt
    assert "amix=inputs=3" in filt
    assert args.count("-i") == 3
    assert amap == "[aout]"


def test_build_audio_inputs_start_index_shift():
    """start_index をずらしても採番が連番であること。"""
    _, filt, _ = build_audio_inputs(
        app_enabled=True, mic_device="Mic A", loopback_device="Loop B", start_index=5)
    assert "[5:a]" in filt and "[6:a]" in filt and "[7:a]" in filt


def test_app_volume_is_clamped():
    _, filt, _ = build_audio_inputs(app_enabled=True, app_volume=9.0, start_index=1)
    assert "volume=2.0" in filt
    _, filt2, _ = build_audio_inputs(app_enabled=True, app_volume=-3, start_index=1)
    assert "volume=0.0" in filt2
    assert _fmt_audio_volume("abc") == "1.0"


# ---------------------------------------------------------------- 補助exeの起動

def test_start_helper_returns_none_when_exe_missing():
    with patch("streamer_core.get_app_audio_capture_cmd", return_value=None):
        assert start_app_audio_helper(1234) is None


def test_start_helper_rejects_bad_pid():
    with patch("streamer_core.get_app_audio_capture_cmd", return_value="dummy.exe"):
        assert start_app_audio_helper(0) is None
        assert start_app_audio_helper(-5) is None
        assert start_app_audio_helper("abc") is None
        assert start_app_audio_helper(None) is None


def test_start_helper_builds_expected_command():
    fake = MagicMock()
    with patch("streamer_core.get_app_audio_capture_cmd",
               return_value="C:/x/app_audio_capture.exe"):
        with patch("streamer_core.subprocess.Popen", return_value=fake) as popen:
            proc = start_app_audio_helper(4321, mode="exclude", stats_sec=5)
    assert proc is fake
    cmd = popen.call_args[0][0]
    assert cmd[0] == "C:/x/app_audio_capture.exe"
    assert cmd[cmd.index("--pid") + 1] == "4321"
    assert cmd[cmd.index("--mode") + 1] == "exclude"
    assert cmd[cmd.index("--stats") + 1] == "5"


def test_start_helper_is_fail_soft_on_exception():
    with patch("streamer_core.get_app_audio_capture_cmd", return_value="dummy.exe"):
        with patch("streamer_core.subprocess.Popen", side_effect=OSError("boom")):
            assert start_app_audio_helper(1234) is None


def test_get_app_audio_capture_cmd_missing(tmp_path):
    with patch("streamer_core.LOCAL_APP_AUDIO_EXE", str(tmp_path / "nope1.exe")):
        with patch("streamer_core.DEV_APP_AUDIO_EXE", str(tmp_path / "nope2.exe")):
            assert get_app_audio_capture_cmd() is None


def test_get_app_audio_capture_cmd_found(tmp_path):
    exe = tmp_path / "app_audio_capture.exe"
    exe.write_bytes(b"MZ")
    with patch("streamer_core.LOCAL_APP_AUDIO_EXE", str(tmp_path / "nope.exe")):
        with patch("streamer_core.DEV_APP_AUDIO_EXE", str(exe)):
            assert get_app_audio_capture_cmd() == str(exe)


# ---------------------------------------------------------------- PID解決と設定

def _core():
    return StreamerCore(override_port=8971, override_enable_tunnel=False)


def test_resolve_pid_disabled():
    core = _core()
    core.config["live_audio_app_enabled"] = False
    assert core._resolve_app_audio_pid() is None


def test_resolve_pid_no_title():
    core = _core()
    core.config["live_audio_app_enabled"] = True
    core.config["live_audio_app_window_title"] = ""
    assert core._resolve_app_audio_pid() is None


def test_resolve_pid_window_gone():
    core = _core()
    core.config["live_audio_app_enabled"] = True
    core.config["live_audio_app_window_title"] = "存在しないウィンドウ"
    with patch("streamer_core.find_capture_window", return_value=None):
        assert core._resolve_app_audio_pid() is None


def test_resolve_pid_found():
    core = _core()
    core.config["live_audio_app_enabled"] = True
    core.config["live_audio_app_window_title"] = "Chrome"
    with patch("streamer_core.find_capture_window",
               return_value={"title": "Chrome", "pid": 777, "hwnd": 1}):
        assert core._resolve_app_audio_pid() == 777


def test_start_app_audio_capture_is_fail_soft_when_window_missing():
    """対象ウィンドウが無くても None を返すだけで、例外は投げない。"""
    core = _core()
    core.config["live_audio_app_enabled"] = True
    core.config["live_audio_app_window_title"] = "居ないウィンドウ"
    with patch("streamer_core.find_capture_window", return_value=None):
        assert core.start_app_audio_capture() is None


def test_set_live_audio_app_updates_config():
    core = _core()
    with patch.object(core, "save_config"):
        with patch.object(core, "request_stream_reload"):
            res = core.set_live_audio_app(enabled=True, window_title="Chrome",
                                          volume=0.5, mode="exclude")
    assert res["live_audio_app_enabled"] is True
    assert res["live_audio_app_window_title"] == "Chrome"
    assert res["live_audio_app_volume"] == 0.5
    assert res["live_audio_app_mode"] == "exclude"
    assert core.config["live_audio_app_enabled"] is True


def test_set_live_audio_app_clamps_and_ignores_bad_mode():
    core = _core()
    with patch.object(core, "save_config"):
        with patch.object(core, "request_stream_reload"):
            res = core.set_live_audio_app(volume=5.0, mode="不正な値")
    assert res["live_audio_app_volume"] == 2.0
    assert res["live_audio_app_mode"] == "include"


def test_reap_helper_kills_helper_when_sender_ends():
    core = _core()
    sender = MagicMock()
    helper = MagicMock()
    with patch("streamer_core.kill_proc") as kp:
        core.reap_app_audio_helper(sender, helper)
    sender.wait.assert_called_once()
    kp.assert_called_once_with(helper)


def test_reap_helper_noop_without_helper():
    core = _core()
    sender = MagicMock()
    with patch("streamer_core.kill_proc") as kp:
        core.reap_app_audio_helper(sender, None)
    kp.assert_not_called()
