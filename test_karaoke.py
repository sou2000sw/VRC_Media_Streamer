# -*- coding: utf-8 -*-
"""タスク27: 参加型カラオケ・セッションのテスト。

★ここで守りたいこと
  1. カラオケを **使わないとき**、FFmpeg のコマンドが従来と 1 バイトも変わらないこと。
     （音声まわりは既に何度も壊してきた場所なので、退行を最優先で止める）
  2. カラオケを **使うとき**、伴奏側の音量が有効化の前後で変わらないこと。
     （amix の normalize を切る埋め合わせが効いているか）
  3. ミキサ・ジッタバッファ・WebSocket のフレーム処理が仕様どおりであること。
"""

import array
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
    SAMPLE_RATE, OUTPUT_CHANNELS, FRAMES_PER_TICK, FRAME_MS, BYTES_PER_SAMPLE,
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


# ---------------------------------------------------------------------------
# 8. API の権限境界（ソケットを張らずにハンドラのメソッドだけ試す）
#
# ★ここが破れると承認制が意味を失う。参加者が自分で自分を承認できてしまえば、
#   「知らないうちに他人の声が配信へ乗る」という一番重い事故がそのまま起きる。
# ---------------------------------------------------------------------------
import api_server


class _Headers(dict):
    def __init__(self, mapping=None):
        super().__init__({k.lower(): v for k, v in (mapping or {}).items()})

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


class _CoreStub:
    def __init__(self, session, web_password=""):
        self.karaoke = session
        self.config = {"enable_web_remote": True, "trust_lan_clients": False,
                       "web_password": web_password}


def _api_handler(session, client_ip="127.0.0.1", headers=None, web_password=""):
    h = object.__new__(api_server.APIAndHLSHandler)
    h.streamer_core = _CoreStub(session, web_password)
    h.client_address = (client_ip, 12345)
    h.headers = _Headers(headers)
    h._origin_is_self = lambda: True
    h._host_header_is_safe = lambda: True
    h.sent = []
    h.send_json_response = lambda code, data: h.sent.append((code, data))
    return h


def test_guest_cannot_reach_host_controls(session):
    """ゲストのPOSTは 403。ここが開くと参加者が自分を承認できる。"""
    h = _api_handler(session, client_ip="192.168.1.50")
    assert h.is_local_request() is False


def test_tunnel_client_is_never_treated_as_host(session):
    """トンネル経由は cloudflared が 127.0.0.1 から繋ぐので IP だけでは見分けられない。

    CF-Connecting-IP / X-Forwarded-For があれば必ずゲスト扱いにすること。
    """
    for hdr in ("CF-Connecting-IP", "X-Forwarded-For"):
        h = _api_handler(session, client_ip="127.0.0.1", headers={hdr: "203.0.113.9"})
        assert h.is_local_request() is False, hdr


def test_ws_password_check_uses_configured_password(session):
    """PIN が設定されていれば hello の値で検証すること。"""
    import karaoke_ws
    h = _api_handler(session, client_ip="192.168.1.50", web_password="1234")
    h.register_auth_success = lambda: None
    h.register_auth_failure = lambda: None
    assert karaoke_ws._check_password(h, "1234") is True
    assert karaoke_ws._check_password(h, "9999") is False
    assert karaoke_ws._check_password(h, None) is False


def test_ws_password_check_counts_failures_for_lockout(session):
    """WebSocket の失敗も既存のブルートフォース対策へ合流させること。

    ここを素通しにすると、REST を固めても WS 側から総当たりできてしまう。
    """
    import karaoke_ws
    h = _api_handler(session, client_ip="192.168.1.50", web_password="1234")
    calls = {"ok": 0, "ng": 0}
    h.register_auth_success = lambda: calls.__setitem__("ok", calls["ok"] + 1)
    h.register_auth_failure = lambda: calls.__setitem__("ng", calls["ng"] + 1)
    karaoke_ws._check_password(h, "9999")
    karaoke_ws._check_password(h, "1234")
    assert calls == {"ok": 1, "ng": 1}


def test_ws_password_is_not_required_without_configuration(session):
    """PIN 未設定なら誰でも入れる（既存の Web リモコンと同じ扱い）。"""
    import karaoke_ws
    h = _api_handler(session, client_ip="192.168.1.50", web_password="")
    assert karaoke_ws._check_password(h, None) is True


# ---------------------------------------------------------------------------
# 9. 配布物（PyInstaller）への同梱
# ---------------------------------------------------------------------------
def test_build_script_declares_karaoke_modules():
    """karaoke_ws は関数内で遅延 import しているので、明示しないと取りこぼしうる。

    落ちるのは「実機でマイクを繋ごうとした瞬間」なので、ここで止める。
    """
    with io.open(os.path.join(BASE_DIR, "build_exe.py"), encoding="utf-8") as f:
        src = f.read()
    for mod in ("remote_mic", "ws_server", "karaoke_ws"):
        assert f'"--hidden-import", "{mod}"' in src, f"{mod} が build_exe.py に無い"


def test_default_config_keeps_karaoke_closed():
    """既定は必ず「閉じている」。開いた状態を初期値にしてはいけない。"""
    from streamer_core import DEFAULT_CONFIG
    assert DEFAULT_CONFIG["karaoke_enabled"] is False
    assert DEFAULT_CONFIG["karaoke_approval_required"] is True


