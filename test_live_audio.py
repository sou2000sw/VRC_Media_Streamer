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
