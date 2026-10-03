# -*- coding: utf-8 -*-
"""タスク14: 配信先（destination）切替・フォールバック・キーマスクの単体テスト。

FFmpeg も TopazChat も呼ばない。コマンド組み立て・設定クランプ・マスク・
フォールバック判定という「壊れても静かに壊れる」部分だけを検証する。

注意: StreamerCore は実在の config.json を読み書きするため、
各テストは元の config.json を退避し、必ず復元する。
"""

import io
import json
import os
import shutil

import streamer_core
from streamer_core import (
    StreamerCore,
    DEFAULT_CONFIG,
    OUTPUT_MODES,
    RTMP_OUTPUT_MODES,
    TOPAZ_MAX_VIDEO_KBPS,
    TOPAZ_MAX_AUDIO_KBPS,
    STREAM_KEY_MIN_LENGTH,
)

CONFIG_FILE = streamer_core.CONFIG_FILE
BACKUP_FILE = CONFIG_FILE + ".test_destination.bak"


def setup_module(module):
    if os.path.exists(CONFIG_FILE):
        shutil.copy2(CONFIG_FILE, BACKUP_FILE)


def teardown_module(module):
    if os.path.exists(BACKUP_FILE):
        shutil.copy2(BACKUP_FILE, CONFIG_FILE)
        os.remove(BACKUP_FILE)


def make_core():
    """URL組み立て等の単体検証用コア。既定の配信先(topaz)ではなく hls から始める。

    既定のまま作ると、配信先キーを含む save_config() のたびにシンクが作り直され、
    存在しないホストへの到達性チェックが走って退避状態に入る。すると
    get_video_url() がHLSのURLを返し、URL組み立ての検証が別要因で落ちる。
    既定値そのものは test_default_destination_and_fallback_safety が
    DEFAULT_CONFIG に対して直接検証している。
    """
    core = StreamerCore(override_port=8997, override_enable_tunnel=False)
    core.config["output_mode"] = "hls"
    return core


def import_gui_streamer():
    """gui_streamer を安全に import する。

    gui_streamer は import 時に sys.stdout/stderr を TextIOWrapper で包み直す
    （PyInstaller の --noconsole 対策）。そのままだと pytest のキャプチャ用
    一時ファイルがラッパーのGCで閉じられ、以降の全テストが道連れになる。
    包まれたラッパーは detach() して下層バッファを閉じずに切り離す。
    """
    import sys
    saved_out, saved_err = sys.stdout, sys.stderr
    try:
        import gui_streamer
        return gui_streamer
    finally:
        for stream in (sys.stdout, sys.stderr):
            if stream is not saved_out and stream is not saved_err:
                try:
                    stream.detach()
                except Exception:
                    pass
        sys.stdout, sys.stderr = saved_out, saved_err


def test_default_destination_and_fallback_safety():
    """既定は TopazChat（低遅延）。ただし安全側の担保は崩さないこと。

    2026-08-30 に既定を hls から topaz へ変更した。相手は個人運営の無償サービスなので、
    (1) ストリームキーを配布物へ焼き込まず初回に自動生成する、
    (2) 繋がらなければHLSへ自動退避する、の2点が崩れていないことをここで守る。
    """
    print("\n--- 1. Default destination ---")
    assert DEFAULT_CONFIG["output_mode"] == "topaz"
    assert DEFAULT_CONFIG["topaz_stream_key"] == "", "キーを配布物へ焼き込まない"
    assert DEFAULT_CONFIG["rtmp_fallback_to_hls"] is True, "退避を既定で無効にしない"

    core = make_core()
    core.config["output_mode"] = "hls"
    assert core.get_output_mode() == "hls"

    # 未知の値は fail-safe に hls へ落ちる
    core.config["output_mode"] = "youtube_live"
    assert core.get_output_mode() == "hls"
    print("PASS: default is topaz, unknown values fall back to 'hls'.")


def test_hls_sink_command_unchanged():
    """HLS のシンク引数は従来どおり（-c copy / キーフレーム分割）であること。"""
    print("\n--- 2. HLS sink command ---")
    core = make_core()
    core.config["output_mode"] = "hls"
    cmd, target = core.build_sink_command("hls")

    assert cmd is not None
    assert "-f" in cmd and "hls" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "copy"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "delete_segments+append_list" in cmd
    assert "libx264" not in cmd, "HLS路では再エンコードしない"
    # 表示・ログ文言は実態に合わせる（hls経路は Cloudflare トンネル経由であり「ローカル」ではない）
    assert "HLS via" in target
    print("PASS: HLS sink still passes through without re-encoding.")


