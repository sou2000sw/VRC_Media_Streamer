# -*- coding: utf-8 -*-
import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

import streamer_core
from streamer_core import (
    DEFAULT_CONFIG, StreamerCore, build_dshow_audio_inputs,
    enumerate_dshow_audio_devices, is_loopback_candidate,
    parse_dshow_audio_devices_output
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SAMPLE_FFMPEG_DSHOW_OUTPUT = (
    '[in#0 @ 000001c2760f36c0] "HD Camera" (video)\n'
    '[in#0 @ 000001c2760f36c0]   Alternative name "@device_pnp_usb_vid_0408"\n'
    '[in#0 @ 000001c2760f36c0] "マイク (Virtual Desktop Audio)" (audio)\n'
    '[in#0 @ 000001c2760f36c0]   Alternative name "@device_cm_wave_0B46D71D"\n'
    '[in#0 @ 000001c2760f36c0] "What U Hear (Sound Blaster X5)" (audio)\n'
    '[in#0 @ 000001c2760f36c0]   Alternative name "@device_cm_wave_00DF85B4"\n'
    '[in#0 @ 000001c2760f36c0] "Microphone (3- Razer Seiren V3 Mini)" (audio)\n'
    '[in#0 @ 000001c2760f36c0]   Alternative name "@device_cm_wave_1E3B8FC9"\n'
    'Error opening input file dummy.\n'
)


def test_dshow_device_parser_utf8():
    raw_bytes = SAMPLE_FFMPEG_DSHOW_OUTPUT.encode("utf-8")
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"", raw_bytes)

    with patch("subprocess.Popen", return_value=mock_proc):
        devices = enumerate_dshow_audio_devices(use_cache=False)

    assert len(devices) == 3
    names = [d["name"] for d in devices]
    assert "HD Camera" not in names
    assert "マイク (Virtual Desktop Audio)" in names
    assert "What U Hear (Sound Blaster X5)" in names
    assert "Microphone (3- Razer Seiren V3 Mini)" in names

    dev0 = next(d for d in devices if "Virtual Desktop Audio" in d["name"])
    assert dev0["alt"] == "@device_cm_wave_0B46D71D"
    assert dev0["loopback_hint"] is True

    dev1 = next(d for d in devices if "Sound Blaster X5" in d["name"])
    assert dev1["alt"] == "@device_cm_wave_00DF85B4"
    assert dev1["loopback_hint"] is True

    dev2 = next(d for d in devices if "Razer" in d["name"])
    assert dev2["alt"] == "@device_cm_wave_1E3B8FC9"
    assert dev2["loopback_hint"] is False


def test_dshow_device_parser_cp932():
    raw_bytes = SAMPLE_FFMPEG_DSHOW_OUTPUT.encode("cp932")
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"", raw_bytes)

    with patch("subprocess.Popen", return_value=mock_proc):
        devices = enumerate_dshow_audio_devices(use_cache=False)

    assert len(devices) == 3
    assert any("マイク (Virtual Desktop Audio)" in d["name"] for d in devices)


def test_enumerate_dshow_audio_devices_exception_and_timeout():
    with patch("subprocess.Popen", side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=8)):
        res = enumerate_dshow_audio_devices(use_cache=False)
        assert res == []

    with patch("subprocess.Popen", side_effect=RuntimeError("Process error")):
        res = enumerate_dshow_audio_devices(use_cache=False)
        assert res == []


