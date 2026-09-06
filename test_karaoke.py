# -*- coding: utf-8 -*-
"""タスク27: 参加型カラオケ・セッションのテスト。

★ここで守りたいこと
  1. カラオケを **使わないとき**、FFmpeg のコマンドが従来と 1 バイトも変わらないこと。
     （音声まわりは既に何度も壊してきた場所なので、退行を最優先で止める）
  2. カラオケを **使うとき**、伴奏側の音量が有効化の前後で変わらないこと。
     （amix の normalize を切る埋め合わせが効いているか）
  3. ミキサ・ジッタバッファ・WebSocket のフレーム処理が仕様どおりであること。
"""

import io
import json
import os
import re
import struct
import threading
import time

import pytest

import remote_mic
import ws_server
from remote_mic import (
    JitterBuffer, KaraokeSession, Participant, ReverbLine, DelayLine,
    pan_gains, mix_participants, float_to_s16le, peak_level,
    build_remote_mic_input, ms_to_frames,
    SAMPLE_RATE, OUTPUT_CHANNELS, FRAMES_PER_TICK, FRAME_MS,
    KARAOKE_BASE_DELAY_MS, LATENCY_MODES, REVERB_PRESETS,
    STATE_WAITING, STATE_ACTIVE, MAX_PARTICIPANTS,
)
from streamer_core import build_audio_inputs, build_audio_inputs_with_remote_mic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 1. 退行防止: カラオケを使わないときは従来どおり
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kwargs", [
    dict(app_enabled=False, mic_device="Mic A", loopback_device=""),
    dict(app_enabled=False, mic_device="Mic A", loopback_device="Loop B"),
    dict(app_enabled=True, mic_device="", loopback_device=""),
    dict(app_enabled=True, mic_device="Mic A", loopback_device="Loop B"),
])
def test_no_remote_mic_keeps_existing_command(kwargs):
    """remote_mic_pipe を渡さなければ、戻り値は従来と完全に一致すること。

    既定引数を足しただけで音声グラフが変わっていないことを、
    「引数を渡さない呼び方」と「None を明示する呼び方」の両方で確かめる。
    """
    baseline = build_audio_inputs(**kwargs)
    explicit_none = build_audio_inputs(remote_mic_pipe=None, **kwargs)
    assert baseline == explicit_none
    # 従来のフィルタには normalize / adelay は現れない。
    _, filt, _ = baseline
    if filt:
        assert "normalize" not in filt
        assert "adelay" not in filt


# ---------------------------------------------------------------------------
# 2. カラオケ有効時の FFmpeg グラフ
# ---------------------------------------------------------------------------
PIPE = r"\\.\pipe\vrc_remote_mic_test"


def _volumes(filter_str):
    """フィルタ文字列から (ラベル -> volume値) を拾う。"""
    out = {}
    for chunk in filter_str.split(";"):
        m = re.match(r"\[\d+:a\]volume=([0-9.]+).*?\[(\w+)\]$", chunk)
        if m:
            out[m.group(2)] = float(m.group(1))
    return out


def test_remote_mic_appends_input_last():
    """歌声の入力は必ず最後尾。既存の入力インデックスを動かさないこと。"""
    args, filt, amap = build_audio_inputs(
        app_enabled=True, app_volume=1.0,
        mic_device="Mic A", loopback_device="Loop B",
        start_index=1, remote_mic_pipe=PIPE)
    assert amap == "[aout]"
    # 入力の並び: 1=アプリ(pipe:0), 2=マイク, 3=ループバック, 4=歌声
    assert args.index("pipe:0") < args.index("audio=Mic A")
    assert args.index("audio=Mic A") < args.index("audio=Loop B")
    assert args.index("audio=Loop B") < args.index(PIPE)
    assert "[4:a]" in filt and "[armic]" in filt


