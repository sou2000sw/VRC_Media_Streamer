# -*- coding: utf-8 -*-
"""ハードウェアエンコード（NVENC / QSV / AMF）対応の回帰テスト。タスク18。

固定したいのは4点:

1. **libx264 の引数を変えない**。preset / tune / level の値は過去の画質実測
   （CHANGELOG 2026-08-30）で決まったもので、「共通化のついで」に動かしてはいけない。
2. **x264の方言をHWエンコーダーへ渡さない**。★実測: `-preset ultrafast` を
   h264_nvenc に渡すと "Unable to parse preset option value" で起動できない。
   共通部分に足し込む実装は、HW選択時に配信不能を意味する。
3. **`-level 3.1` をそのまま流用しない**。★実測: NVENC は 1080p で level 3.1 を
   拒否する（"Invalid Level"）。libx264 は黙認するので、共有すると
   「x264では動くのにNVENCだけ起動しない」になる。
4. **使えないエンコーダーは選ばない**。`ffmpeg -encoders` は GPU が無くても
   h264_nvenc / h264_qsv / h264_amf を列挙する。一覧ではなく実エンコードで判定し、
   駄目なら libx264 へ退避すること（配信を止めない）。
"""

import io
import json
import os

import pytest

import streamer_core
from streamer_core import build_video_encoder_opts, resolve_video_encoder

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _pairs(opts):
    """['-a','1','-b'] を {'-a': '1', '-b': True} に。順序差で落ちないよう比較用に正規化。"""
    out = {}
    i = 0
    while i < len(opts):
        key = opts[i]
        if i + 1 < len(opts) and not str(opts[i + 1]).startswith("-"):
            out[key] = opts[i + 1]
            i += 2
        else:
            out[key] = True
            i += 1
    return out


# --------------------------------------------------------------------------
# 1. 既定値と設定
# --------------------------------------------------------------------------

def test_default_is_auto():
    assert streamer_core.DEFAULT_CONFIG["video_encoder"] == "auto"


def test_dist_config_ships_the_key():
    with io.open(os.path.join(BASE_DIR, "config.dist.json"), encoding="utf-8") as f:
        assert json.load(f)["video_encoder"] == "auto"


def test_unknown_value_falls_back_to_auto_not_crash():
    """設定ファイルを手で壊されても落ちないこと。"""
    assert resolve_video_encoder("h264_totallybogus") in streamer_core.VIDEO_ENCODERS
    assert resolve_video_encoder("") in streamer_core.VIDEO_ENCODERS
    assert resolve_video_encoder(None) in streamer_core.VIDEO_ENCODERS


# --------------------------------------------------------------------------
# 2. libx264 の引数を変えていないこと
# --------------------------------------------------------------------------

def test_libx264_video_path_args_are_unchanged():
    """動画の再エンコード経路（2500k / baseline / ultrafast）。"""
    got = build_video_encoder_opts("libx264", v_kbps=2500, max_kbps=3000, buf_kbps=2000,
                                   h264_profile="baseline", bf_zero=False)
    assert got == [
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-level", "3.1", "-pix_fmt", "yuv420p",
        "-b:v", "2500k", "-maxrate", "3000k", "-bufsize", "2000k",
    ]


def test_libx264_still_path_args_are_unchanged():
    """静止画ループ（待機画面・写真 / 1500k@30fps）。順序は問わないが内容は同一。"""
    got = _pairs(build_video_encoder_opts(
        "libx264", v_kbps=1500, max_kbps=1500, buf_kbps=1000,
        h264_profile="baseline", sc_threshold_zero=True, gop_frames=30, fps=30))
    expected = _pairs([
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-profile:v", "baseline", "-level", "3.1", "-bf", "0",
        "-g", "30", "-keyint_min", "30", "-sc_threshold", "0",
        "-pix_fmt", "yuv420p", "-r", "30",
        "-b:v", "1500k", "-maxrate", "1500k", "-bufsize", "1000k",
    ])
    assert got == expected