def test_build_dshow_audio_inputs_branches():
    # 0 devices
    args, filt, amap = build_dshow_audio_inputs(mic_device=None, loopback_device=None)
    assert args == []
    assert filt is None
    assert amap is None

    # 1 device
    args1, filt1, amap1 = build_dshow_audio_inputs(mic_device="Mic Test", loopback_device="", mic_volume=1.0)
    assert args1 == ["-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50", "-i", "audio=Mic Test"]
    assert filt1 is None
    assert amap1 == "1:a:0"

    args1_vol, filt1_vol, amap1_vol = build_dshow_audio_inputs(mic_device="Mic Test", loopback_device="", mic_volume=0.8)
    assert args1_vol == ["-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50", "-i", "audio=Mic Test"]
    assert filt1_vol == "[1:a]volume=0.8[aout]"
    assert amap1_vol == "[aout]"

    # 2 devices (mic first, loopback second)
    args2, filt2, amap2 = build_dshow_audio_inputs(
        mic_device="Mic Input",
        loopback_device="Loopback Input",
        mic_volume=0.9,
        loopback_volume=0.5,
        start_index=1
    )
    assert args2 == [
        "-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50", "-i", "audio=Mic Input",
        "-f", "dshow", "-thread_queue_size", "1024", "-audio_buffer_size", "50", "-i", "audio=Loopback Input"
    ]
    assert "[1:a]volume=0.9[amic]" in filt2
    assert "[2:a]volume=0.5[apc]" in filt2
    assert "[amic][apc]amix=inputs=2:duration=longest:dropout_transition=0[aout]" in filt2
    assert amap2 == "[aout]"

    # Volume clamping
    _, filt_clamp, _ = build_dshow_audio_inputs(mic_device="Mic Input", mic_volume=3.0)
    assert "volume=2.0" in filt_clamp


def test_play_live_audio_cmd_validation(tmp_path):
    core = StreamerCore(override_port=8998, override_enable_tunnel=False)
    core.config["live_audio_mic_device"] = "Mic Dev"
    core.config["live_audio_loopback_device"] = "Loop Dev"
    core.config["live_audio_mic_volume"] = 1.0
    core.config["live_audio_loopback_volume"] = 0.7
    core.config["overlay_clock_enabled"] = True
    core.config["overlay_clock_video"] = True

    captured_cmds = []

    def mock_popen(cmd, **kwargs):
        captured_cmds.append(cmd)
        proc = MagicMock()
        proc.poll.return_value = None
        return proc

    with patch("subprocess.Popen", side_effect=mock_popen), \
         patch.object(core, "ensure_stream_sink", return_value=True):
        stop_event = core.play_live_audio()
        assert stop_event is not None

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]

    # Verification rules
    assert "-shortest" not in cmd
    assert "-max_interleave_delta" in cmd
    idx_delta = cmd.index("-max_interleave_delta")
    assert cmd[idx_delta + 1] == "0"

    # With 2 devices + clock enabled: -vf NOT included, -filter_complex ONCE with clock & amix, -map [vout] present
    assert "-vf" not in cmd
    filter_complex_count = cmd.count("-filter_complex")
    assert filter_complex_count == 1
    fc_idx = cmd.index("-filter_complex")
    fc_val = cmd[fc_idx + 1]
    assert "[vout]" in fc_val
    assert "amix=inputs=2" in fc_val
    assert "-map" in cmd
    assert "[vout]" in cmd

    # 0 devices check -> returns None and sets status to error
    core.config["live_audio_mic_device"] = ""
    core.config["live_audio_loopback_device"] = ""
    res_none = core.play_live_audio()
    assert res_none is None
    assert core.status == "error"

    core.shutdown()


def test_set_playback_mode_live():
    core = StreamerCore(override_port=8997, override_enable_tunnel=False)
    res = core.set_playback_mode("live")
    assert res == "live"
    assert core.get_playback_mode() == "live"
    core.shutdown()


def test_live_audio_config_keys():
    expected_keys = {
        "live_audio_mic_device": "",
        "live_audio_loopback_device": "",
        "live_audio_mic_volume": 1.0,
        "live_audio_loopback_volume": 0.7,
        "live_audio_bitrate_kbps": 192,
    }
    for k, default_val in expected_keys.items():
        assert k in DEFAULT_CONFIG
        assert DEFAULT_CONFIG[k] == default_val

    dist_config_path = os.path.join(BASE_DIR, "config.dist.json")
    with open(dist_config_path, "r", encoding="utf-8") as f:
        dist_json = json.load(f)
    for k, default_val in expected_keys.items():
        assert k in dist_json
        assert dist_json[k] == default_val


