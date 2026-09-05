# -*- coding: utf-8 -*-
import json
import os
from unittest.mock import patch, MagicMock

import pytest

import streamer_core
from streamer_core import (
    DEFAULT_CONFIG, StreamerCore, even_dimension,
    build_screen_capture_input, build_screen_video_filter,
    find_capture_window
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


def test_build_screen_capture_input_window():
    args, needs_hwdownload = build_screen_capture_input(source_type="window", window_title="メモ帳", framerate=30, draw_mouse=True)
    assert needs_hwdownload is False
    assert "-f" in args and "gdigrab" in args
    assert "-draw_mouse" in args
    idx_dm = args.index("-draw_mouse")
    assert args[idx_dm + 1] == "1"
    assert "-i" in args
    idx_i = args.index("-i")
    assert args[idx_i + 1] == "title=メモ帳"

    # draw_mouse = False -> "0"
    args0, _ = build_screen_capture_input(source_type="window", window_title="メモ帳", framerate=30, draw_mouse=False)
    idx_dm0 = args0.index("-draw_mouse")
    assert args0[idx_dm0 + 1] == "0"


def test_build_screen_capture_input_window_empty_title_fallback():
    args, needs_hwdownload = build_screen_capture_input(source_type="window", window_title="", framerate=30, draw_mouse=True)
    assert needs_hwdownload is True
    assert "-f" in args and "lavfi" in args


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