# ---------------------------------------------------------------------------
# 10. Web UI（配布物のズレと、詰まりどころの案内）
# ---------------------------------------------------------------------------
def _ui_html():
    with io.open(os.path.join(BASE_DIR, "ui", "index.html"), encoding="utf-8") as f:
        return f.read()


def test_ui_has_karaoke_tab_and_host_panel():
    html = _ui_html()
    for needle in ('id="tab-karaoke"', 'id="nav-karaoke"', 'id="kaHostPanel"',
                   'karaokeToggleConnection()', '/ws/audio_session'):
        assert needle in html, needle


def test_ui_warns_about_https_requirement():
    """getUserMedia は https / localhost でしか動かない。

    ここを黙って通すと「つないでも何も起きない」という一番分かりにくい失敗になる。
    LAN の http://192.168.x.x で開いた参加者は必ずここに当たる。
    """
    html = _ui_html()
    assert 'id="kaInsecureNotice"' in html
    assert "karaokeIsSecureForMic" in html


def test_ui_defaults_sidetone_to_zero():
    """サイドトーンの初期値は 0。既定で自分の声を返すとハウリング事故になる。"""
    html = _ui_html()
    i = html.index('id="kaSidetone"')
    snippet = html[i:i + 200]
    assert 'value="0"' in snippet, snippet[:160]


def test_ui_participant_list_is_not_rebuilt_every_poll():
    """卓は 400ms ごとに更新する。毎回作り直すとスライダのドラッグが切れる。"""
    html = _ui_html()
    assert "ka.listSig" in html, "骨組みの差分判定が無い"
    assert "karaokeParticipantHtml" in html


def test_ui_escapes_participant_names():
    """表示名は参加者が自由に決める。そのまま埋めると HTML を注入できる。"""
    html = _ui_html()
    assert "karaokeEscape(p.name)" in html


# ---------------------------------------------------------------------------
# 11. 配信の張り直し（出口の付け替え）
#
# ★配信の停止・再開では「前の送出FFmpegを殺す」->「すぐ次を起こす」が続けて起きる。
#   前の回収スレッドは殺した相手の wait() から戻ってから出口を閉じるので、
#   出口を使い回すと **次の配信が掴んだパイプを前の回収が閉じてしまう**。
# ---------------------------------------------------------------------------
def test_open_sink_creates_a_fresh_pipe_each_time(session):
    """張り直しのたびに新しいパイプ名になること（使い回さない）。"""
    name1, sink1 = session.open_sink()
    if name1 is None:
        pytest.skip("名前付きパイプを作れない環境")
    name2, sink2 = session.open_sink()
    assert sink1 is not sink2
    assert name1 != name2, "パイプ名が使い回されている"
    session.close_sink()


def test_stale_reaper_does_not_close_the_new_pipe(session):
    """古い配信の回収が、次の配信の出口を巻き添えにしないこと。"""
    name1, sink1 = session.open_sink()
    if name1 is None:
        pytest.skip("名前付きパイプを作れない環境")
    name2, sink2 = session.open_sink()

    # 前の配信の回収スレッドが遅れて発火した、という状況
    session.close_sink(sink1)
    assert session.sink is sink2, "新しい出口まで閉じられている"

    # 自分の出口なら閉じる
    session.close_sink(sink2)
    assert session.sink is None


def test_close_sink_without_argument_closes_current(session):
    """引数なしの close_sink は今の出口を閉じる（停止・無効化の経路）。"""
    name, sink = session.open_sink()
    if name is None:
        pytest.skip("名前付きパイプを作れない環境")
    session.close_sink()
    assert session.sink is None


def test_mixer_survives_sink_replacement(session):
    """出口を付け替えてもミキサは回り続けること（参加者は繋がったまま）。"""
    session.configure(approval_required=False)
    session.add_participant("id1", "Taro")
    name, sink = session.open_sink()
    if name is None:
        pytest.skip("名前付きパイプを作れない環境")
    assert session.running
    session.open_sink()
    assert session.running, "出口の付け替えでミキサが止まっている"
    assert session.get("id1") is not None, "参加者まで消えている"


# ---------------------------------------------------------------------------
# 12. ホストPCのマイク（タスク27-A）
#
# ★きっかけ: カラオケ受付をONにしただけで「PCマイクも乗る」と読めてしまい、
#   実際にはライブ音声モードでもマイク未選択でもないまま「声が入らない」と
#   詰まる事故が起きた。卓の上で設定でき、生きているか見え、乗らない理由が
#   分かることを固定する。
# ---------------------------------------------------------------------------
import streamer_core


def test_host_mic_level_cmd_measures_without_saving_audio():
    """レベル測定は null 出力であること。録音してはいけない。"""
    cmd = streamer_core.build_host_mic_level_cmd("Mic A", ffmpeg="ffmpeg")
    assert cmd[-2:] == ["-f", "null"] or cmd[-3:-1] == ["-f", "null"], cmd[-4:]
    assert "audio=Mic A" in cmd
    # key を絞らないと1フレームにつき数十行出て読めない（実測: 2秒で2995行）
    assert any("key=lavfi.astats.Overall.RMS_level" in a for a in cmd)
    assert not any(a.endswith((".wav", ".mp3", ".ts")) for a in cmd), "音を保存してはいけない"