def test_play_live_audio_aborts_when_standby_image_missing(tmp_path):
    """背景静止画が用意できないときは起動せず error を返す。

    generate_standby_image() は描画に失敗しても例外を出さずに進むことがあり、
    戻り値が None のまま os.path.abspath() に渡ると TypeError が
    queue_monitor_loop まで飛んでいた。
    """
    core = StreamerCore(override_port=8996, override_enable_tunnel=False)
    core.config["live_audio_mic_device"] = "Mic Dev"
    core.config["live_audio_loopback_device"] = ""

    with patch.object(core, "ensure_stream_sink", return_value=True), \
         patch.object(core, "generate_standby_image", return_value=None), \
         patch("subprocess.Popen") as popen:
        assert core.play_live_audio() is None
        assert core.status == "error"
        popen.assert_not_called()

    missing = os.path.join(str(tmp_path), "no_such_image.png")
    with patch.object(core, "ensure_stream_sink", return_value=True), \
         patch.object(core, "generate_standby_image", return_value=missing), \
         patch("subprocess.Popen") as popen:
        assert core.play_live_audio() is None
        popen.assert_not_called()

    core.shutdown()


# ============================================================
# タスク25: ライブ音声の配信画面（背景）をラジオと同じように選べる
# ============================================================

def _live_core():
    from streamer_core import StreamerCore
    return StreamerCore(override_port=8969, override_enable_tunnel=False)