def test_libx264_rtmp_sink_args_are_unchanged():
    """RTMP送出（veryfast / main）。★-tune zerolatency を付けないこと。

    2026-08-30 の実測で、同じ1500kbpsで SSIM 0.9751→0.9806 と明確に画質を落とすと
    分かって外した経緯がある。共通化で戻さないよう固定する。
    """
    got = _pairs(build_video_encoder_opts(
        "libx264", v_kbps=1500, max_kbps=1500, buf_kbps=3000,
        h264_profile="main", sw_preset="veryfast", sw_tune=None, level=None,
        bf_zero=False, sc_threshold_zero=True, gop_frames="60"))
    assert "-tune" not in got, "RTMP送出に -tune を戻している"
    assert "-level" not in got
    assert got["-preset"] == "veryfast"
    assert got["-profile:v"] == "main"
    assert got["-sc_threshold"] == "0"
    assert got["-g"] == "60" and got["-keyint_min"] == "60"


def test_radio_path_stays_on_libx264():
    """ラジオ（2fps / 200k）は元から極小負荷。HW化の対象にしない。"""
    with io.open(os.path.join(BASE_DIR, "streamer_core.py"), encoding="utf-8") as f:
        src = f.read()
    _, _, tail = src.partition("def play_radio(")
    head = tail[:tail.index("def ", 100)] if "def " in tail[100:] else tail
    assert '"-c:v", "libx264",' in head, "ラジオ経路が libx264 のリテラルでなくなっている"


# --------------------------------------------------------------------------
# 3. HWエンコーダーへ x264 の方言を渡さないこと
# --------------------------------------------------------------------------

@pytest.mark.parametrize("encoder", ["h264_nvenc", "h264_qsv", "h264_amf"])
def test_hw_encoders_never_get_x264_only_options(encoder):
    opts = build_video_encoder_opts(encoder, v_kbps=2500, max_kbps=3000, buf_kbps=2000,
                                    sc_threshold_zero=True)
    text = " ".join(str(o) for o in opts)
    # ultrafast / zerolatency は x264 にしか無い綴り。★実測: NVENC に渡すと
    # "Unable to parse preset option value ultrafast" で起動できない。
    # （veryfast は QSV では正当なプリセット名なので、ここでは禁じない）
    assert "ultrafast" not in text, "x264のpresetがHWエンコーダーへ漏れている（起動不能になる）"
    assert "zerolatency" not in text, "x264の-tuneがHWエンコーダーへ漏れている"
    if encoder in ("h264_nvenc", "h264_amf"):
        assert "veryfast" not in text
    assert "-sc_threshold" not in opts, "-sc_threshold は libx264 専用"
    assert opts[0] == "-c:v" and opts[1] == encoder


@pytest.mark.parametrize("encoder", ["h264_nvenc", "h264_qsv", "h264_amf"])
def test_hw_encoders_do_not_request_level_3_1(encoder):
    """★実測: NVENC は 1080p で level 3.1 を拒否する（libx264 は黙認する）。"""
    opts = build_video_encoder_opts(encoder, v_kbps=2500, max_kbps=3000, buf_kbps=2000,
                                    level="3.1")
    assert _pairs(opts).get("-level") == "4.1"


def test_amf_uses_its_own_profile_constant():
    """★実測: AMF に "baseline" を渡すと定数として解釈できず起動しない。"""
    opts = _pairs(build_video_encoder_opts("h264_amf", v_kbps=2500, max_kbps=3000,
                                           buf_kbps=2000, h264_profile="baseline"))
    assert opts["-profile:v"] == "constrained_baseline"


def test_bitrates_are_carried_through():
    for enc in ("libx264", "h264_nvenc", "h264_qsv", "h264_amf"):
        opts = _pairs(build_video_encoder_opts(enc, v_kbps=1234, max_kbps=2345, buf_kbps=987))
        assert opts["-b:v"] == "1234k"
        assert opts["-maxrate"] == "2345k"
        assert opts["-bufsize"] == "987k"


# --------------------------------------------------------------------------
# 4. 可否判定は「一覧」ではなく「実際に動くか」
# --------------------------------------------------------------------------

