"""参加型カラオケ・セッションの WebSocket ハンドラ（`/ws/audio_session`）。

api_server.py の HTTP ハンドラから呼ばれ、1 接続＝1 スレッドで最後まで面倒を見る。

★プロトコル（設計書 3.2）
  テキスト(JSON) = 制御、バイナリ = 音声（リニアPCM 16bit LE / 48kHz / モノラル）。

  クライアント → サーバ
    {"type":"hello",   "name":"Taro", "password":"1234"}   最初に必ず送る
    {"type":"request_join"}                                挙手（承認制のとき）
    {"type":"mute",    "muted":true}                       本人ミュート
    {"type":"ping",    "t":<クライアント時刻ms>}            回線品質の測定
    {"type":"net",     "rtt":38, "jitter":4}               測定結果の報告
    {"type":"leave"}                                       退出
    <binary>                                               音声チャンク

  サーバ → クライアント
    {"type":"welcome", "id":..., "state":..., "settings":{...}}
    {"type":"state",   "state":"waiting|active|denied", "reason":"..."}
    {"type":"settings","settings":{...}}                   ホストが設定を変えた
    {"type":"pong",    "t":<そのまま返す>, "server_ms":...}
    {"type":"error",   "code":"...", "message":"..."}

★セキュリティ上の考え方
  - 「知らないうちに他人の声が配信へ乗る」ことが最悪の事故なので、
    既定は karaoke_enabled=False かつ承認制。両方を明示的に開けた場合だけ声が乗る。
  - パスワード（PIN）が設定されているときは hello で必ず検証する。
    ブラウザの WebSocket は独自ヘッダを送れないため、既存の X-Web-Password
    ヘッダ方式ではなくハンドシェイク後の最初のメッセージで受け取る。
    URL のクエリに入れない（クエリはログや履歴に残る）。
  - 認証に失敗したら既存のブルートフォース対策（IP単位の指数バックオフ）へ
    そのまま加算する。WebSocket だけ素通しでは対策の意味が無くなる。
"""

import hmac
import json
import time

from ws_server import (
    WebSocketConnection, WebSocketError, perform_handshake, new_client_id,
)
from remote_mic import (
    STATE_WAITING, STATE_ACTIVE, STATE_DENIED, MAX_NAME_LEN,
)

try:
    from streamer_core import log_print
except Exception:
    def log_print(msg):
        print(msg, flush=True)


# hello を待つ猶予。これを過ぎたら切る（開いたまま放置される接続を残さない）。
HELLO_TIMEOUT_SEC = 10.0
# 受信の無通信タイムアウト。クライアントは 1 秒ごとに ping を送るので、
# 30 秒何も来ないなら相手はもう居ない。
IDLE_TIMEOUT_SEC = 30.0
# 1 秒あたりに受け取る音声の上限[バイト]。48kHz/16bit/モノラル = 96,000 B/s なので
# 倍まで許して、それ以上は「送りつけ」とみなす。
MAX_AUDIO_BYTES_PER_SEC = 96000 * 2


def _send_error(conn, code, message):
    try:
        conn.send_json({"type": "error", "code": code, "message": message})
    except WebSocketError:
        pass


def handle_audio_session(handler):
    """`/ws/audio_session` の入口。do_GET から呼ばれる。

    戻り値なし。この関数から戻った時点で接続は閉じている。
    """
    core = handler.streamer_core
    if not core:
        handler.send_json_response(503, {"success": False, "error": "core not ready"})
        return

    session = core.karaoke
    if not session.enabled:
        # まだ開いていない機能に、プロトコルの詳細を漏らす必要はない。
        handler.send_json_response(403, {
            "success": False,
            "error": "Karaoke session is disabled by the host.",
            "karaoke_enabled": False,
        })
        return

    conn = perform_handshake(handler)
    if conn is None:
        handler.send_json_response(400, {"success": False,
                                         "error": "Expected a WebSocket upgrade"})
        return

    client_id = new_client_id()
    participant = None

    def set_timeout(sec):
        # ★受信タイムアウトが無いと、黙り込んだ相手の接続がスレッドごと居座る。
        #   名乗るまでは短く、名乗ってからは ping の間隔（1秒）に対して十分長く。
        try:
            handler.connection.settimeout(sec)
        except Exception:
            pass

    set_timeout(HELLO_TIMEOUT_SEC)
    try:
        participant = _do_hello(handler, conn, session, client_id)
        if participant is None:
            return
        set_timeout(IDLE_TIMEOUT_SEC)
        _serve(handler, conn, session, participant)
    except WebSocketError as e:
        log_print(f"[Karaoke] ws closed: {e}")
    except (OSError, ValueError) as e:
        log_print(f"[Karaoke] ws socket error: {e}")
    finally:
        if participant is not None:
            session.remove_participant(participant.id)
        try:
            conn.close()
        except Exception:
            pass