def _run_live_audio(monkeypatch, core):
    """play_live_audio を実プロセスなしで走らせ、組み立てたコマンドを返す。"""
    import streamer_core as sc
    from unittest.mock import MagicMock
    captured = {}

    class _FakeProc:
        returncode = None
        stdout = None

        def poll(self):
            return None

    def _fake_popen(cmd, *a, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
    monkeypatch.setattr(core, "get_video_encoder", lambda: "libx264")
    monkeypatch.setattr(sc.subprocess, "Popen", _fake_popen)
    monkeypatch.setattr(core, "relay_stream_data", lambda *a, **k: None)
    monkeypatch.setattr(core, "watch_send_proc", lambda *a, **k: None)
    monkeypatch.setattr(core, "start_app_audio_capture", lambda: None)
    core.play_live_audio()
    return captured.get("cmd")


def test_set_live_audio_bg_source(monkeypatch):
    core = _live_core()
    try:
        monkeypatch.setattr(core, "save_config", lambda: None)
        monkeypatch.setattr(core, "request_stream_reload", lambda: None)
        assert core.set_live_audio_bg_source("slideshow") == "slideshow"
        assert core.set_live_audio_bg_source("standby") == "standby"
        # ラジオの "card" は流用しない（YouTubeのメタデータが元なので成立しない）
        core.set_live_audio_bg_source("slideshow")
        assert core.set_live_audio_bg_source("card") == "slideshow"
        assert core.set_live_audio_bg_source("でたらめ") == "slideshow"
    finally:
        core.shutdown()


def test_live_audio_uses_slideshow_when_selected(monkeypatch, tmp_path):
    """スライドショー指定かつ写真があるなら concat + stream_loop で送る。

    ★-re を付けてはいけない。付けると送出FFmpegが数秒で死に、アプリ音声が
      流れなくなる（実測: -re あり 0/12秒、-re なし 12/12秒）。
    """
    core = _live_core()
    try:
        imgs = []
        for name in ("a.jpg", "b.jpg"):
            f = tmp_path / name
            f.write_bytes(b"x")
            imgs.append(str(f))
        monkeypatch.setattr(core, "get_slideshow_images", lambda: imgs)
        monkeypatch.setattr(core, "get_image_for_playback",
                            lambda img, unique_id=None: img)
        core.config["live_audio_mic_device"] = "Mic A"
        core.config["live_audio_bg_source"] = "slideshow"
        core.config["image_auto_advance"] = True
        core.image_paused = False

        cmd = _run_live_audio(monkeypatch, core)
        assert cmd is not None
        joined = " ".join(str(c) for c in cmd)
        assert "concat" in joined, "スライドショーなのに concat が使われていない"
        assert "-stream_loop" in cmd, "巡回しない（1周で止まる）"
        assert "-re" not in cmd, "-re を付けると送出が死ぬ（0/12秒）"
    finally:
        core.shutdown()


def test_live_audio_falls_back_to_still_without_photos(monkeypatch):
    """スライドショー指定でも写真が無ければ静止画1枚に落ちる（配信は止めない）。"""
    core = _live_core()
    try:
        monkeypatch.setattr(core, "get_slideshow_images", lambda: [])
        core.config["live_audio_mic_device"] = "Mic A"
        core.config["live_audio_bg_source"] = "slideshow"
        core.config["image_auto_advance"] = True
        core.image_paused = False

        cmd = _run_live_audio(monkeypatch, core)
        assert cmd is not None, "写真が無いだけで配信が組み立てられていない"
        joined = " ".join(str(c) for c in cmd)
        assert "concat" not in joined
        assert "-loop" in cmd and "1" in cmd
    finally:
        core.shutdown()


def test_live_audio_default_is_standby(monkeypatch):
    """既定は待機画面。従来の挙動を変えない。"""
    core = _live_core()
    try:
        core.config["live_audio_mic_device"] = "Mic A"
        core.config["live_audio_bg_source"] = "standby"
        cmd = _run_live_audio(monkeypatch, core)
        assert cmd is not None
        assert "concat" not in " ".join(str(c) for c in cmd)
        assert "-loop" in cmd
    finally:
        core.shutdown()


def test_build_slideshow_manifest_advances_cursor(monkeypatch, tmp_path):
    """終わりのない配信（track_seconds=0）でも1枚ぶんカーソルが進む。"""
    core = _live_core()
    try:
        imgs = []
        for name in ("a.jpg", "b.jpg", "c.jpg"):
            f = tmp_path / name
            f.write_bytes(b"x")
            imgs.append(str(f))
        monkeypatch.setattr(core, "get_slideshow_images", lambda: imgs)
        monkeypatch.setattr(core, "get_image_for_playback",
                            lambda img, unique_id=None: img)
        core.slideshow_cursor = 0
        p1 = core.build_slideshow_manifest(track_seconds=0, label="Test",
                                           manifest_name="t_manifest.txt")
        assert p1 and os.path.exists(p1)
        assert core.slideshow_cursor == 1
        core.build_slideshow_manifest(track_seconds=0, label="Test",
                                      manifest_name="t_manifest.txt")
        assert core.slideshow_cursor == 2
    finally:
        core.shutdown()


def test_build_slideshow_manifest_without_photos(monkeypatch):
    core = _live_core()
    try:
        monkeypatch.setattr(core, "get_slideshow_images", lambda: [])
        assert core.build_slideshow_manifest(track_seconds=0) is None
    finally:
        core.shutdown()


def test_live_audio_stops_cleanly_when_no_audio_source(monkeypatch):
    """アプリ音声だけ有効で対象が見つからないとき、壊れたコマンドを渡さない。

    ★入口のガードは「設定上どれか有効か」しか見ない。いざ始める段で対象ウィンドウが
      消えていると音声入力がゼロになり、以前は "-map None" をFFmpegへ渡していた。
      何が悪いか分からないまま配信が失敗するので、理由を出して止める。
    """
    import streamer_core as sc
    core = _live_core()
    captured = {}

    class _FakeProc:
        returncode = None
        stdout = None

        def poll(self):
            return None

    def _fake_popen(cmd, *a, **kw):
        captured["cmd"] = cmd
        return _FakeProc()

    try:
        core.config["live_audio_mic_device"] = ""
        core.config["live_audio_loopback_device"] = ""
        core.config["live_audio_app_enabled"] = True
        core.config["live_audio_app_window_title"] = "居ないウィンドウ"

        monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
        monkeypatch.setattr(core, "get_video_encoder", lambda: "libx264")
        monkeypatch.setattr(sc.subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(core, "relay_stream_data", lambda *a, **k: None)
        monkeypatch.setattr(core, "watch_send_proc", lambda *a, **k: None)
        monkeypatch.setattr(sc, "find_capture_window", lambda title: None)

        res = core.play_live_audio()

        assert res is None, "音声ソースが無いのに配信を始めてしまっている"
        assert "cmd" not in captured, "壊れたコマンドをFFmpegへ渡している"
        assert core.status == "error"
        assert core.status_detail, "理由が利用者に伝わらない"
    finally:
        core.shutdown()
