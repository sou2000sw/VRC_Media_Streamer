# -*- coding: utf-8 -*-
"""素材（動画・ラジオ）音量フェーダーの単体テスト。

★ここで確かめたいのは「スライダーが動くこと」ではなく、
  **既定値のままなら FFmpeg コマンドが1文字も変わらないこと**と、
  **同じ値で呼ばれても配信を張り直さないこと**。
  前者を落とすと「触っていないのに音が変わった」、後者を落とすと
  「スライダーに触るたび視聴者側が切れる」という、どちらも
  原因の辿りにくい壊れ方になる。
"""

from streamer_core import (
    StreamerCore,
    build_media_audio_filter,
    build_radio_audio_filter,
    normalize_media_volume,
)


# ---------------------------------------------------------------- 正規化
def test_normalize_clamps_and_falls_back_to_unity():
    assert normalize_media_volume(1.0) == 1.0
    assert normalize_media_volume(0.5) == 0.5
    # 0 は「無音」という有効な指定。未設定として 1.0 へ戻してはいけない。
    assert normalize_media_volume(0) == 0.0
    assert normalize_media_volume(-3) == 0.0
    assert normalize_media_volume(99) == 2.0
    # 数値でない値・NaN は等倍へ倒す（黙って無音にしない）
    assert normalize_media_volume(None) == 1.0
    assert normalize_media_volume("abc") == 1.0
    assert normalize_media_volume(float("nan")) == 1.0


# ---------------------------------------------------------------- フィルタ文字列
def test_unity_volume_does_not_touch_the_filter_chain():
    """既定値では volume= を差し込まない（従来のコマンドと完全に一致させる）。"""
    assert build_media_audio_filter(1.0) == "aresample=async=1"
    assert build_media_audio_filter(None) == "aresample=async=1"


def test_non_unity_volume_is_prepended():
    assert build_media_audio_filter(0.5) == "volume=0.5,aresample=async=1"
    assert build_media_audio_filter(0) == "volume=0,aresample=async=1"
    assert build_media_audio_filter(2.0) == "volume=2,aresample=async=1"


def test_radio_filter_keeps_volume_before_fade():
    """ラジオでは volume → afade の順。効き方は同じだが読み順を固定しておく。"""
    af = build_radio_audio_filter(
        3, duration=200, seek_seconds=0,
        base=build_media_audio_filter(0.4),
    )
    parts = af.split(",")
    assert parts[0] == "volume=0.4"
    assert parts[1] == "aresample=async=1"
    assert any(p.startswith("afade=t=in") for p in parts)
    assert any(p.startswith("afade=t=out") for p in parts)


def test_radio_filter_unchanged_at_unity():
    """等倍なら、フェーダー追加前と同じ文字列であること。"""
    before = build_radio_audio_filter(3, duration=200, seek_seconds=0)
    after = build_radio_audio_filter(
        3, duration=200, seek_seconds=0,
        base=build_media_audio_filter(1.0),
    )
    assert before == after


# ---------------------------------------------------------------- コアの読み書き
def _core():
    return StreamerCore(override_port=8997, override_enable_tunnel=False)


def test_default_is_unity():
    assert _core().get_media_volume() == 1.0


def test_set_clamps_and_persists():
    core = _core()
    assert core.set_media_volume(0.25) == 0.25
    assert core.get_media_volume() == 0.25
    assert core.config["media_volume"] == 0.25
    assert core.set_media_volume(5) == 2.0
    assert core.set_media_volume("zzz") == 1.0


def test_no_reload_when_value_is_unchanged(monkeypatch):
    """UIは操作のたび現在値を送ってくる。同じ値で張り直すと配信が無駄に切れる。"""
    core = _core()
    core.set_media_volume(0.6)

    calls = []
    monkeypatch.setattr(core, "request_stream_reload_if_sending",
                        lambda: calls.append(1))

    core.set_media_volume(0.6)
    assert calls == []

    core.set_media_volume(0.7)
    assert len(calls) == 1


def test_status_exposes_media_volume():
    core = _core()
    core.set_media_volume(1.5)
    assert core.get_status_data()["media_volume"] == 1.5


# ---------------------------------------------------------------- 実際のFFmpegコマンド
# ★上のフィルタ単体テストが通っても、コマンドへ**配線されている**保証はない。
#   実際に組み上がる引数列から -af を取り出して確かめる。
import io as _io
from unittest.mock import MagicMock, patch

_H264_OK = {
    "codec_name": "h264",
    "pix_fmt": "yuv420p",
    "height": "1080",
    "r_frame_rate": "30/1",
    "avg_frame_rate": "30/1",
}


def _af_of(cmd):
    """組み上がったコマンドから -af の値を取り出す。無ければ None。"""
    assert cmd is not None, "FFmpeg コマンドが組み上がっていない"
    return cmd[cmd.index("-af") + 1] if "-af" in cmd else None


def _local_item(tmp_path, name="v.mp4"):
    f = tmp_path / name
    f.write_bytes(b"dummy")
    return {"id": "v1", "type": "local_video", "title": "t",
            "url": str(f), "path": str(f), "duration": 30.0, "is_local": True}


def _capture(core, item, probe_params=None, radio=False):
    captured = {}

    def mock_popen(cmd, *args, **kwargs):
        captured["cmd"] = cmd
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdout = _io.BytesIO(b"")
        return proc

    with patch("subprocess.Popen", side_effect=mock_popen), \
         patch.object(core, "ensure_stream_sink", return_value=True), \
         patch("streamer_core.probe_video_stream_params", return_value=probe_params):
        if radio:
            core.play_radio(item)
        else:
            core.play_video(item)
    return captured.get("cmd")


def test_video_reencode_path_carries_volume(tmp_path):
    """諸元不明＝再エンコード経路。"""
    core = _core()
    core.set_media_volume(0.4)
    af = _af_of(_capture(core, _local_item(tmp_path), probe_params=None))
    assert af == "volume=0.4,aresample=async=1"


def test_video_copy_path_carries_volume(tmp_path):
    """映像は copy でも音声は AAC へ焼き直しているので、こちらにも効く。"""
    core = _core()
    core.set_media_volume(0.4)
    af = _af_of(_capture(core, _local_item(tmp_path), probe_params=_H264_OK))
    assert af == "volume=0.4,aresample=async=1"


def test_radio_path_carries_volume(tmp_path):
    core = _core()
    core.set_media_volume(0.4)
    af = _af_of(_capture(core, _local_item(tmp_path, "r.mp4"), radio=True))
    assert af.startswith("volume=0.4,aresample=async=1")


def test_default_leaves_every_path_untouched(tmp_path):
    """既定値では、どの経路も従来と同じ -af のままであること。"""
    core = _core()
    assert core.get_media_volume() == 1.0
    assert _af_of(_capture(core, _local_item(tmp_path), probe_params=None)) == "aresample=async=1"
    assert _af_of(_capture(core, _local_item(tmp_path), probe_params=_H264_OK)) == "aresample=async=1"
    assert _af_of(_capture(core, _local_item(tmp_path, "r.mp4"), radio=True)).startswith("aresample=async=1")