def test_remote_mic_input_is_stereo_48k():
    """パイプの読み口はミキサの出力（48kHz/ステレオ/s16le）と一致していること。

    ここがずれると、音は出るが速さと音程がおかしくなる。
    """
    args = build_remote_mic_input(PIPE)
    assert args[args.index("-ar") + 1] == str(SAMPLE_RATE)
    assert args[args.index("-ac") + 1] == str(OUTPUT_CHANNELS)
    assert args[args.index("-f") + 1] == "s16le"
    assert args[-1] == PIPE


def test_bgm_volume_is_preserved_when_karaoke_turns_on():
    """カラオケを有効にしても伴奏側の聞こえ方が変わらないこと。

    従来 amix(normalize=1) は入力2本を 1/2 ずつに割っていた。歌声を足した後も
    伴奏側の実効音量は同じ（volume値 × normalize係数）でなければならない。
    """
    # 従来: マイク1.0 / ループバック0.8 の 2 本 -> normalize=1 で各 1/2
    _, before, _ = build_audio_inputs(
        mic_device="Mic A", loopback_device="Loop B",
        mic_volume=1.0, loopback_volume=0.8)
    assert "normalize" not in before
    v_before = _volumes(before)
    effective_before = {k: v * 0.5 for k, v in v_before.items()}   # amix が割る分

    # カラオケ有効: normalize=0 になる代わりに volume 側へ 1/2 を織り込む
    _, after, _ = build_audio_inputs(
        mic_device="Mic A", loopback_device="Loop B",
        mic_volume=1.0, loopback_volume=0.8, remote_mic_pipe=PIPE)
    assert "normalize=0" in after
    v_after = _volumes(after)
    for label, expected in effective_before.items():
        assert v_after[label] == pytest.approx(expected, abs=0.01), \
            f"{label} の実効音量がカラオケ有効化で変わっている"


def test_single_bgm_source_is_not_scaled_down():
    """伴奏側が1本だけなら、従来 amix は無かったので割ってはいけない。"""
    _, filt, _ = build_audio_inputs(
        mic_device="Mic A", mic_volume=1.0, remote_mic_pipe=PIPE)
    assert _volumes(filt)["amic"] == pytest.approx(1.0)


def test_bgm_delay_is_applied_only_to_bgm_side():
    """伴奏側にだけ adelay の下駄が付き、歌声側には付かないこと。"""
    _, filt, _ = build_audio_inputs(
        mic_device="Mic A", loopback_device="Loop B",
        remote_mic_pipe=PIPE, bgm_delay_ms=KARAOKE_BASE_DELAY_MS)
    parts = {c.split("[")[-1].rstrip("]"): c for c in filt.split(";") if c.endswith("]")}
    for label in ("amic", "apc"):
        assert f"adelay={KARAOKE_BASE_DELAY_MS}:all=1" in parts[label]
    assert "adelay" not in parts["armic"], "歌声にまで下駄を履かせてはいけない"


def test_bgm_delay_zero_emits_no_adelay():
    _, filt, _ = build_audio_inputs(
        mic_device="Mic A", remote_mic_pipe=PIPE, bgm_delay_ms=0)
    assert "adelay" not in filt


def test_remote_mic_only_needs_no_amix():
    """ホスト側の機材が1つも無い（スマホ1台のラジオ枠）構成が成立すること。"""
    args, filt, amap = build_audio_inputs(remote_mic_pipe=PIPE)
    assert amap == "[aout]"
    assert "amix" not in filt
    assert filt.endswith("[aout]")
    assert args[-1] == PIPE