def test_topaz_sink_command_reencodes_within_limits():
    """TopazChat 路では再エンコード必須。上限内のビットレートとGOP固定を確認する。"""
    print("\n--- 3. TopazChat sink command ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_rtmp_base"] = "rtmp://topaz.chat/live"
    core.config["topaz_stream_key"] = "K" * 40
    core.config["rtmp_video_bitrate_kbps"] = 1500
    core.config["rtmp_audio_bitrate_kbps"] = 192
    core.config["rtmp_fps"] = 30
    core.config["rtmp_gop_seconds"] = 2

    cmd, target = core.build_sink_command("topaz")
    assert cmd is not None

    # 出力は flv/RTMP で、URL末尾はストリームキー
    assert cmd[cmd.index("-f") + 1] == "flv"
    assert cmd[-1] == "rtmp://topaz.chat/live/" + "K" * 40

    # -c copy の素通しでは上限超過も切替時の切断も防げないため再エンコードする
    assert cmd[cmd.index("-c:v") + 1] == "libx264"

    # ★実測(2026-08-30): -tune zerolatency はBフレームと先読みを止め、同じ1500kbpsで
    # PSNR を約1dB落としていた（ビットレートを2000kへ増やすのと同等の劣化を無償で被る）。
    # 稼げるレイテンシは数フレームで、中継とプレイヤーのバッファに比べて無視できる。
    assert "zerolatency" not in cmd, "画質を1dB犠牲にする tune は付けない"
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-b:v") + 1] == "1500k"
    assert cmd[cmd.index("-b:a") + 1] == "192k"

    # 解像度・fps 固定でアイテム切替時のパラメータ変化を消す
    vf = cmd[cmd.index("-vf") + 1]
    assert "scale=1280:720" in vf and "fps=30" in vf
    assert "setpts=PTS+0.150/TB" in vf, "音声のエンコード遅延ぶん映像を遅らせる"

    core.config["rtmp_video_sync_delay_ms"] = 275
    adjusted_cmd, _ = core.build_sink_command("topaz")
    adjusted_vf = adjusted_cmd[adjusted_cmd.index("-vf") + 1]
    assert "setpts=PTS+0.275/TB" in adjusted_vf

    # GOP は fps * gop_seconds で固定
    assert cmd[cmd.index("-g") + 1] == "60"
    assert cmd[cmd.index("-keyint_min") + 1] == "60"

    # ログ表示用の宛先にはキーが出てはいけない
    assert "K" * 40 not in target
    print("PASS: TopazChat sink re-encodes with fixed params and masks the log target.")


