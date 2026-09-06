"""最小構成の WebSocket(RFC 6455) サーバ実装。

★なぜ自前で書くか
  本体の HTTP サーバは標準ライブラリの `http.server` + `socketserver.ThreadingMixIn`
  だけで動いており、外部フレームワークを一切持っていない。PyInstaller の onefile
  配布を軽く保つという方針（設計書 1.2「配布性の維持」）があるため、`websockets` や
  `aiohttp` を新たに足さずに済ませたい。サーバ側に必要なのは
  「ハンドシェイク」「マスク解除」「フレーム組み立て」の3つだけなので自前で足りる。

★スレッドモデル
  `ThreadingMixIn` は 1 リクエスト 1 スレッド。アップグレード後はそのスレッドを
  そのまま接続の寿命として使い切る（do_GET から戻らない）。接続ごとに 1 スレッドなので、
  参加者が数人という前提では十分。

★安全側の作り
  - クライアント→サーバのフレームは **必ず** マスクされている必要がある（RFC 6455 5.1）。
    マスクされていないフレームは即切断する。
  - ペイロード長に上限を設ける。上限が無いと、64bit 長を名乗るだけで
    こちらのメモリを食い尽くせる。
"""

import base64
import hashlib
import os
import socket
import struct
import threading

# RFC 6455 で定められた固定の GUID。
WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OPCODE_CONT = 0x0
OPCODE_TEXT = 0x1
OPCODE_BINARY = 0x2
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

# 1 フレームの上限。音声チャンクは 100ms でも 9.6kB 程度なので 64kB あれば十分。
MAX_PAYLOAD_BYTES = 64 * 1024
# 分割フレームを繋いだときの上限。こちらも同じ理由で頭を押さえる。
MAX_MESSAGE_BYTES = 256 * 1024


class WebSocketError(Exception):
    """プロトコル違反・切断など、接続を畳むべき事象。"""


def compute_accept(key: str) -> str:
    """Sec-WebSocket-Accept を計算する（RFC 6455 4.2.2）。"""
    digest = hashlib.sha1(key.strip().encode("ascii", "ignore") + WS_GUID).digest()
    return base64.b64encode(digest).decode("ascii")


def is_websocket_upgrade(headers) -> bool:
    """このリクエストが WebSocket へのアップグレード要求かどうか。

    Connection ヘッダは "keep-alive, Upgrade" のようにカンマ区切りで複数入ることが
    あるため（実際 Firefox がそう送る）、完全一致ではなくトークン一致で見る。
    """
    upgrade = (headers.get("Upgrade") or "").strip().lower()
    if upgrade != "websocket":
        return False
    connection = (headers.get("Connection") or "").lower()
    tokens = {t.strip() for t in connection.split(",")}
    if "upgrade" not in tokens:
        return False
    if (headers.get("Sec-WebSocket-Version") or "").strip() != "13":
        return False
    return bool((headers.get("Sec-WebSocket-Key") or "").strip())