@pytest.mark.parametrize("text,expected", [
    ("0", 1.0),
    ("-6.02", 0.5),
    ("-20", 0.1),
    ("-inf", 0.0),
    ("-999", 0.0),
    ("こわれた値", 0.0),
    ("", 0.0),
])
def test_db_to_linear(text, expected):
    assert streamer_core._db_to_linear(text) == pytest.approx(expected, abs=0.005)


def test_db_to_linear_clamps_above_full_scale():
    """0dBFS を超える値が来ても 1.0 で頭打ちにする（メーターが振り切れて壊れない）。"""
    assert streamer_core._db_to_linear("6.0") == pytest.approx(1.0)


def test_host_mic_monitor_reports_nothing_before_it_runs():
    mon = streamer_core.HostMicMonitor()
    lv = mon.level()
    assert lv["fresh"] is False and lv["monitoring"] is False
    assert lv["peak"] == 0.0 and lv["rms"] == 0.0


def test_host_mic_monitor_ignores_empty_device():
    """デバイス未選択で ffmpeg を起こさないこと（無駄にマイクを掴まない）。"""
    mon = streamer_core.HostMicMonitor()
    mon.request("")
    mon.request("   ")
    assert mon.level()["monitoring"] is False


def test_host_mic_level_goes_stale():
    """レベルが古くなったら 0 を返し fresh=False にすること。

    これが無いと、マイクが死んだ後も最後の値が出続けて「生きている」と誤認する。
    """
    mon = streamer_core.HostMicMonitor()
    mon._level = {"peak": 0.5, "rms": 0.4,
                  "ts": time.time() - streamer_core.HOST_MIC_LEVEL_STALE_SEC - 1}
    lv = mon.level()
    assert lv["fresh"] is False and lv["rms"] == 0.0

    mon._level = {"peak": 0.5, "rms": 0.4, "ts": time.time()}
    lv = mon.level()
    assert lv["fresh"] is True and lv["rms"] == pytest.approx(0.4)


def test_host_mic_pump_parses_astats_lines():
    """astats の行から peak/rms を拾えること（実際に出る書式で確かめる）。"""
    class _FakeProc:
        def __init__(self, lines):
            import io as _io
            self.stderr = _io.BytesIO(lines)

        def poll(self):
            return None

    lines = (b"[Parsed_ametadata_1 @ 0x1] lavfi.astats.Overall.RMS_level=-20.000000\n"
             b"[Parsed_ametadata_2 @ 0x1] lavfi.astats.Overall.Peak_level=-6.020600\n")
    mon = streamer_core.HostMicMonitor()
    proc = _FakeProc(lines)
    mon._proc = proc
    mon._pump(proc)
    assert mon._level["rms"] == pytest.approx(0.1, abs=0.005)
    assert mon._level["peak"] == pytest.approx(0.5, abs=0.005)
    assert mon._level["ts"] > 0


def test_host_mic_pump_survives_inf_and_garbage():
    """'-inf' や欠けた行でメーターが壊れないこと。"""
    class _FakeProc:
        def __init__(self, lines):
            import io as _io
            self.stderr = _io.BytesIO(lines)

        def poll(self):
            return None

    lines = (b"garbage line\n"
             b"[x] lavfi.astats.Overall.RMS_level=-inf\n"
             b"[x] lavfi.astats.Overall.Peak_level=-inf\n")
    mon = streamer_core.HostMicMonitor()
    proc = _FakeProc(lines)
    mon._proc = proc
    mon._pump(proc)
    assert mon._level["rms"] == 0.0 and mon._level["peak"] == 0.0


def test_host_mic_state_explains_why_voice_is_not_on_air():
    """乗らない理由を state から判断できること（卓に出す文言の材料）。"""
    class _Core:
        config = {"live_audio_mic_device": "", "live_audio_mic_volume": 1.0,
                  "live_audio_loopback_device": "", "live_audio_loopback_volume": 0.7}
        status = "offline"
        host_mic_monitor = streamer_core.HostMicMonitor()

        def get_playback_mode(self):
            return self._mode

    c = _Core()
    get_state = streamer_core.StreamerCore.get_host_mic_state

    # 1) マイク未選択
    c._mode = "live"
    assert get_state(c)["on_air"] is False

    # 2) マイクはあるがライブ音声モードでない（今回の事故そのもの）
    c.config["live_audio_mic_device"] = "Mic A"
    c._mode = "video"
    st = get_state(c)
    assert st["is_live_audio_mode"] is False and st["on_air"] is False

    # 3) ライブ音声モードだが配信していない
    c._mode = "live"
    st = get_state(c)
    assert st["is_live_audio_mode"] is True and st["streaming"] is False and st["on_air"] is False

    # 4) 全部そろって初めて on_air
    c.status = "streaming"
    assert get_state(c)["on_air"] is True


def test_host_mic_uses_the_same_config_as_live_audio():
    """卓のマイク設定が、ライブ音声設定と**同じ場所**を読むこと。

    別項目にすると「どちらが配信に乗るのか」を利用者が判断できなくなる。
    """
    import inspect
    src = inspect.getsource(streamer_core.StreamerCore.get_host_mic_state)
    assert "live_audio_mic_device" in src and "live_audio_mic_volume" in src
    setter = inspect.getsource(streamer_core.StreamerCore.set_host_mic)
    assert "set_live_audio_devices" in setter, "設定の実体を分けてはいけない"