def test_bitrate_clamped_to_topaz_limits():
    """上限超過は接続直後に強制切断されるため、設定値の側をクランプする。"""
    print("\n--- 4. Bitrate clamping ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["rtmp_video_bitrate_kbps"] = 8000
    core.config["rtmp_audio_bitrate_kbps"] = 640

    core.clamp_rtmp_bitrates()
    assert core.config["rtmp_video_bitrate_kbps"] == TOPAZ_MAX_VIDEO_KBPS
    assert core.config["rtmp_audio_bitrate_kbps"] == TOPAZ_MAX_AUDIO_KBPS

    # 汎用RTMPは自前サーバーなので上限を課さない
    core.config["output_mode"] = "generic_rtmp"
    core.config["rtmp_video_bitrate_kbps"] = 8000
    core.clamp_rtmp_bitrates()
    assert core.config["rtmp_video_bitrate_kbps"] == 8000
    print("PASS: Topaz limits clamped, generic RTMP left alone.")


def test_stream_key_generated_long_and_masked():
    """短いキーは第三者に配信を乗っ取られる。自動生成は十分に長いこと。"""
    print("\n--- 5. Stream key generation & masking ---")
    core = make_core()
    key = core.generate_stream_key()
    assert len(key) >= STREAM_KEY_MIN_LENGTH, f"key too short: {len(key)}"
    assert core.generate_stream_key() != key, "毎回異なるキーであること"

    masked = core.mask_stream_key(key)
    assert key not in masked
    assert masked.startswith(key[:2]) and masked.endswith(key[-2:])
    assert "*" in masked
    assert core.mask_stream_key("") == ""
    assert core.mask_stream_key("short") == "*****"
    assert core.is_masked_stream_key(masked) is True
    assert core.is_masked_stream_key(key) is False

    # 未設定・短すぎるキーは自動生成で置き換わる
    core.config["topaz_stream_key"] = "test"
    generated = core.ensure_stream_key("topaz", persist=False)
    assert len(generated) >= STREAM_KEY_MIN_LENGTH
    assert generated != "test"
    print("PASS: keys are long, unique, and masked.")


def test_status_never_leaks_key_to_guests():
    """/api/status はゲストにも届く。include_secrets=False で生キーが混ざらないこと。"""
    print("\n--- 6. Status masking ---")
    core = make_core()
    secret = "S" * 40
    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = secret
    core.config["generic_rtmp_key"] = secret

    guest = json.dumps(core.get_status_data(include_secrets=False), ensure_ascii=False)
    assert secret not in guest, "ゲスト向けレスポンスに生キーが漏れている"

    host = json.dumps(core.get_status_data(include_secrets=True), ensure_ascii=False)
    assert secret in host, "ホスト本人には生キーが必要（ワールドに貼るURLのため）"

    # 既定引数（従来の呼び出し）でもマスクされる側であること
    assert secret not in json.dumps(core.get_status_data(), ensure_ascii=False)
    print("PASS: stream key is masked for guests, revealed only for the host.")


def test_video_url_and_remote_url_are_separated():
    """動画URLとWebリモコンURLは別物。QRが焼くのは後者だけ。"""
    print("\n--- 7. URL separation ---")
    core = make_core()
    core.tunnel_raw_url = "https://example.trycloudflare.com"

    core.config["output_mode"] = "hls"
    status = core.get_status_data(include_secrets=True)
    assert status["video_url"].endswith("/stream.m3u8")
    assert status["remote_url"] == "https://example.trycloudflare.com"

    core.config["output_mode"] = "topaz"
    core.config["topaz_rtsp_base"] = "rtspt://topaz.chat/live"
    core.config["topaz_stream_key"] = "T" * 40
    status = core.get_status_data(include_secrets=True)
    assert status["video_url"] == "rtspt://topaz.chat/live/" + "T" * 40
    assert status["remote_url"] == "https://example.trycloudflare.com", "リモコンURLはトンネルのまま"
    print("PASS: video URL follows the destination, remote URL stays on the tunnel.")


def test_fallback_to_hls_when_rtmp_unreachable():
    """相手が落ちていても配信自体は止めない（fail-safe）。"""
    print("\n--- 8. Fallback to HLS ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = "F" * 40
    core.config["rtmp_fallback_to_hls"] = True
    core.config["rtmp_fallback_after_failures"] = 2

    calls = []

    def fake_start(mode):
        calls.append(mode)
        return mode == "hls"   # RTMP は必ず失敗、HLS は成功する状況を再現

    core._start_sink = fake_start
    core._sink_force_restart = True
    assert core.ensure_stream_sink() is True

    assert calls.count("topaz") == 2, f"規定回数だけ再試行すること: {calls}"
    assert calls[-1] == "hls", "最後はHLSへ退避すること"
    assert core.destination_fallback_active is True
    assert core.get_active_output_mode() == "hls", "退避中の実配信先はHLS"
    assert core.get_output_mode() == "topaz", "設定上の配信先は変えない"
    assert core._sink_retry_at > 0, "復帰はバックオフ後に試みる"

    info = core.get_destination_info()
    assert info["fallback_active"] is True
    assert info["active_output_mode"] == "hls"
    print("PASS: RTMP failure falls back to HLS without stopping the stream.")


def test_fallback_disabled_keeps_failure_visible():
    """自動退避を切っている場合は、黙ってHLSへ流さず失敗として返すこと。"""
    print("\n--- 9. Fallback disabled ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = "F" * 40
    core.config["rtmp_fallback_to_hls"] = False
    core.config["rtmp_fallback_after_failures"] = 1

    core._start_sink = lambda mode: False
    core._sink_force_restart = True
    assert core.ensure_stream_sink() is False
    assert core.destination_fallback_active is False
    print("PASS: with fallback disabled the failure is surfaced, not hidden.")


def test_masked_key_is_not_written_back():
    """UIがマスク値を送り返しても、本物のキーを潰さないこと。"""
    print("\n--- 10. Masked key round-trip guard ---")
    core = make_core()
    real = "R" * 40
    core.config["topaz_stream_key"] = real
    core.save_config({"topaz_stream_key": core.mask_stream_key(real)})
    assert core.config["topaz_stream_key"] == real, "マスク値で上書きされてはいけない"

    core.save_config({"topaz_stream_key": "N" * 40})
    assert core.config["topaz_stream_key"] == "N" * 40, "本物の新キーは反映されること"
    print("PASS: masked values are ignored, real keys are accepted.")


def test_generic_rtmp_url_composition():
    print("\n--- 11. Generic RTMP URL ---")
    core = make_core()
    core.config["output_mode"] = "generic_rtmp"
    core.config["generic_rtmp_url"] = "rtmp://localhost/live/"
    core.config["generic_rtmp_key"] = "mykey"
    assert core.get_rtmp_publish_url("generic_rtmp") == "rtmp://localhost/live/mykey"

    core.config["generic_rtmp_key"] = ""
    assert core.get_rtmp_publish_url("generic_rtmp") == "rtmp://localhost/live"

    core.config["generic_rtmp_url"] = ""
    assert core.get_rtmp_publish_url("generic_rtmp") == ""
    cmd, _ = core.build_sink_command("generic_rtmp")
    assert cmd is None, "URL未設定のRTMPシンクは起動させない"
    print("PASS: generic RTMP URL composition and empty-URL guard.")


def test_unreachable_rtmp_detected_before_ffmpeg_starts():
    """★実測由来の回帰防止（2026-08-28）。

    pipe:0 入力のFFmpegは、入力データが流れ始めるまで出力側のRTMP接続を試みない。
    つまり「起動直後にプロセスが生きている」ことは接続成功を意味せず、
    誰もlistenしていない宛先でも起動プローブだけでは失敗を検知できなかった。
    そのため到達性は起動前にTCPで確認する。
    """
    print("\n--- 12. Unreachable RTMP is caught before spawning ffmpeg ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_rtmp_base"] = "rtmp://127.0.0.1:19350/live"   # 誰もlistenしていない
    core.config["topaz_stream_key"] = "U" * 40

    reachable, reason = core.probe_rtmp_endpoint(core.get_rtmp_publish_url("topaz"))
    assert reachable is False and reason, "到達不可を検知できていない"

    spawned = []
    original_popen = streamer_core.subprocess.Popen
    streamer_core.subprocess.Popen = lambda *a, **kw: spawned.append(a) or original_popen(*a, **kw)
    try:
        assert core._start_sink("topaz") is False
    finally:
        streamer_core.subprocess.Popen = original_popen
    assert spawned == [], "到達できない宛先に対してFFmpegを起動してはいけない"
    assert core.destination_last_error

    # ホスト名が解決できない場合も同様に失敗として扱う
    ok, reason = core.probe_rtmp_endpoint("rtmp://this-host-does-not-exist.invalid/live/key")
    assert ok is False and reason
    print("PASS: unreachable destinations fail fast, without spawning ffmpeg.")


def test_failure_count_carries_over_between_calls():
    """『起動しては数秒で切断』を繰り返す相手でも退避条件に到達すること。

    失敗計数を呼び出しごとにリセットすると、ウォッチドッグの再起動と組み合わさって
    永遠に再接続し続け、いつまでもHLSへ退避しない。
    """
    print("\n--- 14. Failure count carries over ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = "C" * 40
    core.config["rtmp_fallback_to_hls"] = True
    core.config["rtmp_fallback_after_failures"] = 3

    # ウォッチドッグが短命な切断を2回数えた状態を再現
    core._sink_fail_count = 2

    calls = []
    core._start_sink = lambda mode: calls.append(mode) or (mode == "hls")
    core._sink_force_restart = True
    assert core.ensure_stream_sink() is True
    assert calls.count("topaz") == 1, f"残り1回だけ試すこと: {calls}"
    assert core.destination_fallback_active is True
    print("PASS: accumulated failures still reach the fallback condition.")


def test_fallback_recovery_actually_retries_primary():
    """★実障害由来の回帰防止（2026-08-28 topaz.chat 全ポート不通）。

    HLSへ退避したあと、バックオフ後の復帰試行で本来の配信先を「実際に試す」こと。
    以前は失敗計数が上限に張り付いたまま復帰処理へ入っていたため、
    ensure_stream_sink() の試行ループが一度も回らず、接続を試さずに退避し直すだけの
    空回りになっていた（＝相手が復旧しても永久にHLSのまま）。
    """
    print("\n--- 18. Recovery actually retries the primary destination ---")
    core = make_core()
    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = "R" * 40
    core.config["rtmp_fallback_to_hls"] = True
    core.config["rtmp_fallback_after_failures"] = 2

    calls = []
    core._start_sink = lambda mode: calls.append(mode) or (mode == "hls")

    core._sink_force_restart = True
    assert core.ensure_stream_sink() is True
    assert calls.count("topaz") == 2, f"初回は規定回数試すこと: {calls}"
    assert core.destination_fallback_active is True
    first_backoff_at = core._sink_retry_at

    # バックオフ満了をシミュレートして、ウォッチドッグ1回分を実行する
    core._sink_retry_at = 0.0
    core.hls_proc = None          # シンク突然死の分岐へ入らないようにする
    core._destination_watchdog_tick()

    assert calls.count("topaz") == 4, f"復帰試行で本来の配信先を実際に試すこと: {calls}"
    assert core.destination_fallback_active is True, "まだ繋がらないなら再びHLSへ退避する"
    assert core._sink_retry_at > 0

    # バックオフは退避の周回数で伸びること（相手を叩き続けない）
    assert core._sink_fallback_rounds == 2
    print("PASS: recovery retries the primary destination and backs off per round.")


def test_probe_timeout_is_bounded_across_address_families():
    """名前解決が複数アドレスを返しても、到達性チェックの所要時間が倍増しないこと。

    socket.create_connection() にホスト名を渡すと IPv4/IPv6 それぞれに満額の
    タイムアウトを使うため、再生スレッドを止める時間が families 倍に伸びていた。
    """
    print("\n--- 19. Probe timeout is bounded ---")
    import time as _time
    core = make_core()
    t0 = _time.time()
    ok, reason = core.probe_rtmp_endpoint("rtmp://127.0.0.1:19350/live/key")
    elapsed = _time.time() - t0
    assert ok is False and reason
    limit = streamer_core.RTMP_CONNECT_TIMEOUT_SECONDS + 2.0
    assert elapsed < limit, f"到達性チェックに {elapsed:.1f}s かかった（上限 {limit}s）"
    print(f"PASS: probe finished in {elapsed:.2f}s (limit {limit}s).")


def test_topaz_endpoint_is_configurable_and_validated():
    """TopazChat のサーバーは利用者が変更できること。ただし不正な値は採用しない。

    個人運営でホストの移転・増設があり得るため書き換え可能にしているが、
    スキームを取り違えた値を保存してしまうと「繋がらない理由が分からない」状態になる。
    """
    print("\n--- 20. TopazChat endpoint form ---")
    core = make_core()

    # 正常系: 別サーバーへ変更でき、末尾スラッシュは正規化される
    core.save_config({"topaz_rtmp_base": "rtmp://jp2.topaz.chat/live/",
                      "topaz_rtsp_base": "rtspt://jp2.topaz.chat/live"})
    assert core.config["topaz_rtmp_base"] == "rtmp://jp2.topaz.chat/live"
    assert core.config["topaz_rtsp_base"] == "rtspt://jp2.topaz.chat/live"
    assert not core.last_config_warnings

    core.config["output_mode"] = "topaz"
    core.config["topaz_stream_key"] = "E" * 40
    assert core.get_rtmp_publish_url("topaz") == "rtmp://jp2.topaz.chat/live/" + "E" * 40
    assert core.get_video_url(include_secrets=True) == "rtspt://jp2.topaz.chat/live/" + "E" * 40

    # 異常系: スキーム違いは採用せず、理由を残す（直前の値は維持）
    core.save_config({"topaz_rtmp_base": "http://example.com/live"})
    assert core.config["topaz_rtmp_base"] == "rtmp://jp2.topaz.chat/live", "不正値で上書きしてはいけない"
    assert core.last_config_warnings, "弾いた理由を返すこと"

    # 空欄は既定のサーバーへ戻す（空のまま保存させない）
    core.save_config({"topaz_rtmp_base": "", "topaz_rtsp_base": ""})
    assert core.config["topaz_rtmp_base"] == DEFAULT_CONFIG["topaz_rtmp_base"]
    assert core.config["topaz_rtsp_base"] == DEFAULT_CONFIG["topaz_rtsp_base"]

    # UI の「既定に戻す」用に、既定値と現在値の両方を返していること
    info = core.get_destination_info()
    for key in ("topaz_rtmp_base", "topaz_rtsp_base",
                "default_topaz_rtmp_base", "default_topaz_rtsp_base"):
        assert info.get(key), f"destination 情報に {key} が無い"
    print("PASS: endpoint is editable, normalized, validated and resettable.")


def test_pts_offset_is_applied_on_the_output_side():
    """★実測由来の回帰防止(2026-08-30)。

    -output_ts_offset は「出力」オプションで、-i より前に置くと黙って無視される
    （実測: 10秒指定しても出力PTSは素通しだった）。無視されると再生アイテムが
    切り替わるたびにPTSが 0 付近へ巻き戻り、受信側で
    「DTS out of order」「Packet corrupt」を起こす。HLSは寛容で表面化しないが、
    RTMP経路では再エンコード入力が壊れる。
    """
    print("\n--- 21. PTS offset は出力側に置く ---")
    core = make_core()
    core.accumulated_pts = 12.5
    opts = core._ts_offset_opts()
    assert opts == ["-output_ts_offset", "12.500"]

    core.accumulated_pts = 0.0
    assert core._ts_offset_opts() == [], "オフセット0のときは付けない"

    # 送出コマンドの中で、入力(-i)より後ろ・出力指定(pipe:1)より前にあること
    src = io.open("streamer_core.py", encoding="utf-8").read()
    assert "_ts_offset_opts(), \"-f\", \"mpegts\", \"pipe:1\"" in src,         "オフセットは出力フォーマット指定の直前へ置くこと"
    assert '"-output_ts_offset", f"{self.accumulated_pts:.3f}"])' not in src,         "入力側(-i より前)に -output_ts_offset を戻してはいけない（黙って無視される）"
    print("PASS: offset is emitted as an output option.")


def test_rtmp_is_paced_close_to_realtime():
    """★実測由来の回帰防止(2026-08-30)。

    HLS用の先読み15秒をRTMPにも適用していたため、経過4秒の時点で約14秒ぶんを
    送出していた（実時間の3.5倍）。低遅延のためにTopazChatを使いながら
    相手サーバーへ詰め込む形になり、遅延も映像の破綻も招く。
    OBS等の実配信と同じく、RTMP系では実時間に近いペースで送る。
    """
    print("\n--- 22. RTMPは実時間ペースで送る ---")
    assert streamer_core.RTMP_BUFFER_AHEAD_SECONDS <= 2.0, "RTMPで先読みを溜めない"
    assert streamer_core.HLS_BUFFER_AHEAD_SECONDS >= 10.0, "HLSは従来どおり先読みする"
    assert streamer_core.RTMP_BUFFER_AHEAD_SECONDS < streamer_core.HLS_BUFFER_AHEAD_SECONDS

    src = io.open("streamer_core.py", encoding="utf-8").read()
    start = src.index("    def relay_stream_data(")
    body = src[start:src.index("\n    def ", start + 10)]
    assert "RTMP_BUFFER_AHEAD_SECONDS if rtmp_live else HLS_BUFFER_AHEAD_SECONDS" in body,         "中継の先読み秒数は配信先で切り替えること"
    assert "BUFFER_AHEAD_SECONDS = 15.0" not in body, "15秒固定に戻してはいけない"
    print("PASS: RTMP paces near realtime, HLS keeps its look-ahead.")


def test_backward_compatible_alias():
    """外部（プラグイン・既存テスト）が呼ぶ旧名を壊していないこと。"""
    print("\n--- 12. ensure_hls_receiver alias ---")
    core = make_core()
    called = []
    core.ensure_stream_sink = lambda: called.append(True) or True
    assert core.ensure_hls_receiver() is True
    assert called == [True]
    print("PASS: ensure_hls_receiver() still delegates to ensure_stream_sink().")


def test_gui_url_helpers_follow_destination():
    """ホストGUIの「ワールド用 動画URL」が配信先に追従し、既定ではキーを伏せること。

    App はウィンドウを開かずに検証したいので、非束縛メソッドへスタブを渡して呼ぶ。
    """
    print("\n--- 16. GUI URL helpers ---")
    gui_streamer = import_gui_streamer()

    core = make_core()
    core.tunnel_raw_url = "https://example.trycloudflare.com"
    core.tunnel_url = "https://example.trycloudflare.com/stream.m3u8"

    class Stub:
        streamer_core = core

    stub = Stub()
    get_video = gui_streamer.App.get_world_video_url
    get_remote = gui_streamer.App.get_remote_url

    # HLS: 動画URLは m3u8、リモコンURLはトンネルのルート
    core.config["output_mode"] = "hls"
    assert get_video(stub).endswith("/stream.m3u8")
    assert get_remote(stub) == "https://example.trycloudflare.com"

    # TopazChat: 動画URLだけが配信先に追従し、リモコンURLは変わらない
    core.config["output_mode"] = "topaz"
    core.config["topaz_rtsp_base"] = "rtspt://topaz.chat/live"
    core.config["topaz_stream_key"] = "G" * 40
    assert get_video(stub, include_secrets=True) == "rtspt://topaz.chat/live/" + "G" * 40
    assert get_remote(stub) == "https://example.trycloudflare.com"

    # 既定（マスク表示）では画面にキーが出ない
    masked = get_video(stub, include_secrets=False)
    assert "G" * 40 not in masked and "*" in masked

    # HLSへ退避中は、退避先のURLが出る（配信できていない先のURLを出さない）
    core.destination_fallback_active = True
    assert get_video(stub).endswith("/stream.m3u8")
    core.destination_fallback_active = False
    print("PASS: GUI shows the destination-aware video URL, masked by default.")


def test_ui_has_destination_controls():
    """UIの配信先操作要素と、規約上必須の注記が存在すること。"""
    print("\n--- 13. UI elements & required notices ---")
    ui_path = os.path.join(os.path.dirname(__file__), "ui", "index.html")
    plugin_path = os.path.join(os.path.dirname(__file__), "plugin", "ui", "index.html")
    content = io.open(ui_path, encoding="utf-8").read()

    for element_id in (
        "settingOutputMode", "settingTopazKey", "btnGenerateTopazKey",
        "settingGenericRtmpUrl", "settingGenericRtmpKey",
        "settingRtmpVideoBitrate", "settingRtmpAudioBitrate", "settingRtmpFallback",
        "destinationVideoUrl", "btnCopyVideoUrl", "destinationStatusBadge",
        "btnRetryDestination", "topazSettingsBlock", "genericRtmpBlock",
    ):
        assert f'id="{element_id}"' in content, f"missing UI element: {element_id}"

    # RTMP系ではローカルHLSを生成しないため、プレビューは成立しない。
    # 404を叩き続けずに理由を出して止めること。
    assert "function stopHlsPreview" in content, "RTMP時にプレビューを停止する処理が必要"
    assert "プレビューできません" in content, "プレビュー不可の理由表示が必要"
    assert "activeOutputMode" in content, "実配信先を追跡する変数が必要"
    # ワールドに貼るURLは配信先に追従すること（HLS固定の .m3u8 ではない）
    assert "data.video_url" in content, "プレイヤー入力用URLは video_url ベースであること"

    # 規約・法務上、表示が必須の注記
    assert "本ソフトはTopazChatの公式ツールではありません" in content
    assert "法人が運営主体" in content
    assert "最大2Mbps" in content
    assert "https://topaz.chat/" in content

    # 公式を騙らないこと: ロゴ・ブランド素材は使わずテキスト名とリンクのみ
    import re as _re
    for tag in _re.findall(r"<img[^>]*>", content, flags=_re.I):
        assert "topaz" not in tag.lower(), f"TopazChatのブランド画像を使ってはいけない: {tag}"
    assert not _re.search(r'(src|background-image)[^;>]*topaz', content, flags=_re.I),         "TopazChatのロゴ・ブランド素材を読み込んではいけない"

    assert content == io.open(plugin_path, encoding="utf-8").read(), \
        "ui/index.html と plugin/ui/index.html は完全一致でなければならない"
    print("PASS: destination UI controls and required notices are present and synced.")


if __name__ == "__main__":
    setup_module(None)
    try:
        for name, fn in sorted(globals().items()):
            if name.startswith("test_") and callable(fn):
                fn()
        print("\nAll destination tests passed.")
    finally:
        teardown_module(None)