def test_probe_runs_a_real_encode_not_just_a_listing():
    """`ffmpeg -encoders` の一覧を見るだけの実装に戻さないこと。

    一覧は GPU が無くても3種すべてを載せるため、それを信じると
    「配信を始めた瞬間に落ちる」設定を選んでしまう。
    """
    with io.open(os.path.join(BASE_DIR, "streamer_core.py"), encoding="utf-8") as f:
        src = f.read()
    _, _, tail = src.partition("def probe_video_encoder(")
    body = tail[:tail.index("def resolve_video_encoder")]
    assert '"-encoders"' not in body, "一覧（ffmpeg -encoders）だけで判定している"
    assert "lavfi" in body and "testsrc2" in body, "実際にエンコードして確かめていない"
    assert "build_video_encoder_opts" in body, "本番と同じ引数で試していない"
    assert "returncode" in body, "終了コードで判定していない"


def test_unusable_encoder_falls_back_to_libx264(monkeypatch):
    monkeypatch.setattr(streamer_core, "probe_video_encoder", lambda enc, timeout=20: False)
    assert resolve_video_encoder("h264_nvenc") == "libx264"
    assert resolve_video_encoder("auto") == "libx264"


def test_auto_prefers_the_first_working_encoder(monkeypatch):
    monkeypatch.setattr(streamer_core, "probe_video_encoder",
                        lambda enc, timeout=20: enc == "h264_amf")
    assert resolve_video_encoder("auto") == "h264_amf"


def test_libx264_is_never_probed():
    """同梱ビルドの必須エンコーダー。ここでプロセスを起動する必要はない。"""
    assert streamer_core.probe_video_encoder("libx264") is True


# --------------------------------------------------------------------------
# 5. 状態が見えること
# --------------------------------------------------------------------------

def test_status_exposes_requested_and_active(monkeypatch):
    """退避したことが利用者から見えるよう、設定値と実動作の両方を出すこと。"""
    monkeypatch.setattr(streamer_core, "probe_video_encoder", lambda enc, timeout=20: False)
    core = streamer_core.StreamerCore()
    core.config["video_encoder"] = "h264_nvenc"
    data = core.get_status_data()
    assert data["video_encoder"] == "h264_nvenc"
    assert data["active_video_encoder"] == "libx264"


def test_changing_the_setting_takes_effect_without_restart(monkeypatch):
    calls = []

    def fake_resolve(req):
        calls.append(req)
        return "libx264"

    monkeypatch.setattr(streamer_core, "resolve_video_encoder", fake_resolve)
    core = streamer_core.StreamerCore()
    core.config["video_encoder"] = "auto"
    core.get_video_encoder()
    core.get_video_encoder()
    assert calls == ["auto"], "毎回プローブし直している（再生のたびに遅くなる）"
    core.config["video_encoder"] = "h264_nvenc"
    core.get_video_encoder()
    assert calls == ["auto", "h264_nvenc"], "設定変更が再起動なしで効かない"


# --------------------------------------------------------------------------
# 6. 切り替える手段
# --------------------------------------------------------------------------

def test_both_settings_screens_expose_the_selector():
    with io.open(os.path.join(BASE_DIR, "ui", "index.html"), encoding="utf-8") as f:
        html = f.read()
    assert 'id="hostVideoEncoder"' in html
    assert "set('hostVideoEncoder', cfg.video_encoder || 'auto');" in html
    assert "video_encoder: (document.getElementById('hostVideoEncoder') || {}).value || 'auto'," in html
    # 退避したことが画面から分かること
    assert 'id="hostActiveEncoder"' in html
    assert "active_video_encoder" in html

    with io.open(os.path.join(BASE_DIR, "gui_streamer.py"), encoding="utf-8") as f:
        gui = f.read()
    assert "opt_video_encoder" in gui
    assert '"video_encoder": video_encoder,' in gui


def test_cli_can_select_the_encoder():
    import argparse

    from config_overrides import add_config_arguments, build_overrides

    parser = argparse.ArgumentParser()
    add_config_arguments(parser)
    assert "video_encoder" not in build_overrides(parser.parse_args([]), environ={})
    over = build_overrides(parser.parse_args(["--video-encoder", "h264_nvenc"]), environ={})
    assert over["video_encoder"] == ("h264_nvenc", "cli")


def test_plugin_ui_is_in_sync():
    with io.open(os.path.join(BASE_DIR, "ui", "index.html"), encoding="utf-8") as f:
        src = f.read()
    with io.open(os.path.join(BASE_DIR, "plugin", "ui", "index.html"), encoding="utf-8") as f:
        assert f.read() == src
