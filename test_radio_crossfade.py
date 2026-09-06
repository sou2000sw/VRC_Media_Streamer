# -*- coding: utf-8 -*-
"""ラジオモードの曲間フェード（タスク17）の回帰テスト。

固定したいのは4点:

1. **重ねる方式には戻れない**。送出は 1曲 = 1本の送信FFmpegで永続シンクの
   pipe:0 へ MPEG-TS を流し込む構造のため、2曲を同時に流すと多重化が壊れる。
   ここで検証するのは「重ねない afade 方式」であり、生成される -af は
   単一入力に閉じていること（acrossfade を使っていないこと）。
2. **ホットリロードで音量を揺らさない**。設定保存のたびに play_radio が
   seek 付きで張り直されるため、seek>0 でフェードインを掛けると
   利用者には原因不明の音量ゆらぎとして出る。
3. **長さ不明の曲でフェードアウトを掛けない**。開始位置が決まらないうえ、
   -shortest で入力が尽きる瞬間も事前には読めない。
4. **既存の aresample=async=1 を落とさない**。A/V同期のために入っている
   フィルタで、フェード追加のついでに消してはいけない。
"""

import io
import json
import os

import pytest

import streamer_core
from streamer_core import build_radio_audio_filter, normalize_radio_crossfade

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# --------------------------------------------------------------------------
# 1. 既定値と設定
# --------------------------------------------------------------------------

def test_default_is_three_seconds():
    assert streamer_core.DEFAULT_CONFIG["radio_crossfade_duration"] == 3


def test_dist_config_ships_the_key():
    with io.open(os.path.join(BASE_DIR, "config.dist.json"), encoding="utf-8") as f:
        assert json.load(f)["radio_crossfade_duration"] == 3


@pytest.mark.parametrize("raw,expected", [
    (0, 0.0),
    (3, 3.0),
    (5, 5.0),
    (99, 5.0),        # 上限で頭打ち
    (-2, 0.0),        # 負値は無効
    ("2.5", 2.5),     # UIからは文字列で届きうる
    ("", 0.0),
    (None, 0.0),
    ("abc", 0.0),
    (float("nan"), 0.0),
])
def test_setting_is_clamped(raw, expected):
    assert normalize_radio_crossfade(raw) == expected


def test_core_reads_the_setting():
    core = streamer_core.StreamerCore()
    core.config["radio_crossfade_duration"] = 4
    assert core.get_radio_crossfade_duration() == 4.0
    core.config["radio_crossfade_duration"] = 100
    assert core.get_radio_crossfade_duration() == 5.0


def test_status_exposes_the_setting():
    core = streamer_core.StreamerCore()
    core.config["radio_crossfade_duration"] = 2
    assert core.get_status_data()["radio_crossfade_duration"] == 2.0


# --------------------------------------------------------------------------
# 2. -af の組み立て
# --------------------------------------------------------------------------

def test_disabled_keeps_only_the_existing_filter():
    """0 のときは今までと完全に同じ引数であること（既定変更前の挙動へ戻せる）。"""
    assert build_radio_audio_filter(0, duration=300) == "aresample=async=1"


def test_resample_filter_is_never_dropped():
    for seek in (0, 30):
        assert build_radio_audio_filter(3, duration=300, seek_seconds=seek).startswith("aresample=async=1")


def test_fade_in_and_out_for_a_normal_track():
    af = build_radio_audio_filter(3, duration=300)
    assert af == "aresample=async=1,afade=t=in:st=0:d=3,afade=t=out:st=297.000:d=3"


def test_never_uses_acrossfade():
    """重ねる方式は現構造では成立しない（同一pipeへ2本流せない）。"""
    assert "acrossfade" not in build_radio_audio_filter(3, duration=300)


def test_hot_reload_resume_does_not_fade_in_again():
    af = build_radio_audio_filter(3, duration=300, seek_seconds=120)
    assert "afade=t=in" not in af
    # 曲尾は張り直し後の時間軸（-ss 済み）で測る: 300 - 120 - 3 = 177
    assert "afade=t=out:st=177.000:d=3" in af


def test_unknown_duration_gets_fade_in_only():
    af = build_radio_audio_filter(3, duration=0)
    assert "afade=t=in" in af
    assert "afade=t=out" not in af


def test_short_track_shrinks_the_fade():
    """8秒の曲に3秒フェードは掛けない（曲長の1/4まで）。"""
    af = build_radio_audio_filter(3, duration=8)
    assert "afade=t=in:st=0:d=2" in af
    assert "afade=t=out:st=6.000:d=2" in af


def test_very_short_track_gets_no_fade():
    assert build_radio_audio_filter(3, duration=1.5) == "aresample=async=1"


def test_seek_past_the_fade_out_point_omits_it():
    """残り時間がフェード幅を切っていたら、負の st を渡さない。"""
    af = build_radio_audio_filter(3, duration=300, seek_seconds=299)
    assert "afade=t=out" not in af


# --------------------------------------------------------------------------
# 3. 送出コマンドに実際に載ること
# --------------------------------------------------------------------------

def _radio_cmd(monkeypatch, crossfade, duration=240, seek=0):
    """play_radio が組む FFmpeg 引数を、プロセスを起こさずに取り出す。"""
    core = streamer_core.StreamerCore()
    core.config["radio_crossfade_duration"] = crossfade
    core.config["radio_bg_source"] = "standby"
    core.config["overlay_qr_enabled"] = False
    core.config["overlay_clock_enabled"] = False
    core.config["overlay_clock_video"] = False

    captured = {}

    monkeypatch.setattr(core, "ensure_stream_sink", lambda: True)
    monkeypatch.setattr(core, "get_audio_only_stream_urls",
                        lambda url: ("http://example.invalid/a.m4a", "Track", duration, None,
                                     {"title": "Track", "duration": duration}))
    # 背景は「実在するファイル」であればよい（Popen を差し替えるので中身は読まれない）。
    # os.path.exists 自体を差し替えると pytest 内部まで巻き込むため触らない。
    monkeypatch.setattr(core, "get_radio_background_path", lambda *a, **k: os.path.abspath(__file__))

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        raise RuntimeError("stop before spawning ffmpeg")

    monkeypatch.setattr(streamer_core.subprocess, "Popen", fake_popen)
    core.play_radio({"url": "https://example.invalid/watch?v=x", "title": "Track"}, seek_seconds=seek)
    return captured.get("cmd") or []


def _af_value(cmd):
    return cmd[cmd.index("-af") + 1]


def test_command_carries_the_fade(monkeypatch):
    cmd = _radio_cmd(monkeypatch, 3)
    assert _af_value(cmd) == "aresample=async=1,afade=t=in:st=0:d=3,afade=t=out:st=237.000:d=3"


def test_command_unchanged_when_disabled(monkeypatch):
    cmd = _radio_cmd(monkeypatch, 0)
    assert _af_value(cmd) == "aresample=async=1"