def test_host_mic_action_is_localhost_only():
    """卓のマイク設定はホスト限定。ゲストに触らせない。"""
    with io.open(os.path.join(BASE_DIR, "api_server.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index('elif path == "/api/karaoke":', src.index("def do_POST"))
    block = src[i:i + 4000]
    assert "is_local_request()" in block
    assert 'action == "host_mic"' in block


def test_ui_has_host_mic_controls_and_reason():
    """卓にマイクの欄・VU・理由の表示があること。"""
    html = _ui_html()
    for needle in ('id="kaHostMicDevice"', 'id="kaHostMicVol"', 'id="kaHostMicVu"',
                   'id="kaHostMicHint"', 'id="kaHostMicState"',
                   'karaokeRenderHostMic(data.host_mic)'):
        assert needle in html, needle
    # 今回詰まった原因そのものを、画面で名指しできていること
    assert "ライブ音声" in html and "モードではありません" in html


# ---------------------------------------------------------------------------
# 13. 伴奏（タスク27-B: YouTube 等をカラオケの伴奏にする）
#
# ★成立の条件は「歌い手が伴奏を聴けること」。ホストが鳴らすだけでは、
#   その音が歌い手へ届くのは配信経由＝数秒後で、歌えない。だから
#   **同じ音を WebSocket で歌い手へ直接配る**。ここを固定する。
# ---------------------------------------------------------------------------
import wave as _wave
from remote_mic import (AccompanimentPlayer, DOWNSTREAM_TYPE_BGM, DOWNSTREAM_HEADER,
                        BGM_STATE_IDLE, BGM_STATE_PAUSED)


def _make_wav(path, seconds=3.0, amp=9000, freq=440):
    import math
    a = array.array("h")
    ph, st = 0.0, 2 * math.pi * freq / SAMPLE_RATE
    for _ in range(int(SAMPLE_RATE * seconds)):
        v = int(amp * math.sin(ph))
        a.extend((v, v))
        ph += st
    with _wave.open(str(path), "wb") as w:
        w.setnchannels(OUTPUT_CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(a.tobytes())
    return str(path)


@pytest.fixture
def bgm_file(tmp_path):
    return _make_wav(tmp_path / "bgm.wav")


def test_bgm_decoder_command_is_48k_stereo_s16le():
    """デコード結果がミキサのバスと一致していること。

    ここがずれると、伴奏だけ速さと音程がおかしくなる。
    """
    pl = AccompanimentPlayer(ffmpeg_cmd="ffmpeg")
    cmd = pl._build_cmd("x.mp3", None, 0)
    assert cmd[cmd.index("-ar") + 1] == str(SAMPLE_RATE)
    assert cmd[cmd.index("-ac") + 1] == str(OUTPUT_CHANNELS)
    assert "s16le" in cmd
    assert "-vn" in cmd, "映像まで引き込むと無駄に重い"


def test_bgm_seek_goes_before_input():
    """-ss は -i の前。後ろに置くと頭から復号してから捨てるので遅い。"""
    pl = AccompanimentPlayer(ffmpeg_cmd="ffmpeg")
    cmd = pl._build_cmd("x.mp3", None, 30)
    assert cmd.index("-ss") < cmd.index("-i")


def test_bgm_passes_http_headers():
    """YouTube の音声URLはヘッダ込みでないと 403 になることがある。"""
    pl = AccompanimentPlayer(ffmpeg_cmd="ffmpeg")
    cmd = pl._build_cmd("https://x/a.m4a", {"User-Agent": "UA"}, 0)
    assert "-headers" in cmd
    assert "User-Agent: UA" in cmd[cmd.index("-headers") + 1]


def test_bgm_load_without_autoplay_stays_paused(bgm_file):
    """読み込んだだけで鳴り出さないこと。

    ★以前ここが壊れていた: pause() が LOADING を見ておらず素通りし、
      デコード開始と同時に鳴り出していた。ホストが選曲した瞬間に
      配信へ曲が流れてしまう。
    """
    pl = AccompanimentPlayer()
    pl.load(bgm_file, title="t", duration=3.0, autoplay=False)
    time.sleep(1.0)
    assert pl.snapshot()["state"] == BGM_STATE_PAUSED
    assert pl.take(FRAMES_PER_TICK) is None
    pl.stop()


def test_bgm_play_and_pause_control_the_position(bgm_file):
    pl = AccompanimentPlayer()
    pl.load(bgm_file, title="t", duration=3.0, autoplay=False)
    time.sleep(0.6)
    pl.play()
    got = 0
    for _ in range(40):
        if pl.take(FRAMES_PER_TICK) is not None:
            got += 1
        time.sleep(0.02)
    assert got > 20, "再生が始まらない"
    pl.pause()
    time.sleep(0.2)
    assert pl.take(FRAMES_PER_TICK) is None, "一時停止中に進んでいる"
    pl.stop()
    assert pl.snapshot()["state"] == BGM_STATE_IDLE


def test_bgm_stop_rewinds_position(bgm_file):
    pl = AccompanimentPlayer()
    pl.load(bgm_file, title="t", duration=3.0)
    time.sleep(0.5)
    for _ in range(20):
        pl.take(FRAMES_PER_TICK)
    pl.stop()
    assert pl.snapshot()["position"] == 0.0
    pl.stop()   # 二重停止で壊れないこと


def test_bgm_volume_is_clamped():
    pl = AccompanimentPlayer()
    assert pl.set_volume(99)["volume"] == 2.0
    assert pl.set_volume(-1)["volume"] == 0.0


def test_bgm_take_is_silent_when_nothing_loaded():
    pl = AccompanimentPlayer()
    assert pl.take(FRAMES_PER_TICK) is None


def test_bgm_reaches_the_stream_bus(session, bgm_file):
    """伴奏が配信バス（＝FFmpegへ行く音）に乗ること。"""
    session.configure(approval_required=False)
    session.bgm.set_volume(1.0)
    session.bgm.load(bgm_file, title="t", duration=3.0)
    session.ensure_mixer()
    path = session.start_recording()
    time.sleep(1.5)
    session.stop_recording()
    session.stop()
    with _wave.open(path, "rb") as wf:
        pcm = array.array("h")
        pcm.frombytes(wf.readframes(wf.getnframes()))
    assert max(abs(v) for v in pcm) > 3000, "伴奏が配信バスに乗っていない"


def test_bgm_is_broadcast_only_to_on_air_participants(session, bgm_file):
    """伴奏は ON AIR の人にだけ配ること。

    待機中の全員へ配ると、ホストの上り帯域が人数倍になる（1人 約768kbps）。
    """
    got = {"active": [], "waiting": []}

    class _Conn:
        def __init__(self, key):
            self.key = key

        def send_binary(self, data):
            got[self.key].append(data)

    session.configure(approval_required=True)
    session.add_participant("a", "歌う人", conn=_Conn("active"))
    session.add_participant("w", "待つ人", conn=_Conn("waiting"))
    session.set_state("a", STATE_ACTIVE)

    session.bgm.load(bgm_file, title="t", duration=3.0)
    session.ensure_mixer()
    time.sleep(1.2)
    session.stop()

    assert len(got["active"]) > 20, "ON AIR の人へ届いていない"
    assert got["waiting"] == [], "待機中の人にまで配っている"


def test_bgm_downstream_frame_shape(session, bgm_file):
    """下りフレームの形（種別バイト＋モノラル48k）が仕様どおりであること。"""
    frames = []

    class _Conn:
        def send_binary(self, data):
            frames.append(data)

    session.configure(approval_required=False)
    session.add_participant("a", "歌う人", conn=_Conn())
    session.set_state("a", STATE_ACTIVE)
    session.bgm.load(bgm_file, title="t", duration=3.0)
    session.ensure_mixer()
    time.sleep(1.0)
    session.stop()

    assert frames
    f = frames[0]
    assert f[0] == DOWNSTREAM_TYPE_BGM
    assert len(f) == DOWNSTREAM_HEADER + FRAMES_PER_TICK * BYTES_PER_SAMPLE
    # 16bit 境界が保たれていること（JS 側で Int16Array を被せるため）
    assert DOWNSTREAM_HEADER % 2 == 0


def test_bgm_downstream_is_pre_volume(session, bgm_file):
    """下りへは**音量を掛ける前**を配ること。

    ホストが配信側の伴奏を絞ったせいで歌い手に聴こえなくなる、では困る。
    """
    frames = []

    class _Conn:
        def send_binary(self, data):
            frames.append(data)

    session.configure(approval_required=False)
    session.add_participant("a", "歌う人", conn=_Conn())
    session.set_state("a", STATE_ACTIVE)
    session.bgm.set_volume(0.0)          # 配信側は無音にする
    session.bgm.load(bgm_file, title="t", duration=3.0)
    session.ensure_mixer()
    time.sleep(1.2)
    session.stop()

    mono = array.array("h")
    for f in frames:
        mono.frombytes(f[DOWNSTREAM_HEADER:])
    assert mono and max(abs(v) for v in mono) > 3000, \
        "配信側を絞ったら歌い手にも聴こえなくなっている"


def test_bgm_downstream_queue_drops_oldest_when_stuck():
    """詰まった相手には古いフレームを捨てること。

    捨てないと遅延が伸び続け、しかも意味のない過去の音を送り続ける。
    """
    p = Participant("id", "x")
    for i in range(remote_mic.BGM_DOWNSTREAM_MAX_CHUNKS + 15):
        p.push_downstream(bytes([i & 0xFF]) * 4)
    assert p.downstream_dropped == 15
    assert len(p._down_q) == remote_mic.BGM_DOWNSTREAM_MAX_CHUNKS


def test_bgm_bus_has_its_own_delay_separate_from_singers(session):
    """伴奏は歌声と**別の遅延**を持つこと。

    伴奏は伴奏側なので固定 500ms。遅延補正スライダで動かしてよいのは
    歌声だけで、伴奏まで一緒に動くと補正が意味を成さない。
    """
    base = ms_to_frames(KARAOKE_BASE_DELAY_MS)
    assert session._bgm_delay._delay_frames == base
    session.configure(offset_ms=300)
    assert session._delay_line._delay_frames == ms_to_frames(KARAOKE_BASE_DELAY_MS + 300)
    assert session._bgm_delay._delay_frames == base, "伴奏まで一緒に動いている"


def test_bgm_appears_in_status_snapshot(session):
    snap = session.status_snapshot()
    assert "bgm" in snap and snap["bgm"]["state"] == BGM_STATE_IDLE
    assert json.dumps(snap, ensure_ascii=False)


def test_offset_suggestion_is_negative_rtt():
    """遅延補正の推奨は −RTT。

    歌い手は伴奏を下りで受け取ってから歌い、その声が上りで戻るので、
    往復ぶん歌声が遅れて届く。
    """
    import streamer_core

    class _Core:
        karaoke = KaraokeSession()
        config = {"karaoke_host_mic_route": False}

    c = _Core()
    for i, rtt in enumerate((40, 60, 80)):
        p, _ = c.karaoke.add_participant(f"id{i}", f"P{i}")
        p.state = STATE_ACTIVE
        p.rtt_ms = rtt
    got, why = streamer_core.StreamerCore.suggest_karaoke_offset(c)
    assert got == -60, got          # 中央値 60ms の符号反転
    assert "60" in why
    c.karaoke.stop()


def test_offset_suggestion_needs_active_participants():
    import streamer_core

    class _Core:
        karaoke = KaraokeSession()
        config = {"karaoke_host_mic_route": False}

    c = _Core()
    assert streamer_core.StreamerCore.suggest_karaoke_offset(c)[0] is None
    p, _ = c.karaoke.add_participant("id", "P")   # 挙手中のまま
    p.rtt_ms = 50
    assert streamer_core.StreamerCore.suggest_karaoke_offset(c)[0] is None
    c.karaoke.stop()


def test_ui_has_accompaniment_controls():
    html = _ui_html()
    for needle in ('id="kaBgmSource"', 'id="kaBgmSeek"', 'id="kaBgmVol"',
                   'karaokeLoadHostBgm()', 'karaokeAutoOffset()',
                   'karaokeOnDownstream'):
        assert needle in html, needle


def test_ui_does_not_send_host_bgm_back_upstream():
    """受け取った伴奏を上りへ混ぜないこと。

    ホストが同じ伴奏を配信バスに乗せているので、送り返すと二重になり、
    しかも往復ぶんずれて山びこになる。
    """
    html = _ui_html()
    i = html.index("function karaokeEnsureBgmChain")
    block = html[i:i + 900]
    assert "hostBgmGain.connect(ka.ac.destination)" in block
    # コメント中の語ではなく、実際の接続が無いことを見る。
    assert "connect(ka.uplink)" not in block, "ホストからの伴奏を上りへ繋いでいる"
    assert "hostBgmGain.connect(ka.uplink" not in html


def test_recording_names_do_not_collide(session):
    """1秒以内に録り直しても、前のテイクを上書きしないこと。

    ファイル名が秒単位なので、停止してすぐ再開すると同じ名前になり、
    前の録音が黙って消えていた（テストの干渉として表面化した）。
    """
    session.ensure_mixer()
    first = session.start_recording()
    time.sleep(0.15)
    session.stop_recording()
    second = session.start_recording()
    time.sleep(0.15)
    session.stop_recording()
    session.stop()
    assert first != second, "同じ秒に録り直すと前のテイクが消える"
    assert os.path.exists(first) and os.path.exists(second)


# ---------------------------------------------------------------------------
# 14. 生演奏の合わせ（タスク27-C）
#
# ★成立の条件は「相手の演奏が聴けること」。片方向でも欠けると合奏にならない。
#   ①ホストの演奏 → 参加者へ    ②参加者の演奏 → ホストへ（監聴）
#   そして **どちらも「自分の音」は返さない**（返ると山びこで演奏できない）。
# ---------------------------------------------------------------------------
import math as _math
from remote_mic import (MonitorClient, DownstreamSender, DOWNSTREAM_TYPE_MONITOR,
                        SYNC_REFERENCE_HOST, SYNC_REFERENCE_PARTICIPANT,
                        HOST_MIC_CAPTURE_LATENCY_MS)


class _Tone:
    """取り込み器のふり。指定周波数のステレオを実時間ぶん返す。"""

    def __init__(self, freq=880, amp=9000):
        self.phase = 0.0
        self.step = 2 * _math.pi * freq / SAMPLE_RATE
        self.amp = amp

    def take(self, n):
        a = array.array("h")
        for _ in range(n):
            v = int(self.amp * _math.sin(self.phase))
            a.extend((v, v))
            self.phase += self.step
        return a


class _Collector:
    def __init__(self):
        self.frames = []

    def send_binary(self, data):
        self.frames.append(data)


def _goertzel(pcm, freq, rate=SAMPLE_RATE):
    """特定周波数の強さ。混ざっていないことを「聞かずに」確かめるために使う。"""
    n = min(len(pcm), rate)
    if n < 1000:
        return 0.0
    k = int(0.5 + n * freq / rate)
    w = 2 * _math.pi * k / n
    coeff = 2 * _math.cos(w)
    s1 = s2 = 0.0
    for i in range(n):
        s0 = pcm[i] + coeff * s1 - s2
        s2, s1 = s1, s0
    return _math.sqrt(abs(s1 * s1 + s2 * s2 - coeff * s1 * s2)) / n


def _collect(frames, want_type):
    out = array.array("h")
    for f in frames:
        if f[0] == want_type:
            out.frombytes(f[DOWNSTREAM_HEADER:])
    return out


def test_host_performance_reaches_participants(session):
    """① ホストの演奏が ON AIR の参加者へ届くこと。"""
    session.configure(approval_required=False)
    session.host_mic_source = _Tone(freq=880)
    sink = _Collector()
    session.add_participant("p", "歌い手", conn=sink)
    session.set_state("p", STATE_ACTIVE)
    session.ensure_mixer()
    time.sleep(1.2)
    session.stop()

    pcm = _collect(sink.frames, DOWNSTREAM_TYPE_BGM)
    assert pcm, "参加者へ何も届いていない"
    assert _goertzel(pcm, 880) > 100, "ホストの演奏が入っていない"


def test_participants_do_not_hear_themselves(session):
    """参加者へ返す音に、その参加者自身の声を混ぜないこと。

    自分の声が往復ぶん遅れて返ってくると、まず歌えない。
    """
    session.configure(approval_required=False)
    session.host_mic_source = _Tone(freq=880)
    sink = _Collector()
    session.add_participant("p", "歌い手", conn=sink)
    session.set_state("p", STATE_ACTIVE)
    session.ensure_mixer()

    ph, st = 0.0, 2 * _math.pi * 440 / SAMPLE_RATE
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.4:
        a = array.array("h")
        for _ in range(FRAMES_PER_TICK):
            a.append(int(8000 * _math.sin(ph)))
            ph += st
        session.push_audio("p", a.tobytes())
        time.sleep(0.02)
    session.stop()

    pcm = _collect(sink.frames, DOWNSTREAM_TYPE_BGM)
    host = _goertzel(pcm, 880)
    own = _goertzel(pcm, 440)
    assert host > 100, "ホストの演奏が入っていない"
    assert own < host * 0.1, f"自分の声が返っている（山びこ）: own={own} host={host}"


def test_monitor_receives_participants(session):
    """② 参加者の演奏がホストの監聴へ届くこと。"""
    session.configure(approval_required=False)
    sink = _Collector()
    session.add_participant("p", "演奏者")
    session.set_state("p", STATE_ACTIVE)
    session.add_monitor("m", conn=sink)
    session.ensure_mixer()

    ph, st = 0.0, 2 * _math.pi * 440 / SAMPLE_RATE
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.4:
        a = array.array("h")
        for _ in range(FRAMES_PER_TICK):
            a.append(int(8000 * _math.sin(ph)))
            ph += st
        session.push_audio("p", a.tobytes())
        time.sleep(0.02)
    session.stop()

    pcm = _collect(sink.frames, DOWNSTREAM_TYPE_MONITOR)
    assert pcm, "監聴へ何も届いていない"
    assert _goertzel(pcm, 440) > 100, "参加者の演奏が入っていない"


def test_monitor_does_not_hear_the_host_own_mic(session):
    """監聴にホスト自身のマイクを混ぜないこと。

    自分の声が遅れて返ると、参加者の演奏に合わせて歌えない。ここが②の肝。
    """
    session.configure(approval_required=False)
    session.host_mic_source = _Tone(freq=880)
    sink = _Collector()
    session.add_participant("p", "演奏者")
    session.set_state("p", STATE_ACTIVE)
    session.add_monitor("m", conn=sink)
    session.ensure_mixer()

    ph, st = 0.0, 2 * _math.pi * 440 / SAMPLE_RATE
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1.4:
        a = array.array("h")
        for _ in range(FRAMES_PER_TICK):
            a.append(int(8000 * _math.sin(ph)))
            ph += st
        session.push_audio("p", a.tobytes())
        time.sleep(0.02)
    session.stop()

    pcm = _collect(sink.frames, DOWNSTREAM_TYPE_MONITOR)
    part = _goertzel(pcm, 440)
    own = _goertzel(pcm, 880)
    assert part > 100, "参加者の演奏が入っていない"
    assert own < part * 0.1, f"ホスト自身のマイクが返っている: own={own} part={part}"


def test_downstream_types_are_not_mixed_up(session):
    """参加者向けと監聴向けが取り違えられないこと。"""
    session.configure(approval_required=False)
    session.host_mic_source = _Tone(freq=880)
    to_part, to_mon = _Collector(), _Collector()
    session.add_participant("p", "歌い手", conn=to_part)
    session.set_state("p", STATE_ACTIVE)
    session.add_monitor("m", conn=to_mon)
    session.ensure_mixer()
    session.push_audio("p", array.array("h", [1000] * FRAMES_PER_TICK).tobytes())
    time.sleep(1.0)
    session.stop()

    assert to_part.frames and to_mon.frames
    assert all(f[0] == DOWNSTREAM_TYPE_BGM for f in to_part.frames)
    assert all(f[0] == DOWNSTREAM_TYPE_MONITOR for f in to_mon.frames)


def test_monitor_is_not_a_participant(session):
    """監聴は参加者一覧に出ないこと（人数にも数えない）。"""
    session.add_monitor("m")
    snap = session.status_snapshot()
    assert snap["participants"] == []
    assert len(snap["monitors"]) == 1
    session.remove_monitor("m")
    assert session.status_snapshot()["monitors"] == []


def test_host_mic_bus_uses_the_bgm_side_delay(session):
    """ホストのマイクは伴奏側と同じ固定 500ms。遅延補正では動かないこと。"""
    base = ms_to_frames(KARAOKE_BASE_DELAY_MS)
    assert session._host_mic_delay._delay_frames == base
    session.configure(offset_ms=-400)
    assert session._delay_line._delay_frames == ms_to_frames(KARAOKE_BASE_DELAY_MS - 400)
    assert session._host_mic_delay._delay_frames == base, "ホストマイクまで動いている"


# ---------------------------------------------------------------------------
# 遅延補正の符号（基準で逆になる）
# ---------------------------------------------------------------------------
def _core_with(session, reference, host_mic_route=False):
    import streamer_core

    class _Core:
        pass

    c = _Core()
    c.karaoke = session
    c.config = {"karaoke_host_mic_route": host_mic_route}
    session.configure(sync_reference=reference)
    return c, streamer_core.StreamerCore.suggest_karaoke_offset


def test_offset_sign_flips_with_the_reference(session):
    """★基準で符号が逆になること。ここを取り違えるとズレが倍になる。

    ・ホスト基準   … 参加者が往復ぶん遅れる → 歌声を早める（負）
    ・参加者基準   … ホストが監聴ぶん遅れる → 参加者を遅らせる（正）
    """
    session.configure(approval_required=False)
    p, _ = session.add_participant("p", "歌い手")
    p.state = STATE_ACTIVE
    p.rtt_ms = 60

    c, suggest = _core_with(session, SYNC_REFERENCE_HOST)
    host_val, host_why = suggest(c)
    assert host_val == -60, host_val

    m = session.add_monitor("m")
    m.lead_ms = 180
    m.rtt_ms = 4
    c, suggest = _core_with(session, SYNC_REFERENCE_PARTICIPANT)
    part_val, part_why = suggest(c)
    assert part_val == 182, part_val        # lead 180 + 片道RTT 2
    assert host_val < 0 < part_val, "符号が逆になっていない"


def test_offset_participant_reference_adds_capture_latency(session):
    """ホストのマイクを Python 経由にしたぶんの遅れも足すこと。"""
    m = session.add_monitor("m")
    m.lead_ms = 100
    m.rtt_ms = 0
    c, suggest = _core_with(session, SYNC_REFERENCE_PARTICIPANT, host_mic_route=True)
    val, why = suggest(c)
    assert val == 100 + HOST_MIC_CAPTURE_LATENCY_MS, val


def test_offset_participant_reference_needs_the_monitor(session):
    """監聴が動いていなければ測れない、と正直に言うこと。"""
    c, suggest = _core_with(session, SYNC_REFERENCE_PARTICIPANT)
    val, why = suggest(c)
    assert val is None
    assert "監聴" in why


def test_sync_reference_is_clamped_to_known_values(session):
    assert session.configure(sync_reference="でたらめ")["sync_reference"] == SYNC_REFERENCE_HOST
    assert session.configure(sync_reference="participant")["sync_reference"] == \
        SYNC_REFERENCE_PARTICIPANT


# ---------------------------------------------------------------------------
# ホストマイクの経路切り替え
# ---------------------------------------------------------------------------
def test_host_mic_capture_command_emits_pcm():
    """取り込みモードでは生PCMを stdout へ流すこと。"""
    cmd = streamer_core.build_host_mic_level_cmd("Mic A", ffmpeg="ffmpeg", capture=True)
    assert cmd[-1] == "-", "stdout へ出していない"
    assert "s16le" in cmd
    assert cmd[cmd.index("-ar") + 1] == str(SAMPLE_RATE)
    assert cmd[cmd.index("-ac") + 1] == str(OUTPUT_CHANNELS)
    # レベルも同時に取れること（卓のVUを止めない）
    assert any("astats" in a for a in cmd)


def test_host_mic_level_only_command_saves_nothing():
    cmd = streamer_core.build_host_mic_level_cmd("Mic A", ffmpeg="ffmpeg", capture=False)
    assert cmd[-2:] == ["-f", "null"] or cmd[-3:-1] == ["-f", "null"]
    assert "s16le" not in cmd


def test_host_mic_take_is_none_without_capture():
    mon = streamer_core.HostMicMonitor()
    assert mon.take(FRAMES_PER_TICK) is None


def test_host_mic_routing_needs_all_three_conditions():
    """カラオケ有効・経路ON・デバイス選択、の3つが揃ったときだけ経由すること。"""
    import streamer_core as sc

    class _Core:
        pass

    c = _Core()
    c.karaoke = KaraokeSession()
    check = sc.StreamerCore.karaoke_host_mic_is_routed

    c.config = {"karaoke_host_mic_route": True, "live_audio_mic_device": "Mic A"}
    c.karaoke.enabled = False
    assert check(c) is False, "カラオケが無効なのに経由している"

    c.karaoke.enabled = True
    c.config["karaoke_host_mic_route"] = False
    assert check(c) is False

    c.config["karaoke_host_mic_route"] = True
    c.config["live_audio_mic_device"] = ""
    assert check(c) is False

    c.config["live_audio_mic_device"] = "Mic A"
    assert check(c) is True
    c.karaoke.stop()


def test_ui_has_reference_and_monitor_controls():
    html = _ui_html()
    for needle in ('id="kaSyncRef"', 'id="kaHostMicRoute"', 'id="kaMonitorOn"',
                   'id="kaMonitorVol"', 'karaokeToggleMonitor()',
                   'karaokeOnMonitorAudio', "role: 'monitor'"):
        assert needle in html, needle


def test_ui_explains_that_the_sign_flips():
    """符号が逆になることを画面で説明していること。ここは必ず混乱する。"""
    html = _ui_html()
    i = html.index("function karaokeRenderSync")
    block = html[i:i + 1200]
    assert "＋方向" in block and "−方向" in block


def test_monitor_role_is_localhost_only():
    """監聴はホストPCからのみ。開けると参加者どうしが盗み聴きできる。"""
    with io.open(os.path.join(BASE_DIR, "karaoke_ws.py"), encoding="utf-8") as f:
        src = f.read()
    i = src.index('== "monitor"')
    block = src[i:i + 400]
    assert "is_local_request()" in block
    assert "forbidden" in block