class WebSocketConnection:
    """アップグレード済みのソケットを読み書きする。

    送信は複数スレッドから呼ばれる（音声ミキサのブロードキャストと制御応答）ため、
    送信側だけロックで直列化する。受信は所有スレッド 1 本からしか呼ばない。
    """

    def __init__(self, sock, rfile, wfile, peer=""):
        self.sock = sock
        self.rfile = rfile
        self.wfile = wfile
        self.peer = peer
        self._send_lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------
    # 受信
    # ------------------------------------------------------------------
    def _read_exact(self, n):
        """n バイトきっちり読む。足りないまま切れたら WebSocketError。"""
        if n <= 0:
            return b""
        chunks = []
        remaining = n
        while remaining > 0:
            data = self.rfile.read(remaining)
            if not data:
                raise WebSocketError("connection closed while reading")
            chunks.append(data)
            remaining -= len(data)
        return b"".join(chunks)

    def _read_frame(self):
        """1 フレームを読み、(fin, opcode, payload) を返す。"""
        header = self._read_exact(2)
        b0, b1 = header[0], header[1]
        fin = bool(b0 & 0x80)
        # RSV1-3 はこちらでは拡張を一切ネゴシエートしないので、立っていたら違反。
        if b0 & 0x70:
            raise WebSocketError("reserved bits set")
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F

        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]

        if length > MAX_PAYLOAD_BYTES:
            raise WebSocketError(f"payload too large: {length}")

        # クライアントは必ずマスクする。していなければ攻撃かバグなので切る。
        if not masked:
            raise WebSocketError("client frame is not masked")

        mask = self._read_exact(4)
        payload = bytearray(self._read_exact(length))
        for i in range(len(payload)):
            payload[i] ^= mask[i & 3]
        return (fin, opcode, bytes(payload))

    def recv(self):
        """次のメッセージを (kind, data) で返す。

        kind は "text"（str）か "binary"（bytes）。制御フレーム（ping/close）は
        この中で処理し、呼び出し側には見せない。close を受けたら None を返す。
        """
        frames = []
        message_opcode = None
        total = 0
        while True:
            fin, opcode, payload = self._read_frame()

            if opcode == OPCODE_CLOSE:
                self._send_frame(OPCODE_CLOSE, b"")
                return None
            if opcode == OPCODE_PING:
                self._send_frame(OPCODE_PONG, payload)
                continue
            if opcode == OPCODE_PONG:
                continue

            if opcode == OPCODE_CONT:
                if message_opcode is None:
                    raise WebSocketError("continuation without start")
            elif opcode in (OPCODE_TEXT, OPCODE_BINARY):
                if message_opcode is not None:
                    raise WebSocketError("new message while fragmented")
                message_opcode = opcode
            else:
                raise WebSocketError(f"unknown opcode: {opcode}")

            frames.append(payload)
            total += len(payload)
            if total > MAX_MESSAGE_BYTES:
                raise WebSocketError("message too large")

            if fin:
                data = b"".join(frames)
                if message_opcode == OPCODE_TEXT:
                    try:
                        return ("text", data.decode("utf-8"))
                    except UnicodeDecodeError:
                        raise WebSocketError("invalid utf-8 in text frame")
                return ("binary", data)

    # ------------------------------------------------------------------
    # 送信
    # ------------------------------------------------------------------
    def _send_frame(self, opcode, payload: bytes):
        if self._closed:
            return
        length = len(payload)
        if length < 126:
            header = struct.pack(">BB", 0x80 | opcode, length)
        elif length < 65536:
            header = struct.pack(">BBH", 0x80 | opcode, 126, length)
        else:
            header = struct.pack(">BBQ", 0x80 | opcode, 127, length)
        with self._send_lock:
            if self._closed:
                return
            try:
                self.wfile.write(header + payload)
                self.wfile.flush()
            except (OSError, ValueError) as e:
                # 相手が消えた。以後の送信は無意味なので閉じた扱いにする。
                self._closed = True
                raise WebSocketError(f"send failed: {e}")

    def send_text(self, text: str):
        self._send_frame(OPCODE_TEXT, text.encode("utf-8"))

    def send_binary(self, data: bytes):
        self._send_frame(OPCODE_BINARY, data)

    def send_json(self, obj):
        import json
        self.send_text(json.dumps(obj, ensure_ascii=False))

    def close(self):
        if self._closed:
            return
        try:
            self._send_frame(OPCODE_CLOSE, b"")
        except Exception:
            pass
        self._closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    @property
    def closed(self):
        return self._closed


def perform_handshake(handler):
    """`http.server` のハンドラ上で 101 応答を返し、WebSocketConnection を作る。

    ★`self.send_response()` を使わない理由
      本体のサーバは protocol_version を設定していないので HTTP/1.0 を名乗る。
      101 Switching Protocols は HTTP/1.1 の応答なので、ここだけ生のバイト列で
      書く。ついでに `end_headers()` が挟む CORS ヘッダ（Access-Control-*）も
      避けられる。ハンドシェイク応答に余計なヘッダを足す必要はない。

    アップグレードできなければ None を返す（呼び出し側が 400 を返す）。
    """
    if not is_websocket_upgrade(handler.headers):
        return None
    key = (handler.headers.get("Sec-WebSocket-Key") or "").strip()
    accept = compute_accept(key)
    response = (
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    ).encode("ascii")
    handler.wfile.write(response)
    handler.wfile.flush()

    # ★アップグレード後は keep-alive の話ではないので、ハンドラ側の後処理を止める。
    handler.close_connection = True
    peer = ""
    try:
        peer = "%s:%s" % handler.client_address[:2]
    except Exception:
        pass
    return WebSocketConnection(handler.connection, handler.rfile, handler.wfile, peer=peer)


def new_client_id():
    """参加者を識別する短いID。推測されても困らないが、被らないことが大事。"""
    return os.urandom(8).hex()
