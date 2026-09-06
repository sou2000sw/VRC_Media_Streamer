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
    # ★親PIDを必ず渡す。渡さないと本体を強制終了したとき補助exeが残り、
    #   音声を取り込み続ける。
    import os as _os
    assert cmd[cmd.index("--parent-pid") + 1] == str(_os.getpid())


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


# ---------------------------------------------------------------- 配線（結合）

def _fake_helper():
    """補助exeの代役。stdout は「これが子プロセスへ渡ったか」を見るための目印。"""
    helper = MagicMock()
    helper.stdout = MagicMock()
    return helper


def _run_screen_capture(monkeypatch, core, helper):
    """play_screen_capture を実プロセスなしで走らせ、組み立てられたコマンドを返す。"""
    import streamer_core as sc
    captured = {}

    class _FakeProc:
        returncode = None
        stdout = None

        def poll(self):
            return None

    def _fake_popen(cmd, *a, **kw):
        captured["cmd"] = cmd
        captured["stdin"] = kw.get("stdin")
        return _FakeProc()

    monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
    monkeypatch.setattr(core, "get_video_encoder", lambda: "libx264")
    monkeypatch.setattr(sc.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(core, "relay_stream_data", lambda *a, **k: None)
    monkeypatch.setattr(core, "watch_send_proc", lambda *a, **k: None)
    monkeypatch.setattr(core, "reap_app_audio_helper", lambda *a, **k: None)
    monkeypatch.setattr(core, "start_app_audio_capture", lambda: helper)
    core.play_screen_capture()
    return captured


def test_screen_capture_feeds_app_audio_through_stdin(monkeypatch):
    """アプリ音声が有効なら、生PCM入力が入り、補助exeの stdout が子の stdin になる。"""
    core = _core()
    helper = _fake_helper()
    try:
        core.config["live_audio_mic_device"] = ""
        core.config["live_audio_loopback_device"] = ""
        core.config["screen_capture_source_type"] = "display"
        core.config["screen_capture_display_index"] = 0
        cap = _run_screen_capture(monkeypatch, core, helper)

        cmd = cap.get("cmd")
        assert cmd is not None, "送出プロセスが組み立てられていない"
        joined = " ".join(str(c) for c in cmd)
        assert "s16le" in joined, "アプリ音声の生PCM入力が入っていない"
        assert "pipe:0" in joined, "stdin から読む指定になっていない"
        # 無音トラックで埋められていないこと（アプリ音声が本物の音声トラック）
        assert "anullsrc" not in joined
        assert cap.get("stdin") is helper.stdout, "補助exeの stdout が子の stdin に渡っていない"
        helper.stdout.close.assert_called_once()
    finally:
        core.shutdown()


def test_screen_capture_falls_back_when_helper_unavailable(monkeypatch):
    """補助exeが使えないときは従来経路へ落ち、配信は止まらない。"""
    core = _core()
    try:
        core.config["live_audio_mic_device"] = ""
        core.config["live_audio_loopback_device"] = ""
        core.config["screen_capture_source_type"] = "display"
        core.config["screen_capture_display_index"] = 0
        cap = _run_screen_capture(monkeypatch, core, None)

        cmd = cap.get("cmd")
        assert cmd is not None, "補助exeが無いと配信が組み立てられていない（fail-soft でない）"
        joined = " ".join(str(c) for c in cmd)
        assert "pipe:0" not in joined, "補助exeが無いのに stdin から読もうとしている（無音で固まる）"
        assert "anullsrc" in joined, "音声トラックが無い（RTMP経路でカクつく）"
    finally:
        core.shutdown()
