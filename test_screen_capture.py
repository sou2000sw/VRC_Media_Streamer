# -*- coding: utf-8 -*-
import json
import os
from unittest.mock import patch, MagicMock

import pytest

import streamer_core
from streamer_core import (
    DEFAULT_CONFIG, StreamerCore, even_dimension,
    build_screen_capture_input, build_screen_video_filter,
    find_capture_window, clamp_window_capture_rect
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def test_even_dimension():
    assert even_dimension(1441) == 1440
    assert even_dimension(1121) == 1120
    assert even_dimension(1920) == 1920
    assert even_dimension(0) == 2
    assert even_dimension("abc") == 2


def test_build_screen_capture_input_display_default():
    args, needs_hwdownload = build_screen_capture_input(source_type="display", display_index=1, framerate=30, draw_mouse=True)
    assert needs_hwdownload is True
    assert "-f" in args and "lavfi" in args
    joined = " ".join(args)
    assert "ddagrab=output_idx=1:framerate=30:draw_mouse=true" in joined


def test_build_screen_capture_input_display_draw_mouse_false():
    args, needs_hwdownload = build_screen_capture_input(source_type="display", display_index=0, framerate=30, draw_mouse=False)
    assert needs_hwdownload is True
    joined = " ".join(args)
    assert "draw_mouse=false" in joined


def test_build_screen_capture_input_window_ddagrab():
    """ウィンドウ取り込みの既定は ddagrab の切り出し（速度のため）。

    ★gdigrab(BitBlt) は切り出しが大きいほど遅い。実測で 2568x1401 では
      実効23.7fps まで落ち、カクつきとして見えた。ddagrab は同じ範囲で29.5fps。
    """
    args, needs_hwdownload = build_screen_capture_input(
        source_type="window", window_title="メモ帳", framerate=30, draw_mouse=True,
        window_plan=("ddagrab", 1, 10, 20, 800, 600))
    assert needs_hwdownload is True
    joined = " ".join(args)
    assert "ddagrab=output_idx=1" in joined
    assert "video_size=800x600" in joined
    assert "offset_x=10" in joined and "offset_y=20" in joined
    assert "draw_mouse=true" in joined
    # ★回帰ガード: title= 経路へ戻したら落とす（GPU合成ウィンドウが真っ黒になる）
    assert not any(str(a).startswith("title=") for a in args)


def test_build_screen_capture_input_window_gdigrab_fallback():
    """ddagrab に載せられないときは合成済みデスクトップの切り出しへ退避する。"""
    args, needs_hwdownload = build_screen_capture_input(
        source_type="window", window_title="メモ帳", framerate=30, draw_mouse=False,
        window_plan=("gdigrab", 100, 50, 800, 600))
    assert needs_hwdownload is False
    assert args[args.index("-i") + 1] == "desktop"
    assert args[args.index("-offset_x") + 1] == "100"
    assert args[args.index("-video_size") + 1] == "800x600"
    assert args[args.index("-draw_mouse") + 1] == "0"
    assert not any(str(a).startswith("title=") for a in args)


def test_build_screen_capture_input_window_without_plan_falls_back():
    """取り込み方が決まらないウィンドウはディスプレイ取り込みへ落とす。"""
    args, needs_hwdownload = build_screen_capture_input(
        source_type="window", window_title="メモ帳", framerate=30, window_plan=None)
    assert needs_hwdownload is True
    assert "lavfi" in args
    assert not any(str(a).startswith("title=") for a in args)


def test_clamp_rect_to_monitor():
    """モニタ矩形でクランプし偶数寸法にする。

    ★ddagrab はその出力の内側しか切り出せない。実測でウィンドウ幅2568が
      モニタ幅2560を超え、オフセット -1 と併せて起動に失敗した。
    """
    from streamer_core import clamp_rect_to_monitor
    mon = {"left": -2560, "top": 1, "width": 2560, "height": 1440}
    assert clamp_rect_to_monitor(-2568, -7, 2576, 1408, mon) == (-2560, 1, 2560, 1400)
    assert clamp_rect_to_monitor(-2000, 100, 800, 600, mon) == (-2000, 100, 800, 600)


def test_clamp_window_capture_rect():
    """仮想デスクトップからはみ出した分を落とす。

    ★落とさないと ffmpeg が `extends outside window area` で起動しない。
      実測でウィンドウが (-2568, -7) と画面外へわずかに出ていた。
    """
    virt = (-2560, 0, 5120, 1441)
    # 左上が枠外へはみ出しているケース（実測値）
    assert clamp_window_capture_rect(-2568, -7, 2576, 1408, virt) == (-2560, 0, 2568, 1401)
    # 完全に内側なら素通し
    assert clamp_window_capture_rect(672, 296, 1216, 808, virt) == (672, 296, 1216, 808)
    # 右下がはみ出すケース
    assert clamp_window_capture_rect(2000, 1200, 1000, 1000, virt) == (2000, 1200, 560, 241)


def test_build_screen_capture_input_framerate_clamping():
    args0, _ = build_screen_capture_input(source_type="display", framerate=0)
    assert "framerate=30" in " ".join(args0)

    args999, _ = build_screen_capture_input(source_type="display", framerate=999)
    assert "framerate=30" in " ".join(args999)

    args_abc, _ = build_screen_capture_input(source_type="display", framerate="abc")
    assert "framerate=30" in " ".join(args_abc)


def test_build_screen_video_filter_needs_hwdownload():
    filt = build_screen_video_filter(needs_hwdownload=True, out_width=1920, out_height=1080)
    assert "hwdownload,format=bgra," in filt


def test_build_screen_video_filter_no_hwdownload():
    filt = build_screen_video_filter(needs_hwdownload=False, out_width=1920, out_height=1080)
    assert "hwdownload" not in filt


def test_build_screen_video_filter_structure():
    filt_true = build_screen_video_filter(needs_hwdownload=True, out_width=1920, out_height=1080)
    filt_false = build_screen_video_filter(needs_hwdownload=False, out_width=1920, out_height=1080)
    for filt in (filt_true, filt_false):
        assert filt.startswith("[0:v]")
        assert filt.endswith("[vout]")
        assert "force_original_aspect_ratio=decrease" in filt
        assert "pad=" in filt
        assert "format=yuv420p" in filt


def test_build_screen_video_filter_odd_dimensions():
    filt = build_screen_video_filter(needs_hwdownload=False, out_width=1921, out_height=1081)
    assert "scale=1920:1080" in filt
    assert "pad=1920:1080" in filt


def test_build_screen_video_filter_clock_filter():
    clock_f = "drawtext=text='12\\:00'"
    filt = build_screen_video_filter(needs_hwdownload=False, out_width=1920, out_height=1080, clock_filter=clock_f)
    assert "format=yuv420p," + clock_f + "[vout]" in filt


def test_playback_mode_screen():
    core = StreamerCore(override_port=8995, override_enable_tunnel=False)
    try:
        res = core.set_playback_mode("screen")
        assert res == "screen"
        assert core.get_playback_mode() == "screen"
    finally:
        core.shutdown()


def test_set_screen_capture_source_clamping():
    core = StreamerCore(override_port=8994, override_enable_tunnel=False)
    try:
        res = core.set_screen_capture_source(
            display_index=99,
            framerate=999,
            bitrate_kbps=1,
            width=99,
            source_type="bogus"
        )
        assert res["display_index"] == 7
        assert res["framerate"] == 60
        assert res["bitrate_kbps"] == 500
        assert res["width"] == 320
        assert res["source_type"] == "display"
    finally:
        core.shutdown()


def test_find_capture_window_exact_match():
    mock_windows = [
        {"title": "無題 - メモ帳", "width": 800, "height": 600, "pid": 1234, "duplicate": False},
        {"title": "Google Chrome", "width": 1024, "height": 768, "pid": 5678, "duplicate": False}
    ]
    with patch("streamer_core.enumerate_capture_windows", return_value=mock_windows):
        found = find_capture_window("無題 - メモ帳")
        assert found is not None
        assert found["title"] == "無題 - メモ帳"

        # 部分一致のタイトルは None
        found_partial = find_capture_window("メモ帳")
        assert found_partial is None


def test_ddagrab_output_mapping_requires_clear_winner(monkeypatch):
    """モニタ→ddagrab出力の対応付けは「次点の2倍以上離れている」ときだけ確定する。

    ★取り違えると別のモニタをそのまま配信する事故になる。実際に、絶対値で
      線を引いていた実装が diff=31.4 で誤った出力を選んだ。迷ったら None を返し、
      呼び出し側が gdigrab（絶対座標指定なので取り違えない）へ退避する。
    """
    mon = {"left": 0, "top": 0, "width": 2560, "height": 1440}

    def make(vals):
        def _probe(px, py, pw, ph, ox, oy, idx, timeout=15):
            return vals[idx] if idx < len(vals) else None
        return _probe

    # 明確な差がある -> 確定する
    streamer_core._ddagrab_output_map_cache.clear()
    monkeypatch.setattr(streamer_core, "_probe_monitor_vs_ddagrab", make([90.0, 20.0]))
    assert streamer_core.resolve_ddagrab_output_for_monitor(mon) == 1

    # 差が2倍未満（紛らわしい）-> 決めずに退避させる
    streamer_core._ddagrab_output_map_cache.clear()
    monkeypatch.setattr(streamer_core, "_probe_monitor_vs_ddagrab", make([55.0, 40.0]))
    assert streamer_core.resolve_ddagrab_output_for_monitor(mon) is None

    # 出力が1つしかなければ、比べる相手がいないので確定してよい
    streamer_core._ddagrab_output_map_cache.clear()
    monkeypatch.setattr(streamer_core, "_probe_monitor_vs_ddagrab", make([40.0]))
    assert streamer_core.resolve_ddagrab_output_for_monitor(mon) == 0

    # 一度決まったらモニタ単位で覚える（毎回プローブしない）
    streamer_core._ddagrab_output_map_cache.clear()
    monkeypatch.setattr(streamer_core, "_probe_monitor_vs_ddagrab", make([90.0, 20.0]))
    assert streamer_core.resolve_ddagrab_output_for_monitor(mon) == 1
    monkeypatch.setattr(streamer_core, "_probe_monitor_vs_ddagrab", make([20.0, 90.0]))
    assert streamer_core.resolve_ddagrab_output_for_monitor(mon) == 1


def test_screen_capture_always_has_audio_track(monkeypatch):
    """音声デバイス未設定でも**無音トラックを必ず載せる**。

    ★映像だけのストリームは HLS(-c copy) では再生できるのに、
      RTMP/FLV 経由（TopazChat -> VRChat/AVPro）でカクついて見える。
      実機で「HLSモードだと滑らか、TopazChatだとガタつく」という形で出た。
      待機画面・ラジオなど他モードは元から anullsrc を入れており、
      画面共有だけが音声トラック無しを送る唯一の例外だった。
    """
    core = StreamerCore(override_port=8993, override_enable_tunnel=False)
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
        core.set_live_audio_devices(mic_device="", loopback_device="")
        core.set_screen_capture_source(source_type="display", display_index=0, framerate=30)
        monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
        monkeypatch.setattr(core, "get_video_encoder", lambda: "libx264")
        monkeypatch.setattr(streamer_core.subprocess, "Popen", _fake_popen)
        monkeypatch.setattr(core, "relay_stream_data", lambda *a, **k: None)
        monkeypatch.setattr(core, "watch_send_proc", lambda *a, **k: None)

        core.play_screen_capture()
        cmd = captured.get("cmd")
        assert cmd is not None, "送出プロセスが組み立てられていない"
        joined = " ".join(str(c) for c in cmd)

        # ★音声を捨てていないこと
        assert "-an" not in cmd, "映像のみのストリームを送っている（RTMP経路で再生が乱れる）"
        assert "anullsrc" in joined, "無音トラックが入っていない"
        assert "-c:a" in cmd and "aac" in cmd, "音声コーデックが指定されていない"
    finally:
        core.shutdown()