def _do_hello(handler, conn, session, client_id):
    """最初の hello を検証し、参加者を登録して返す。駄目なら None。"""
    deadline = time.monotonic() + HELLO_TIMEOUT_SEC
    while True:
        if time.monotonic() > deadline:
            _send_error(conn, "timeout", "hello が来ませんでした")
            return None
        msg = conn.recv()
        if msg is None:
            return None
        kind, data = msg
        if kind != "text":
            # 名乗る前に音声を送りつけてくる相手は相手にしない。
            _send_error(conn, "protocol", "hello を先に送ってください")
            return None
        try:
            payload = json.loads(data)
        except ValueError:
            _send_error(conn, "protocol", "JSON として読めません")
            return None
        if not isinstance(payload, dict) or payload.get("type") != "hello":
            continue

        if not _check_password(handler, payload.get("password")):
            log_print(f"[Karaoke] 認証失敗 from {conn.peer}")
            _send_error(conn, "auth", "合言葉（PIN）が違います")
            return None

        name = str(payload.get("name") or "")[:MAX_NAME_LEN]
        participant, err = session.add_participant(
            client_id, name, conn=conn, is_host=handler.is_local_request())
        if participant is None:
            _send_error(conn, "full", err or "参加できません")
            return None

        conn.send_json({
            "type": "welcome",
            "id": participant.id,
            "name": participant.name,
            "state": participant.state,
            "settings": session.settings_snapshot(),
            "server_ms": int(time.time() * 1000),
        })
        return participant


def _check_password(handler, supplied):
    """Web リモコンのパスワードを検証する。

    ★既存の check_web_password_auth() をそのまま呼ばない理由
      あちらはヘッダから候補を拾う作りで、WebSocket には独自ヘッダが無い。
      ここでは hello の値を候補として渡し、**失敗の数え方（ブルートフォース対策）は
      既存の仕組みへ合流させる**。ロックアウト自体は do_GET 入口の
      reject_if_auth_blocked() が既に見ている。
    """
    core = handler.streamer_core
    if handler.is_local_request():
        return True
    configured = str(core.config.get("web_password", "")).strip() if core else ""
    if not configured:
        return True
    candidate = str(supplied or "").strip()
    ok = hmac.compare_digest(candidate, configured)
    if candidate:
        if ok:
            handler.register_auth_success()
        else:
            handler.register_auth_failure()
    return ok


def _serve(handler, conn, session, participant):
    """hello 以降のメッセージを処理し続ける。"""
    audio_window_start = time.monotonic()
    audio_bytes_in_window = 0
    last_state = participant.state
    last_host_muted = participant.host_muted
    last_settings = session.settings_snapshot()

    while True:
        msg = conn.recv()
        if msg is None:
            return
        kind, data = msg

        if kind == "binary":
            # 発言許可が無い相手の音は **受け取った時点で捨てる**。
            # バッファへ積んでから捨てると、承認した瞬間に溜まった過去の音が
            # まとめて流れ出す（実際に起こりうる事故）。
            now = time.monotonic()
            if now - audio_window_start >= 1.0:
                audio_window_start = now
                audio_bytes_in_window = 0
            audio_bytes_in_window += len(data)
            if audio_bytes_in_window > MAX_AUDIO_BYTES_PER_SEC:
                _send_error(conn, "flood", "音声の送信量が多すぎます")
                return
            session.push_audio(participant.id, data)
        else:
            if not _handle_control(conn, session, participant, data):
                return

        # ホスト側の操作（承認・ミュート・設定変更）を本人へ知らせる。
        # 別スレッドから送りつける作りにすると送信の直列化が要るので、
        # 受信ループのついでに差分だけ通知する（音声が来ている間は 20ms ごとに回る）。
        if participant.state != last_state or participant.host_muted != last_host_muted:
            last_state = participant.state
            last_host_muted = participant.host_muted
            conn.send_json({"type": "state", "state": participant.state,
                            "host_muted": participant.host_muted})
            if participant.state == STATE_DENIED:
                return

        current = session.settings_snapshot()
        if current != last_settings:
            last_settings = current
            conn.send_json({"type": "settings", "settings": current})


def _handle_control(conn, session, participant, text):
    """制御メッセージ 1 件を処理する。接続を続けるなら True。"""
    try:
        payload = json.loads(text)
    except ValueError:
        return True
    if not isinstance(payload, dict):
        return True
    mtype = payload.get("type")

    if mtype == "ping":
        conn.send_json({"type": "pong", "t": payload.get("t"),
                        "server_ms": int(time.time() * 1000)})
        return True

    if mtype == "net":
        try:
            participant.rtt_ms = max(0, min(5000, int(payload.get("rtt", 0))))
            participant.jitter_ms = max(0, min(5000, int(payload.get("jitter", 0))))
        except (TypeError, ValueError):
            pass
        return True

    if mtype == "request_join":
        if participant.state == STATE_ACTIVE:
            return True
        # 承認制でなければ、挙手はそのまま発言許可になる。
        new_state = STATE_WAITING if session.approval_required else STATE_ACTIVE
        session.set_state(participant.id, new_state)
        log_print(f"[Karaoke] 挙手 name={participant.name!r} -> {new_state}")
        return True

    if mtype == "mute":
        participant.self_muted = bool(payload.get("muted", True))
        return True

    if mtype == "leave":
        return False

    return True