# ---------------------------------------------------------------------------
# 3. ジッタバッファ
# ---------------------------------------------------------------------------
def _tone(n_frames, amp=8000):
    import array
    return array.array("h", [amp if (i // 32) % 2 == 0 else -amp
                             for i in range(n_frames)]).tobytes()


def test_jitter_buffer_primes_before_playing():
    """目標の深さまで溜まるまでは無音を返すこと（頭から音切れさせない）。"""
    jb = JitterBuffer(target_ms=40)
    out = jb.take(FRAMES_PER_TICK)
    assert set(out) == {0}, "溜まる前に中身を出してはいけない"

    jb.push(_tone(ms_to_frames(40)))
    out = jb.take(FRAMES_PER_TICK)
    assert any(v != 0 for v in out), "目標まで溜まったら出し始めること"


def test_jitter_buffer_underrun_fills_with_silence():
    """足りない分は無音で埋め、長さは必ず要求どおりであること。"""
    jb = JitterBuffer(target_ms=20)
    jb.push(_tone(ms_to_frames(20)))
    jb.take(FRAMES_PER_TICK)          # prime して吐き出す
    before = jb.underruns
    out = jb.take(FRAMES_PER_TICK)    # 空
    assert len(out) == FRAMES_PER_TICK
    assert jb.underruns == before + 1


def test_jitter_buffer_drops_when_overfilled():
    """溜まりすぎたら古い方を捨てて遅延を取り戻すこと。

    捨てないと、一度混んだだけで遅延が単調に伸び続け二度と戻らない。
    """
    jb = JitterBuffer(target_ms=40)
    for _ in range(50):
        jb.push(_tone(ms_to_frames(40)))
    assert jb.drops > 0
    assert jb.depth_ms() <= 40 * remote_mic.JITTER_MAX_FACTOR + FRAME_MS


def test_jitter_buffer_ignores_odd_byte_tail():
    """半端な 1 バイトが混ざってもサンプル境界がずれないこと。"""
    jb = JitterBuffer(target_ms=20)
    jb.push(_tone(ms_to_frames(20)) + b"\x01")
    assert jb.received_bytes % 2 == 0


def test_latency_mode_changes_target():
    jb = JitterBuffer(target_ms=LATENCY_MODES["low"])
    assert jb.target_ms == 40
    jb.set_target(LATENCY_MODES["stable"])
    assert jb.target_ms == 120


# ---------------------------------------------------------------------------
# 4. ミキシング・PAN・リバーブ・遅延
# ---------------------------------------------------------------------------
def test_pan_gains_center_is_unity():
    """中央では左右とも 1.0。PAN を触っただけで音量が変わらないこと。"""
    assert pan_gains(0.0) == (1.0, 1.0)
    assert pan_gains(-1.0) == (1.0, 0.0)
    assert pan_gains(1.0) == (0.0, 1.0)
    assert pan_gains(-5) == (1.0, 0.0)      # 範囲外は丸める


def test_mix_participants_interleaves_stereo():
    import array
    mono = array.array("h", [1000] * 4)
    out = mix_participants([(mono, 1.0, 0.0)], 4)
    assert len(out) == 8
    assert out[0::2] == [1000.0] * 4    # L
    assert out[1::2] == [0.0] * 4       # R


def test_mix_participants_sums_sources():
    import array
    a = array.array("h", [1000] * 4)
    b = array.array("h", [500] * 4)
    out = mix_participants([(a, 1.0, 1.0), (b, 1.0, 1.0)], 4)
    assert out[0] == 1500.0


def test_float_to_s16le_saturates_instead_of_wrapping():
    """クリップは飽和させること。折り返すと轟音のノイズになる。"""
    data = float_to_s16le([40000.0, -40000.0])
    assert struct.unpack("<hh", data) == (32767, -32768)


def test_delay_line_shifts_by_requested_amount():
    """遅延ラインが指定サンプル数ぶん実際に遅らせること。"""
    dl = DelayLine(KARAOKE_BASE_DELAY_MS * 2)
    dl.set_delay_ms(20)                       # = 960 フレーム
    first = dl.process([1000.0] * (FRAMES_PER_TICK * OUTPUT_CHANNELS))
    assert set(first) == {0.0}, "遅延ぶんの最初は無音で出てくるはず"
    second = dl.process([0.0] * (FRAMES_PER_TICK * OUTPUT_CHANNELS))
    assert second[0] == 1000.0, "1 刻み後に元の音が出てくるはず"


def test_delay_line_zero_is_passthrough():
    dl = DelayLine(100)
    dl.set_delay_ms(0)
    assert dl.process([1.0, 2.0, 3.0, 4.0]) == [1.0, 2.0, 3.0, 4.0]


def test_reverb_off_is_passthrough():
    rv = ReverbLine()
    rv.configure("off")
    assert rv.process([100.0, 200.0]) == [100.0, 200.0]


def test_reverb_adds_a_decaying_tail():
    """リバーブは「後から小さく返ってくる」こと。"""
    rv = ReverbLine()
    rv.configure("mid")
    n = ms_to_frames(45) * OUTPUT_CHANNELS
    rv.process([10000.0] * 2 + [0.0] * (n - 2))   # 頭だけ鳴らす
    tail = rv.process([0.0] * n)
    assert max(tail) > 0, "遅れて返ってこない"
    assert max(tail) < 10000.0, "返りが元より大きいのは発振している"


def test_peak_level_is_normalised():
    import array
    assert peak_level(array.array("h", [32767]), 1) == pytest.approx(1.0, abs=0.001)
    assert peak_level(array.array("h", [0, 0]), 2) == 0.0


# ---------------------------------------------------------------------------
# 5. セッション（承認制・権限）
# ---------------------------------------------------------------------------
@pytest.fixture
def session(tmp_path):
    s = KaraokeSession(recordings_dir=str(tmp_path / "recordings"))
    yield s
    s.stop()


def test_new_participant_waits_when_approval_required(session):
    """既定は承認制。繋いだだけでは声は乗らない。"""
    session.configure(approval_required=True)
    p, err = session.add_participant("id1", "Taro")
    assert err is None
    assert p.state == STATE_WAITING
    assert not p.audible


def test_open_policy_lets_participant_speak_immediately(session):
    session.configure(approval_required=False)
    p, _ = session.add_participant("id1", "Taro")
    assert p.state == STATE_ACTIVE
    assert p.audible


def test_audio_from_unapproved_participant_is_discarded(session):
    """承認前の音は **受け取った時点で捨てる**。

    バッファへ積んでから捨てる作りにすると、承認した瞬間に溜まっていた
    過去の音がまとめて流れ出す。
    """
    session.configure(approval_required=True)
    p, _ = session.add_participant("id1", "Taro")
    assert session.push_audio("id1", _tone(1000)) is False
    assert p.buffer.received_bytes == 0

    session.set_state("id1", STATE_ACTIVE)
    assert session.push_audio("id1", _tone(1000)) is True
    assert p.buffer.received_bytes > 0


def test_host_mute_and_self_mute_both_silence(session):
    session.configure(approval_required=False)
    p, _ = session.add_participant("id1", "Taro")
    assert p.audible
    p.self_muted = True
    assert not p.audible
    p.self_muted = False
    session.set_mix("id1", host_muted=True)
    assert not p.audible


def test_participant_limit_is_enforced(session):
    for i in range(MAX_PARTICIPANTS):
        p, err = session.add_participant(f"id{i}", f"P{i}")
        assert p is not None, err
    p, err = session.add_participant("overflow", "TooMany")
    assert p is None and err


def test_name_is_trimmed_and_defaulted(session):
    p, _ = session.add_participant("id1", "   ")
    assert p.name == "ゲスト"
    long_name, _ = session.add_participant("id2", "あ" * 100)
    assert len(long_name.name) == remote_mic.MAX_NAME_LEN


def test_mix_values_are_clamped(session):
    session.add_participant("id1", "Taro")
    p = session.set_mix("id1", volume=99, pan=99)
    assert p.volume == 2.0 and p.pan == 1.0
    p = session.set_mix("id1", volume=-5, pan=-5)
    assert p.volume == 0.0 and p.pan == -1.0


def test_offset_is_clamped_to_slider_range(session):
    assert session.configure(offset_ms=9999)["offset_ms"] == remote_mic.KARAOKE_OFFSET_MAX_MS
    assert session.configure(offset_ms=-9999)["offset_ms"] == remote_mic.KARAOKE_OFFSET_MIN_MS


def test_offset_maps_to_base_plus_offset_delay(session):
    """遅延補正 0 のとき、マイク側の遅延は伴奏の下駄と同じであること。

    ここがずれると、スライダを 0 にしても歌がずれる。
    """
    session.configure(offset_ms=0)
    assert session._delay_line._delay_frames == ms_to_frames(KARAOKE_BASE_DELAY_MS)
    session.configure(offset_ms=-KARAOKE_BASE_DELAY_MS)
    assert session._delay_line._delay_frames == 0
    session.configure(offset_ms=200)
    assert session._delay_line._delay_frames == ms_to_frames(KARAOKE_BASE_DELAY_MS + 200)


def test_latency_mode_applies_to_existing_participants(session):
    session.add_participant("id1", "Taro")
    session.configure(latency_mode="stable")
    assert session.get("id1").buffer.target_ms == LATENCY_MODES["stable"]


def test_status_snapshot_is_json_serialisable(session):
    session.add_participant("id1", "Taro")
    payload = json.dumps(session.status_snapshot(), ensure_ascii=False)
    assert "Taro" in payload


# ---------------------------------------------------------------------------
# 6. ミキサの実走行（出口なし）
# ---------------------------------------------------------------------------
def test_mixer_produces_real_time_amount_of_audio(session):
    """ミキサが壁時計に沿った量を作ること（速すぎず遅すぎず）。

    ★ここが狂うと配信の音が早送り／スローになる。sleep の積み上げでは
      ずれるので、経過時間から逆算する作りになっているかを実測で確かめる。
    """
    session.configure(approval_required=False)
    session.add_participant("id1", "Taro")
    session.ensure_mixer()
    time.sleep(1.0)
    ticks = session.ticks
    session.stop()
    expected = 1000 / FRAME_MS          # 1 秒 = 50 刻み
    assert expected * 0.75 <= ticks <= expected * 1.25, \
        f"1秒で {ticks} 刻み（期待 {expected} 前後）"


def test_recording_writes_a_playable_wav(session, tmp_path):
    """録音がヘッダの正しい WAV になっていること。"""
    import wave
    session.ensure_mixer()
    path = session.start_recording()
    assert path
    time.sleep(0.4)
    session.stop_recording()
    session.stop()
    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == OUTPUT_CHANNELS
        assert wf.getframerate() == SAMPLE_RATE
        assert wf.getsampwidth() == 2
        assert wf.getnframes() > 0


# ---------------------------------------------------------------------------
# 7. WebSocket のフレーム処理
# ---------------------------------------------------------------------------
def test_accept_key_matches_rfc_example():
    """RFC 6455 4.2.2 の例そのもの。ここが違うとブラウザが接続を拒む。"""
    assert ws_server.compute_accept("dGhlIHNhbXBsZSBub25jZQ==") == \
        "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


class _Headers(dict):
    def get(self, k, default=None):
        for key, val in self.items():
            if key.lower() == k.lower():
                return val
        return default


def test_upgrade_detection_accepts_multi_token_connection_header():
    """Connection: keep-alive, Upgrade を弾かないこと（Firefox がこう送る）。"""
    h = _Headers({"Upgrade": "websocket", "Connection": "keep-alive, Upgrade",
                  "Sec-WebSocket-Version": "13", "Sec-WebSocket-Key": "x"})
    assert ws_server.is_websocket_upgrade(h)


def test_upgrade_detection_rejects_plain_request():
    assert not ws_server.is_websocket_upgrade(_Headers({}))
    assert not ws_server.is_websocket_upgrade(_Headers({
        "Upgrade": "websocket", "Connection": "Upgrade",
        "Sec-WebSocket-Version": "8", "Sec-WebSocket-Key": "x"}))


def _client_frame(opcode, payload, mask=b"\xaa\xbb\xcc\xdd"):
    """クライアントが送る体（＝マスクあり）のフレームを組む。"""
    masked = bytes(b ^ mask[i & 3] for i, b in enumerate(payload))
    n = len(payload)
    if n < 126:
        header = struct.pack(">BB", 0x80 | opcode, 0x80 | n)
    elif n < 65536:
        header = struct.pack(">BBH", 0x80 | opcode, 0x80 | 126, n)
    else:
        header = struct.pack(">BBQ", 0x80 | opcode, 0x80 | 127, n)
    return header + mask + masked


class _FakeSock:
    def shutdown(self, how):
        pass


def _conn_from(raw):
    return ws_server.WebSocketConnection(_FakeSock(), io.BytesIO(raw), io.BytesIO())


def test_recv_unmasks_text_frame():
    conn = _conn_from(_client_frame(ws_server.OPCODE_TEXT, "こんにちは".encode("utf-8")))
    assert conn.recv() == ("text", "こんにちは")


def test_recv_reassembles_fragments():
    """分割送信されたバイナリを繋ぎ直すこと（音声チャンクが割れても壊れない）。"""
    mask = b"\x01\x02\x03\x04"
    part1 = bytes(b ^ mask[i & 3] for i, b in enumerate(b"AAAA"))
    part2 = bytes(b ^ mask[i & 3] for i, b in enumerate(b"BBBB"))
    raw = (struct.pack(">BB", ws_server.OPCODE_BINARY, 0x80 | 4) + mask + part1
           + struct.pack(">BB", 0x80 | ws_server.OPCODE_CONT, 0x80 | 4) + mask + part2)
    assert _conn_from(raw).recv() == ("binary", b"AAAABBBB")


def test_unmasked_client_frame_is_rejected():
    """マスクなしのフレームは RFC 違反。受け取らずに切ること。"""
    raw = struct.pack(">BB", 0x80 | ws_server.OPCODE_TEXT, 2) + b"hi"
    with pytest.raises(ws_server.WebSocketError):
        _conn_from(raw).recv()


def test_oversized_frame_is_rejected():
    """長さだけ巨大を名乗るフレームでメモリを食い潰されないこと。"""
    raw = struct.pack(">BBQ", 0x80 | ws_server.OPCODE_BINARY, 0x80 | 127,
                      ws_server.MAX_PAYLOAD_BYTES + 1) + b"\x00\x00\x00\x00"
    with pytest.raises(ws_server.WebSocketError):
        _conn_from(raw).recv()


def test_ping_is_answered_with_pong():
    conn = ws_server.WebSocketConnection(
        _FakeSock(),
        io.BytesIO(_client_frame(ws_server.OPCODE_PING, b"xy")
                   + _client_frame(ws_server.OPCODE_TEXT, b"ok")),
        io.BytesIO())
    assert conn.recv() == ("text", "ok")
    sent = conn.wfile.getvalue()
    assert sent[0] == 0x80 | ws_server.OPCODE_PONG
    assert sent.endswith(b"xy")


def test_close_frame_ends_the_conversation():
    assert _conn_from(_client_frame(ws_server.OPCODE_CLOSE, b"")).recv() is None


def test_server_frames_are_not_masked():
    """サーバ→クライアントはマスクしないこと（するとブラウザが切る）。"""
    conn = ws_server.WebSocketConnection(_FakeSock(), io.BytesIO(), io.BytesIO())
    conn.send_text("hi")
    assert conn.wfile.getvalue() == b"\x81\x02hi"


def test_large_server_frame_uses_extended_length():
    conn = ws_server.WebSocketConnection(_FakeSock(), io.BytesIO(), io.BytesIO())
    conn.send_binary(b"\x00" * 200)
    assert conn.wfile.getvalue()[:4] == b"\x82\x7e\x00\xc8"
