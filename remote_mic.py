"""参加型カラオケ・セッション（リモートマイク）のホスト側エンジン。

設計書: karaoke_session_design.md
役割: WebSocket で届いた参加者ごとの PCM を、ジッタバッファで均し、
      音量・PAN・リバーブを掛けて 1 本のステレオ PCM にミックスし、
      名前付きパイプ経由で配信中の FFmpeg へ流し込む。

────────────────────────────────────────────────────────────────────
★設計上の重要な判断（設計書からの意図的な逸脱を含む）

1) **ミックスは FFmpeg ではなく Python で行う**
   設計書 5.2 は参加者ごとに FFmpeg 入力を立て、`pan` / `aecho` / `amix` で
   混ぜる案だった。しかし FFmpeg のフィルタグラフは **プロセス起動時に固定** される。
   参加者が途中で入退室するたびに配信そのものを張り直すことになり、
   カラオケ大会という「人が出入りし続ける」用途では破綻する。
   そこで Python 側で 1 本のステレオバスへ混ぜ、FFmpeg からは
   **常に 1 入力**に見せる。音量・PAN・リバーブ・遅延補正は生放送中に変えられる。

2) **遅延補正（±500ms）は「伴奏を先に 500ms 遅らせておく」ことで実現する**
   歌声は必ずネットワーク分だけ遅れて届くので、素直に作ると「歌声を遅らせる」
   方向にしか直せない。そこでカラオケ有効時は **伴奏側に固定 500ms の下駄**
   (`adelay`) を履かせ、マイクバスの Python 側遅延を `500 + offset` にする。
   これで offset は −500〜+500 の全域が配信を止めずに効く。
   代償は全体が 500ms 遅れることだが、VRChat 側の再生は元々秒単位で遅れるので実害がない。

3) **numpy を使わない**
   配布は PyInstaller の onefile。1 チャンク(20ms) は 960 サンプルしかなく、
   参加者 4 人でも毎秒 40 万回程度の演算にしかならない。純 Python で足りる。
   （Python 3.13 で `audioop` が標準ライブラリから消えているため、そちらにも頼れない）
────────────────────────────────────────────────────────────────────
"""

import array
import collections
import ctypes
import json
import os
import struct
import subprocess
import sys
import threading
import time
import uuid
import wave

# ★streamer_core を **モジュール先頭で import しない**。
#   streamer_core 側がこのモジュールを import するため、先頭で相互に呼ぶと
#   片方が初期化途中の状態で読まれて壊れる。ログだけ遅延で借りる。
def log_print(msg):
    try:
        from streamer_core import log_print as _core_log
        _core_log(msg)
    except Exception:
        print(msg, flush=True)


# 録音の保存先は **exe の隣**。onefile の展開先(sys._MEIPASS)は終了時に消えるので、
# そこへ書くと録音が丸ごと失われる。
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# ★streamer_core と同じ値をここでも持つ。あちらを先頭 import できないため。
#   付け忘れると、伴奏をデコードするたびに黒いコンソールが一瞬開く。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def kill_proc(proc, timeout=2.0):
    """子プロセスを確実に終わらせる。streamer_core の同名関数と同じ役割。

    ★terminate() だけで済ませない。パイプ待ちで固まった ffmpeg は
      terminate に反応しないことがあり、居座って次の再生を邪魔する。
    """
    if not proc:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=timeout)
            except Exception:
                proc.kill()
                proc.wait(timeout=timeout)
    except Exception:
        pass


# --------------------------------------------------------------------------
# 定数
# --------------------------------------------------------------------------
SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 2          # PAN を効かせるためミックス後はステレオ
BYTES_PER_SAMPLE = 2         # s16le
FRAME_MS = 20                # ミキサの 1 刻み
FRAMES_PER_TICK = SAMPLE_RATE * FRAME_MS // 1000    # 960

# 遅延モード（設計書 5.1）
LATENCY_MODES = {
    "low": 40,       # 掛け合いトーク・カラオケ
    "stable": 120,   # 弾き語り・楽器（音切れ耐性重視）
}
DEFAULT_LATENCY_MODE = "low"

# ジッタバッファが溜まりすぎたときに捨て始める深さ。目標の 4 倍。
JITTER_MAX_FACTOR = 4.0

# 伴奏側に履かせる下駄（上の設計判断 2）
KARAOKE_BASE_DELAY_MS = 500
# 遅延補正スライダの可動域
KARAOKE_OFFSET_MIN_MS = -KARAOKE_BASE_DELAY_MS
KARAOKE_OFFSET_MAX_MS = KARAOKE_BASE_DELAY_MS

# リバーブ（設計書の aecho 相当を Python の 1 段フィードバック遅延で近似）
REVERB_PRESETS = {
    "off": None,
    "weak": (30, 0.20),
    "mid": (45, 0.35),
    "strong": (60, 0.50),
}
DEFAULT_REVERB = "off"

# 参加者の状態
STATE_WAITING = "waiting"    # 挙手中（ホストの承認待ち）
STATE_ACTIVE = "active"      # 発言許可済み
STATE_DENIED = "denied"      # 拒否された

MAX_PARTICIPANTS = 8
# 参加者 1 人が名乗れる名前の長さ。長い名前でホストUIを壊されないように切る。
MAX_NAME_LEN = 24

# レベル計（VU）の減衰。ピークホールドを緩やかに落とす。
LEVEL_DECAY_PER_TICK = 0.86

SILENCE_TICK = b"\x00" * (FRAMES_PER_TICK * OUTPUT_CHANNELS * BYTES_PER_SAMPLE)

# 歌い手へ配る伴奏の控えの上限（1人あたり）。20ms × 25 = 0.5 秒。
# これ以上溜めても、届く頃には歌う役に立たない音になっている。
BGM_DOWNSTREAM_MAX_CHUNKS = 25


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def pan_gains(pan):
    """PAN 値 (-1.0=左 〜 0=中央 〜 +1.0=右) から左右ゲインを返す。

    等パワー則（sin/cos）ではなく素直な線形を使う。中央で 1.0/1.0 になるので、
    「PAN を触ったら音量まで変わった」という混乱が起きない。
    """
    p = clamp(float(pan), -1.0, 1.0)
    left = 1.0 - max(0.0, p)
    right = 1.0 + min(0.0, p)
    return (left, right)


def ms_to_frames(ms):
    return int(SAMPLE_RATE * max(0, int(ms)) / 1000)


# --------------------------------------------------------------------------
# ジッタバッファ
# --------------------------------------------------------------------------
class JitterBuffer:
    """1 参加者ぶんのモノラル PCM を溜めて、一定量になってから吐き出す。

    ★「溜めてから出す」ことが肝。ネットワークの揺らぎでチャンクの到着間隔は
      ばらつくので、いきなり再生すると隙間が音切れになる。目標の深さまで
      貯めてから（prime）出し始め、以後は空になっても無音で埋めて時間軸を守る。
    """

    def __init__(self, target_ms=LATENCY_MODES[DEFAULT_LATENCY_MODE]):
        self._lock = threading.Lock()
        self._buf = bytearray()
        self._primed = False
        self.underruns = 0
        self.drops = 0
        self.received_bytes = 0
        self.set_target(target_ms)

    def set_target(self, target_ms):
        with self._lock:
            self.target_ms = max(10, int(target_ms))
            self._target_bytes = ms_to_frames(self.target_ms) * BYTES_PER_SAMPLE
            self._max_bytes = int(self._target_bytes * JITTER_MAX_FACTOR)
            # 目標を下げたときに溜まりすぎが残らないよう、その場で切り詰める。
            if len(self._buf) > self._max_bytes:
                self._buf = self._buf[-self._max_bytes:]

    def push(self, pcm_bytes):
        """モノラル s16le を積む。奇数バイトは前段の壊れたフレームなので捨てる。"""
        if not pcm_bytes:
            return
        if len(pcm_bytes) & 1:
            pcm_bytes = pcm_bytes[:-1]
        with self._lock:
            self._buf += pcm_bytes
            self.received_bytes += len(pcm_bytes)
            if len(self._buf) > self._max_bytes:
                # 溜まりすぎ＝相手が速すぎるか、こちらが詰まった。古い方を捨てて
                # 遅延を取り戻す。捨てないと遅延が単調増加して二度と戻らない。
                excess = len(self._buf) - self._target_bytes
                del self._buf[:excess]
                self.drops += 1

    def take(self, n_frames):
        """n_frames ぶんの array('h') を返す。足りなければ無音で埋める。"""
        need = n_frames * BYTES_PER_SAMPLE
        with self._lock:
            if not self._primed:
                if len(self._buf) < self._target_bytes:
                    return array.array("h", bytes(need))
                self._primed = True
            if len(self._buf) < need:
                self.underruns += 1
                self._primed = False      # 溜め直す（連続の途切れを避ける）
                chunk = bytes(self._buf)
                self._buf.clear()
                chunk += bytes(need - len(chunk))
            else:
                chunk = bytes(self._buf[:need])
                del self._buf[:need]
        out = array.array("h")
        out.frombytes(chunk)
        if sys.byteorder != "little":
            out.byteswap()
        return out

    def depth_ms(self):
        with self._lock:
            frames = len(self._buf) // BYTES_PER_SAMPLE
        return int(frames * 1000 / SAMPLE_RATE)

    def reset(self):
        with self._lock:
            self._buf.clear()
            self._primed = False


# --------------------------------------------------------------------------
# 参加者
# --------------------------------------------------------------------------
class Participant:
    def __init__(self, client_id, name, is_host=False):
        self.id = client_id
        self.name = name
        self.is_host = is_host
        self.state = STATE_WAITING
        self.self_muted = False       # 本人がミュートした
        self.host_muted = False       # ホストがミュートした
        self.volume = 1.0             # 0.0〜2.0
        self.pan = 0.0                # -1.0〜1.0
        self.buffer = JitterBuffer()
        self.level = 0.0              # 0.0〜1.0（ホストUIのVU用）
        self.rtt_ms = 0
        self.jitter_ms = 0
        self.joined_at = time.time()
        self.conn = None              # WebSocketConnection（送信用）

        # ---- 下り（伴奏を歌い手へ配る）----
        # ★ミキサのスレッドから直接 send してはいけない。相手の回線が詰まると
        #   ソケット書き込みがブロックし、**ミキサごと止まって全員の音が壊れる**。
        #   上限付きの控えに積み、この参加者専用のスレッドが送り出す。
        self._down_q = collections.deque()
        self._down_cv = threading.Condition()
        self._down_stop = False
        self._down_thread = None
        self.downstream_dropped = 0

    # ------------------------------------------------------------------
    def start_downstream(self):
        if self._down_thread:
            return
        self._down_stop = False
        self._down_thread = threading.Thread(
            target=self._downstream_loop, name=f"karaoke-down-{self.id[:6]}",
            daemon=True)
        self._down_thread.start()

    def stop_downstream(self):
        with self._down_cv:
            self._down_stop = True
            self._down_q.clear()
            self._down_cv.notify_all()
        self._down_thread = None

    def push_downstream(self, data):
        """伴奏フレームを控えに積む。溜まりすぎたら**古い方を捨てる**。

        捨てないと、詰まった相手のために遅延が伸び続け、しかも意味のない
        過去の音を後生大事に送ることになる。
        """
        with self._down_cv:
            if self._down_stop:
                return
            if len(self._down_q) >= BGM_DOWNSTREAM_MAX_CHUNKS:
                self._down_q.popleft()
                self.downstream_dropped += 1
            self._down_q.append(data)
            self._down_cv.notify()

    def _downstream_loop(self):
        while True:
            with self._down_cv:
                while not self._down_q and not self._down_stop:
                    self._down_cv.wait(0.25)
                if self._down_stop:
                    return
                chunk = self._down_q.popleft()
            conn = self.conn
            if not conn:
                continue
            try:
                conn.send_binary(chunk)
            except Exception:
                # 相手が消えた。受信側のループが後始末をするので、ここは黙って降りる。
                return

    @property
    def audible(self):
        return (self.state == STATE_ACTIVE
                and not self.self_muted
                and not self.host_muted
                and self.volume > 0.0)

    def snapshot(self):
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "self_muted": self.self_muted,
            "host_muted": self.host_muted,
            "volume": round(self.volume, 2),
            "pan": round(self.pan, 2),
            "level": round(self.level, 3),
            "rtt_ms": int(self.rtt_ms),
            "jitter_ms": int(self.jitter_ms),
            "buffer_ms": self.buffer.depth_ms(),
            "underruns": self.buffer.underruns,
            "drops": self.buffer.drops,
            "is_host": self.is_host,
            "joined_at": self.joined_at,
        }


# --------------------------------------------------------------------------
# 名前付きパイプ（FFmpeg への出口）
# --------------------------------------------------------------------------
_IS_WINDOWS = (os.name == "nt")

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _HANDLE = ctypes.c_void_p
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    _PIPE_ACCESS_OUTBOUND = 0x00000002
    _PIPE_TYPE_BYTE = 0x00000000
    _PIPE_WAIT = 0x00000000
    _ERROR_PIPE_CONNECTED = 535
    _ERROR_NO_DATA = 232
    _ERROR_BROKEN_PIPE = 109

    _kernel32.CreateNamedPipeW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    _kernel32.CreateNamedPipeW.restype = _HANDLE
    _kernel32.ConnectNamedPipe.argtypes = [_HANDLE, ctypes.c_void_p]
    _kernel32.ConnectNamedPipe.restype = ctypes.c_int
    _kernel32.WriteFile.argtypes = [_HANDLE, ctypes.c_void_p, ctypes.c_uint32,
                                    ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    _kernel32.WriteFile.restype = ctypes.c_int
    _kernel32.DisconnectNamedPipe.argtypes = [_HANDLE]
    _kernel32.DisconnectNamedPipe.restype = ctypes.c_int
    _kernel32.CloseHandle.argtypes = [_HANDLE]
    _kernel32.CloseHandle.restype = ctypes.c_int
    _kernel32.CancelIoEx.argtypes = [_HANDLE, ctypes.c_void_p]
    _kernel32.CancelIoEx.restype = ctypes.c_int


class NamedPipeSink:
    """`\\\\.\\pipe\\...` を **こちら側がサーバ**として作り、FFmpeg に読ませる。

    ★向きに注意
      タスク25 のアプリ音声は補助exeが stdout に吐いたものを FFmpeg の stdin
      (`pipe:0`) に直結していた。stdin はもう埋まっているので、ここは
      タスク26 のウィンドウキャプチャと同じ「名前付きパイプ」方式を採る。
      ただし向きは逆で、**Python がサーバ・FFmpeg がクライアント**。
      したがって **パイプを作ってから FFmpeg を起こす**（順序を逆にすると
      FFmpeg が存在しないパイプを開きに行って即死する）。

    ★書き込みは専用スレッド
      WriteFile は FFmpeg が読むまでブロックする。ミキサを直接ブロックさせると
      時間軸が壊れるので、間に上限付きのキューを挟む。
    """

    def __init__(self, name=None, buffer_bytes=SAMPLE_RATE * OUTPUT_CHANNELS * BYTES_PER_SAMPLE):
        self.name = name or (r"\\.\pipe\vrc_remote_mic_%d_%s"
                             % (os.getpid(), uuid.uuid4().hex[:8]))
        self._buffer_bytes = buffer_bytes
        self._handle = None
        self._thread = None
        self._stop = threading.Event()
        self._queue = []
        self._queue_lock = threading.Condition()
        # 1 秒ぶん溜まったら古い方を捨てる。捨てないと遅延が伸び続ける。
        self._max_queue_chunks = max(4, 1000 // FRAME_MS)
        self.connected = False
        self.written_bytes = 0
        self.dropped_chunks = 0

    def start(self):
        """パイプを作って接続待ちスレッドを起こす。失敗したら False。"""
        if not _IS_WINDOWS:
            log_print("[Karaoke] 名前付きパイプは Windows 専用。リモートマイクを無効化")
            return False
        handle = _kernel32.CreateNamedPipeW(
            self.name,
            _PIPE_ACCESS_OUTBOUND,
            _PIPE_TYPE_BYTE | _PIPE_WAIT,
            1,                      # インスタンスは 1 本だけ
            self._buffer_bytes,     # 出力バッファ
            0,                      # 入力バッファ（こちらは書くだけ）
            0,
            None)
        if not handle or handle == _INVALID_HANDLE_VALUE:
            err = ctypes.get_last_error()
            log_print(f"[Karaoke] CreateNamedPipe 失敗: {self.name} (GetLastError={err})")
            return False
        self._handle = handle
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="karaoke-pipe", daemon=True)
        self._thread.start()
        log_print(f"[Karaoke] named pipe ready: {self.name}")
        return True

    def write(self, data: bytes):
        with self._queue_lock:
            if self._stop.is_set():
                return
            if len(self._queue) >= self._max_queue_chunks:
                self._queue.pop(0)
                self.dropped_chunks += 1
            self._queue.append(data)
            self._queue_lock.notify()

    def _pump(self):
        h = self._handle
        n_written = ctypes.c_uint32(0)
        while not self._stop.is_set():
            # 1) FFmpeg の接続を待つ。ここは相手が来るまで返ってこない。
            ok = _kernel32.ConnectNamedPipe(h, None)
            if not ok and ctypes.get_last_error() != _ERROR_PIPE_CONNECTED:
                if self._stop.is_set():
                    break
                err = ctypes.get_last_error()
                log_print(f"[Karaoke] ConnectNamedPipe 失敗 (GetLastError={err})")
                time.sleep(0.2)
                continue
            self.connected = True
            log_print("[Karaoke] FFmpeg がリモートマイクのパイプに接続しました")

            # 2) 繋がっている間はひたすら書く。
            while not self._stop.is_set():
                with self._queue_lock:
                    while not self._queue and not self._stop.is_set():
                        self._queue_lock.wait(0.2)
                    if self._stop.is_set():
                        break
                    chunk = self._queue.pop(0)
                buf = ctypes.create_string_buffer(chunk, len(chunk))
                ok = _kernel32.WriteFile(h, buf, len(chunk), ctypes.byref(n_written), None)
                if not ok:
                    err = ctypes.get_last_error()
                    if err in (_ERROR_NO_DATA, _ERROR_BROKEN_PIPE):
                        log_print("[Karaoke] FFmpeg 側がパイプを閉じました（再接続を待ちます）")
                    else:
                        log_print(f"[Karaoke] WriteFile 失敗 (GetLastError={err})")
                    break
                self.written_bytes += n_written.value

            # 3) 相手が去った。切り離して次の接続を待つ（配信の張り直しに追随する）。
            self.connected = False
            try:
                _kernel32.DisconnectNamedPipe(h)
            except Exception:
                pass

    def stop(self):
        self._stop.set()
        with self._queue_lock:
            self._queue.clear()
            self._queue_lock.notify_all()
        if self._handle:
            # ★ブロック中の ConnectNamedPipe / WriteFile を叩き起こす。
            #   これが無いと、FFmpeg が一度も繋ぎに来なかった場合にスレッドが
            #   永久に残る。
            try:
                _kernel32.CancelIoEx(self._handle, None)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        if self._handle:
            try:
                _kernel32.DisconnectNamedPipe(self._handle)
            except Exception:
                pass
            try:
                _kernel32.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        self.connected = False


# --------------------------------------------------------------------------
# 伴奏プレイヤー（タスク27-B: YouTube等をカラオケの伴奏に使う）
# --------------------------------------------------------------------------
# ★なぜ FFmpeg の入力ではなく Python で持つのか
#   FFmpeg の入力は**プロセス起動時に固定**される。伴奏を FFmpeg の入力にすると、
#   曲送り・一時停止・シークのたびに配信を張り直すことになる。カラオケは
#   曲を次々に変えるものなので、それでは使い物にならない。
#   Python 側のバスに置けば、再生操作はどれも配信を止めずに効く。
#
# ★歌い手に伴奏をどう届けるか（ここが案1の肝）
#   ホストが鳴らした伴奏は、配信に乗って VRChat へ届くまで数秒かかる。
#   数秒遅れの伴奏では歌えないので、**同じ音を WebSocket で歌い手へ直接配る**。
#   歌い手はそれを手元モニターで聴きながら歌う。
#
# ★整合（どれをどれだけ遅らせるか）
#   伴奏は「伴奏側」なので、ホストマイクや PC 音声と同じ固定 500ms の下駄を履く。
#   歌声は 500+offset。歌い手は伴奏を下りで受け取ってから歌うので、
#   往復ぶん（RTT）だけ戻す必要がある。したがって理論値は **offset ≒ −RTT**。
#   RTT は測っているので、卓から自動で当てられる。
BGM_STATE_IDLE = "idle"
BGM_STATE_LOADING = "loading"
BGM_STATE_PLAYING = "playing"
BGM_STATE_PAUSED = "paused"
BGM_STATE_ERROR = "error"

# 伴奏デコーダから先読みしておく量。これ以上は溜めない（＝デコーダが自然に待つ）。
BGM_QUEUE_TICKS = 25          # 20ms × 25 = 0.5 秒

# 下りで歌い手へ配る音声フレームの種別（1バイト目）
DOWNSTREAM_TYPE_BGM = 1
DOWNSTREAM_HEADER = 4         # [0]=種別, [1..3]=予約。4バイトにして16bit境界を保つ


class AccompanimentPlayer:
    """伴奏（YouTube の音声URL / ローカル音源）を FFmpeg でデコードして供給する。

    ★ペーシングはミキサ任せ
      こちらは `take()` された分だけ読み進める。キューが埋まればデコーダは
      パイプ書き込みでブロックするので、`-re` を付けなくても実時間で進む。
      一時停止は「読むのをやめる」だけでよい。
    """

    def __init__(self, ffmpeg_cmd="ffmpeg"):
        self._ffmpeg = ffmpeg_cmd
        self._lock = threading.Lock()
        self._proc = None
        self._queue = collections.deque()
        self._queue_cv = threading.Condition(self._lock)
        self._state = BGM_STATE_IDLE
        self._title = ""
        self._duration = 0.0
        self._error = ""
        self._frames_played = 0        # 再生位置（シーク基準からのフレーム数）
        self._seek_base = 0.0          # -ss で飛ばした秒数
        self._source = None            # (url, headers) 再シーク用に覚えておく
        self.volume = 0.8
        self.level = 0.0

    # ---------------- 状態 ----------------
    def snapshot(self):
        with self._lock:
            pos = self._seek_base + self._frames_played / float(SAMPLE_RATE)
            return {
                "state": self._state,
                "title": self._title,
                "duration": round(self._duration, 1),
                "position": round(pos, 1),
                "volume": round(self.volume, 2),
                "level": round(self.level, 3),
                "error": self._error,
                "loaded": bool(self._source),
            }

    @property
    def playing(self):
        return self._state == BGM_STATE_PLAYING

    # ---------------- 操作 ----------------
    def load(self, url, headers=None, title="", duration=0.0, autoplay=True):
        """伴奏を差し替える。url は YouTube の音声URLでもローカルパスでもよい。"""
        with self._lock:
            self._source = (url, headers or {})
            self._title = title or ""
            self._duration = float(duration or 0.0)
            self._error = ""
        self._start_decoder(seek=0.0)
        if not autoplay:
            self.pause()
        return self.snapshot()

    def play(self):
        with self._lock:
            if not self._source:
                return self.snapshot()
            self._state = BGM_STATE_PLAYING
            # 一時停止中はミキサが読み進めないのでデコーダも待っている。
            # 起こしてやらないと再開しない。
            self._queue_cv.notify_all()
        if not self._proc:
            self._start_decoder(seek=self._seek_base
                                + self._frames_played / float(SAMPLE_RATE))
        return self.snapshot()

    def pause(self):
        # ★LOADING のときも止められること。読み込み直後（まだデコーダの最初の
        #   チャンクが来ていない）に止めようとすると、素通りしてしまい、
        #   デコード開始と同時に鳴り出す。autoplay=False がこれで効かなかった。
        with self._lock:
            if self._state in (BGM_STATE_PLAYING, BGM_STATE_LOADING):
                self._state = BGM_STATE_PAUSED
        return self.snapshot()

    def stop(self):
        self._kill_decoder()
        with self._lock:
            self._state = BGM_STATE_IDLE
            self._queue.clear()
            self._frames_played = 0
            self._seek_base = 0.0
            self.level = 0.0
        return self.snapshot()

    def seek(self, seconds):
        """★シークはデコーダを立て直す。音のバッファも捨てないと前の位置が混ざる。"""
        try:
            sec = max(0.0, float(seconds))
        except (TypeError, ValueError):
            return self.snapshot()
        with self._lock:
            if not self._source:
                return self.snapshot()
        self._start_decoder(seek=sec)
        return self.snapshot()

    def set_volume(self, v):
        try:
            self.volume = clamp(float(v), 0.0, 2.0)
        except (TypeError, ValueError):
            pass
        return self.snapshot()

    # ---------------- ミキサからの取り出し ----------------
    def take(self, n_frames):
        """ステレオ interleaved の array('h') を返す。無ければ無音。

        再生中でなければ**読み進めない**（＝一時停止）。
        """
        need = n_frames * OUTPUT_CHANNELS
        with self._lock:
            if self._state != BGM_STATE_PLAYING:
                return None
            if not self._queue:
                # デコーダが追いついていない。無音を返して時間軸だけ進める。
                return None
            chunk = self._queue.popleft()
            self._frames_played += n_frames
            self._queue_cv.notify_all()
        out = array.array("h")
        out.frombytes(chunk)
        if sys.byteorder != "little":
            out.byteswap()
        if len(out) < need:
            out.extend([0] * (need - len(out)))
        return out

    # ---------------- デコーダ ----------------
    def _build_cmd(self, url, headers, seek):
        cmd = [self._ffmpeg, "-hide_banner", "-loglevel", "error"]
        if headers:
            cmd += ["-headers", "".join(f"{k}: {v}\r\n" for k, v in headers.items())]
        # ★-ss は -i の前に置く（キーフレーム単位の高速シーク）。
        if seek and seek > 0.05:
            cmd += ["-ss", f"{seek:.2f}"]
        cmd += ["-i", url,
                "-vn",
                "-f", "s16le", "-acodec", "pcm_s16le",
                "-ar", str(SAMPLE_RATE), "-ac", str(OUTPUT_CHANNELS),
                "-"]
        return cmd

    def _start_decoder(self, seek=0.0):
        self._kill_decoder()
        with self._lock:
            source = self._source
            if not source:
                return
            url, headers = source
            self._queue.clear()
            self._frames_played = 0
            self._seek_base = float(seek or 0.0)
            self._state = BGM_STATE_LOADING
        try:
            proc = subprocess.Popen(
                self._build_cmd(url, headers, seek),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, bufsize=0,
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            with self._lock:
                self._state = BGM_STATE_ERROR
                self._error = str(e)
            log_print(f"[Karaoke] 伴奏デコーダを起動できません: {e}")
            return
        with self._lock:
            self._proc = proc
        threading.Thread(target=self._read_loop, args=(proc,),
                         name="karaoke-bgm", daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(proc,),
                         name="karaoke-bgm-err", daemon=True).start()

    def _read_loop(self, proc):
        """デコード結果を 20ms 単位でキューへ。満杯なら待つ（＝自然な実時間ペース）。"""
        chunk_bytes = FRAMES_PER_TICK * OUTPUT_CHANNELS * BYTES_PER_SAMPLE
        started = False
        try:
            while True:
                data = proc.stdout.read(chunk_bytes)
                if not data:
                    break
                with self._lock:
                    if self._proc is not proc:
                        return              # 差し替えられた
                    while (len(self._queue) >= BGM_QUEUE_TICKS
                           and self._proc is proc):
                        self._queue_cv.wait(0.2)
                    if self._proc is not proc:
                        return
                    self._queue.append(data)
                    if not started:
                        started = True
                        if self._state == BGM_STATE_LOADING:
                            self._state = BGM_STATE_PLAYING
        except Exception:
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass
            with self._lock:
                if self._proc is proc:
                    # 曲が最後まで流れ切った。位置は残したまま止める。
                    self._proc = None
                    if self._state in (BGM_STATE_PLAYING, BGM_STATE_LOADING):
                        self._state = BGM_STATE_IDLE
                        log_print("[Karaoke] 伴奏の再生が終わりました")

    def _read_stderr(self, proc):
        """★読み続けないとバッファが詰まってデコーダが止まる。"""
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                log_print(f"[Karaoke:BGM] {line}")
                with self._lock:
                    self._error = line[:200]
        except Exception:
            pass
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass

    def _kill_decoder(self):
        with self._lock:
            proc, self._proc = self._proc, None
            self._queue.clear()
            self._queue_cv.notify_all()
        if proc:
            kill_proc(proc)


# --------------------------------------------------------------------------
# ミキサ
# --------------------------------------------------------------------------
class ReverbLine:
    """1 段フィードバック遅延。FFmpeg の aecho=in_gain:out_gain:delay:decay 相当。

    ステレオでインターリーブされた int リストをその場で書き換える。
    """

    def __init__(self):
        self._delay_frames = 0
        self._decay = 0.0
        self._line = None
        self._pos = 0

    def configure(self, preset):
        params = REVERB_PRESETS.get(preset, None)
        if not params:
            self._delay_frames = 0
            self._line = None
            return
        delay_ms, decay = params
        frames = ms_to_frames(delay_ms)
        if frames != self._delay_frames or self._line is None:
            self._delay_frames = frames
            self._line = [0.0] * (frames * OUTPUT_CHANNELS)
            self._pos = 0
        self._decay = decay

    def process(self, samples):
        """samples: 長さ n*2 の float リスト（インターリーブ L,R）。その場で加工。"""
        if not self._delay_frames or self._line is None:
            return samples
        line = self._line
        size = len(line)
        pos = self._pos
        decay = self._decay
        for i in range(len(samples)):
            delayed = line[pos]
            out = samples[i] + delayed * decay
            line[pos] = out
            samples[i] = out
            pos += 1
            if pos >= size:
                pos = 0
        self._pos = pos
        return samples


class DelayLine:
    """マイクバス全体を一定時間遅らせる（遅延補正用）。

    遅延量は生放送中に変わる。**長さを変えるたびに中身を作り直すと
    プツッと切れる**ので、最大長のリングを一度だけ確保して読み出し位置だけ動かす。
    """

    def __init__(self, max_ms):
        self._max_frames = ms_to_frames(max_ms)
        self._size = (self._max_frames + FRAMES_PER_TICK) * OUTPUT_CHANNELS
        self._line = [0.0] * self._size
        self._write = 0
        self._delay_frames = 0

    def set_delay_ms(self, ms):
        frames = ms_to_frames(clamp(int(ms), 0, self._max_frames * 1000 // SAMPLE_RATE))
        self._delay_frames = min(frames, self._max_frames)

    def process(self, samples):
        line = self._line
        size = self._size
        w = self._write
        read_offset = self._delay_frames * OUTPUT_CHANNELS
        for i in range(len(samples)):
            line[w] = samples[i]
            r = w - read_offset
            if r < 0:
                r += size
            samples[i] = line[r]
            w += 1
            if w >= size:
                w = 0
        self._write = w
        return samples


def mix_participants(sources, n_frames):
    """参加者ごとの (array('h') モノラル, 左ゲイン, 右ゲイン) を混ぜる。

    戻り値は長さ n_frames*2 の float リスト（インターリーブ）。
    ここを純関数にしてあるのは、テストから直接叩けるようにするため。
    """
    out = [0.0] * (n_frames * OUTPUT_CHANNELS)
    for mono, gl, gr in sources:
        if gl == 0.0 and gr == 0.0:
            continue
        j = 0
        for i in range(n_frames):
            s = mono[i]
            if s:
                out[j] += s * gl
                out[j + 1] += s * gr
            j += 2
    return out


def float_to_s16le(samples):
    """float リストを s16le バイト列へ。クリップは飽和させる（折り返さない）。"""
    buf = array.array("h", bytes(len(samples) * 2))
    for i, v in enumerate(samples):
        iv = int(v)
        if iv > 32767:
            iv = 32767
        elif iv < -32768:
            iv = -32768
        buf[i] = iv
    if sys.byteorder != "little":
        buf.byteswap()
    return buf.tobytes()


def peak_level(mono, n_frames):
    """0.0〜1.0 のピーク。VU 表示用なので厳密な RMS までは要らない。"""
    peak = 0
    for i in range(n_frames):
        v = mono[i]
        if v < 0:
            v = -v
        if v > peak:
            peak = v
    return peak / 32768.0


# --------------------------------------------------------------------------
# セッション
# --------------------------------------------------------------------------
class KaraokeSession:
    """参加者の管理・ミキシング・FFmpeg への送出をまとめて持つ。

    StreamerCore から 1 つだけ生成され、配信の開始・終了と無関係に
    生き続ける（参加者は配信が止まっても繋ぎっぱなしでよい）。
    FFmpeg への出口（NamedPipeSink）だけが配信のたびに開閉する。
    """

    def __init__(self, config_get=None, recordings_dir=None, ffmpeg_cmd="ffmpeg"):
        self._lock = threading.RLock()
        self.participants = {}          # id -> Participant
        self.enabled = False
        self.approval_required = True   # 承認制（設計書 1.2 荒らし対策）
        self.latency_mode = DEFAULT_LATENCY_MODE
        self.master_volume = 1.0        # リモートマイクバス全体
        self.reverb = DEFAULT_REVERB
        self.offset_ms = 0              # 遅延補正 (-500〜+500)
        self._config_get = config_get

        self.sink = None
        self._mixer_thread = None
        self._mixer_stop = threading.Event()
        self._reverb_line = ReverbLine()
        self._delay_line = DelayLine(KARAOKE_BASE_DELAY_MS * 2)
        # タスク27-B: 伴奏バス。歌声とは**別の遅延**を持つ（伴奏側の固定 500ms）。
        self.bgm = AccompanimentPlayer(ffmpeg_cmd=ffmpeg_cmd)
        self._bgm_delay = DelayLine(KARAOKE_BASE_DELAY_MS)
        self._bgm_delay.set_delay_ms(KARAOKE_BASE_DELAY_MS)
        # 伴奏が止まった後、遅延ラインに残った尾を吐き切るまでの刻み数。
        self._bgm_flush_ticks = ms_to_frames(KARAOKE_BASE_DELAY_MS) // FRAMES_PER_TICK + 2
        self._bgm_flush = 0
        self.master_level = 0.0
        self.ticks = 0

        # 録音
        self.recordings_dir = recordings_dir or os.path.join(APP_DIR, "recordings")
        self._wave = None
        self._wave_path = None
        self._record_started_at = 0.0

        self._apply_delay()
        self._reverb_line.configure(self.reverb)

    # ---------------- 設定 ----------------
    def _apply_delay(self):
        # 伴奏に 500ms の下駄を履かせてあるので、マイク側は 500+offset で釣り合う。
        self._delay_line.set_delay_ms(
            clamp(KARAOKE_BASE_DELAY_MS + self.offset_ms, 0, KARAOKE_BASE_DELAY_MS * 2))

    def configure(self, enabled=None, approval_required=None, latency_mode=None,
                  master_volume=None, reverb=None, offset_ms=None):
        with self._lock:
            if enabled is not None:
                self.enabled = bool(enabled)
            if approval_required is not None:
                self.approval_required = bool(approval_required)
            if latency_mode in LATENCY_MODES:
                self.latency_mode = latency_mode
                target = LATENCY_MODES[latency_mode]
                for p in self.participants.values():
                    p.buffer.set_target(target)
            if master_volume is not None:
                self.master_volume = clamp(float(master_volume), 0.0, 2.0)
            if reverb in REVERB_PRESETS:
                self.reverb = reverb
                self._reverb_line.configure(reverb)
            if offset_ms is not None:
                self.offset_ms = int(clamp(int(offset_ms),
                                           KARAOKE_OFFSET_MIN_MS, KARAOKE_OFFSET_MAX_MS))
                self._apply_delay()
        return self.settings_snapshot()

    def settings_snapshot(self):
        return {
            "enabled": self.enabled,
            "approval_required": self.approval_required,
            "latency_mode": self.latency_mode,
            "latency_target_ms": LATENCY_MODES[self.latency_mode],
            "master_volume": round(self.master_volume, 2),
            "reverb": self.reverb,
            "offset_ms": self.offset_ms,
            "offset_min_ms": KARAOKE_OFFSET_MIN_MS,
            "offset_max_ms": KARAOKE_OFFSET_MAX_MS,
            "max_participants": MAX_PARTICIPANTS,
            "sample_rate": SAMPLE_RATE,
            "frame_ms": FRAME_MS,
        }

    def status_snapshot(self):
        with self._lock:
            people = [p.snapshot() for p in self.participants.values()]
        people.sort(key=lambda x: x["joined_at"])
        data = self.settings_snapshot()
        data.update({
            "participants": people,
            "active_count": sum(1 for p in people if p["state"] == STATE_ACTIVE),
            "waiting_count": sum(1 for p in people if p["state"] == STATE_WAITING),
            "master_level": round(self.master_level, 3),
            "pipe_connected": bool(self.sink and self.sink.connected),
            "pipe_name": self.sink.name if self.sink else "",
            "running": bool(self._mixer_thread and self._mixer_thread.is_alive()),
            "recording": self.is_recording,
            "recording_path": os.path.basename(self._wave_path or ""),
            "recording_seconds": (int(time.time() - self._record_started_at)
                                  if self.is_recording else 0),
            "bgm": self.bgm.snapshot(),
        })
        return data

    # ---------------- 参加者 ----------------
    def add_participant(self, client_id, name, conn=None, is_host=False):
        """戻り値は (Participant, error_message)。満員なら (None, 理由)。"""
        clean = (str(name or "").strip() or "ゲスト")[:MAX_NAME_LEN]
        with self._lock:
            if len(self.participants) >= MAX_PARTICIPANTS:
                return (None, f"満員です（上限 {MAX_PARTICIPANTS} 人）")
            p = Participant(client_id, clean, is_host=is_host)
            p.conn = conn
            p.buffer.set_target(LATENCY_MODES[self.latency_mode])
            # 承認制でなければ、繋いだ瞬間から歌える。
            if not self.approval_required:
                p.state = STATE_ACTIVE
            self.participants[client_id] = p
        p.start_downstream()
        log_print(f"[Karaoke] join id={client_id[:8]} name={clean!r} state={p.state}")
        return (p, None)

    def remove_participant(self, client_id):
        with self._lock:
            p = self.participants.pop(client_id, None)
        if p:
            p.stop_downstream()
            log_print(f"[Karaoke] leave id={client_id[:8]} name={p.name!r}")
        return p

    def get(self, client_id):
        with self._lock:
            return self.participants.get(client_id)

    def set_state(self, client_id, state):
        with self._lock:
            p = self.participants.get(client_id)
            if not p:
                return None
            p.state = state
            if state != STATE_ACTIVE:
                p.buffer.reset()
                p.level = 0.0
        return p

    def set_mix(self, client_id, volume=None, pan=None, host_muted=None):
        with self._lock:
            p = self.participants.get(client_id)
            if not p:
                return None
            if volume is not None:
                p.volume = clamp(float(volume), 0.0, 2.0)
            if pan is not None:
                p.pan = clamp(float(pan), -1.0, 1.0)
            if host_muted is not None:
                p.host_muted = bool(host_muted)
        return p

    def push_audio(self, client_id, pcm_bytes):
        p = self.get(client_id)
        if not p or p.state != STATE_ACTIVE:
            return False
        p.buffer.push(pcm_bytes)
        return True

    # ---------------- ミキサ ----------------
    def ensure_mixer(self):
        """ミキサだけ回す（FFmpeg への出口は無くてよい）。

        ★配信していない間もミキサを回す理由
          参加者は本番前にマイクの音量やモニターを合わせたい。ホスト画面の
          VU メーターと回線品質は、配信が始まる前から動いていないと役に立たない。
          出口が無い間、作った音は捨てられるだけで害はない。
        """
        with self._lock:
            if self._mixer_thread and self._mixer_thread.is_alive():
                return True
            self._mixer_stop.clear()
            self._mixer_thread = threading.Thread(target=self._mix_loop,
                                                  name="karaoke-mixer", daemon=True)
            self._mixer_thread.start()
        log_print("[Karaoke] mixer started")
        return True

    def open_sink(self):
        """FFmpeg 用の名前付きパイプを開き、(パイプ名, sink) を返す（失敗なら (None, None)）。

        ★FFmpeg を起こす **前に** 呼ぶこと。こちらがパイプのサーバなので、
          存在しないパイプに FFmpeg を向けると即死する。

        ★毎回 **新しいパイプを作る**（前のを使い回さない）
          配信の張り直しでは「前の送出FFmpegを殺す」→「すぐ次を起こす」が起きる。
          前の回収スレッド（reap）は殺した相手の wait() から戻ってから出口を閉じるので、
          使い回すと **次の配信が掴んだパイプを前の回収が閉じてしまう**競合になる。
          毎回作れば、回収は自分が渡された sink だけを閉じればよく、競合が消える。
        """
        with self._lock:
            old = self.sink
            sink = NamedPipeSink()
            if not sink.start():
                return (None, None)
            self.sink = sink
        if old:
            old.stop()
        self.ensure_mixer()
        return (sink.name, sink)

    def close_sink(self, sink=None):
        """出口だけ閉じる。参加者の接続とミキサはそのまま残す。

        sink を渡した場合、それが **今の出口でなければ何もしない**。
        古い配信の回収スレッドが、次の配信の出口を巻き添えにしないため。
        """
        with self._lock:
            if sink is not None and self.sink is not sink:
                return
            current, self.sink = self.sink, None
        if current:
            current.stop()
            log_print("[Karaoke] pipe closed")

    def stop(self):
        """全部畳む（アプリ終了・カラオケ機能の無効化）。"""
        self._mixer_stop.set()
        t = self._mixer_thread
        if t:
            t.join(timeout=2.0)
        self._mixer_thread = None
        self.bgm.stop()
        self.close_sink()
        self.stop_recording()
        self.master_level = 0.0
        log_print("[Karaoke] mixer stopped")

    @property
    def running(self):
        return bool(self._mixer_thread and self._mixer_thread.is_alive())

    def _mix_loop(self):
        """壁時計に追従して 20ms ぶんずつ作る。

        ★sleep(0.02) の積み上げでは駄目。Windows のタイマ分解能では 1 刻みごとに
          数ミリ秒ずれ、10 分も回せば秒単位の音ズレになる。「開始からの経過時間で
          あるべきサンプル数」を毎回計算し、その差分だけ作ることで自己補正する。
        """
        start = time.monotonic()
        produced_frames = 0
        while not self._mixer_stop.is_set():
            elapsed = time.monotonic() - start
            should_have = int(elapsed * SAMPLE_RATE)
            behind = should_have - produced_frames
            if behind < FRAMES_PER_TICK:
                # まだ次の刻みの時刻ではない。半刻みだけ寝て様子を見る。
                self._mixer_stop.wait(FRAME_MS / 2000.0)
                continue
            # 大きく出遅れたとき（重い処理に割り込まれた等）に一気に作ろうとすると
            # そこでまた固まる。最大 5 刻みまでで諦め、時間軸を進めてしまう。
            ticks = min(5, behind // FRAMES_PER_TICK)
            if behind > FRAMES_PER_TICK * 25:
                # 1 刻み 20ms なので 500ms 以上の出遅れ。追いつくのは諦めて基準を戻す。
                produced_frames = should_have - FRAMES_PER_TICK
                ticks = 1
            for _ in range(ticks):
                self._tick()
                produced_frames += FRAMES_PER_TICK

    def _tick(self):
        n = FRAMES_PER_TICK
        with self._lock:
            people = list(self.participants.values())
            master = self.master_volume

        sources = []
        for p in people:
            if p.state != STATE_ACTIVE:
                p.level *= LEVEL_DECAY_PER_TICK
                continue
            mono = p.buffer.take(n)
            lvl = peak_level(mono, n)
            p.level = lvl if lvl > p.level else p.level * LEVEL_DECAY_PER_TICK
            if not p.audible:
                continue
            gl, gr = pan_gains(p.pan)
            v = p.volume * master
            sources.append((mono, gl * v, gr * v))

        samples = mix_participants(sources, n)
        if self.reverb != "off":
            self._reverb_line.process(samples)
        self._delay_line.process(samples)

        # ---- 伴奏（タスク27-B）----
        # ★歌い手へは「遅延を掛ける前・音量を掛ける前」の音を配る。
        #   ・遅延前: 歌い手にはできるだけ早く届いた方が歌いやすい
        #   ・音量前: ホストが配信side の伴奏を絞っても、歌い手が聴けなくならない
        bgm = self.bgm.take(n)
        if bgm is not None:
            self._bgm_flush = self._bgm_flush_ticks
            self._broadcast_bgm(bgm, n)
        if bgm is not None or self._bgm_flush > 0:
            vol = self.bgm.volume
            if bgm is None:
                self._bgm_flush -= 1
                bgm_f = [0.0] * (n * OUTPUT_CHANNELS)
            else:
                bgm_f = [bgm[i] * vol for i in range(n * OUTPUT_CHANNELS)]
            # 伴奏は「伴奏側」。ホストマイクや PC 音声と同じ固定 500ms の下駄を履く。
            # 歌声（500+offset）と違い、遅延補正スライダでは動かさない。
            self._bgm_delay.process(bgm_f)
            for i in range(n * OUTPUT_CHANNELS):
                samples[i] += bgm_f[i]
            has_bgm = True
        else:
            has_bgm = False

        # マスタのピーク（ホストUIの「配信に乗っている音」の目安）
        peak = 0.0
        for v in samples:
            av = v if v >= 0 else -v
            if av > peak:
                peak = av
        lvl = min(1.0, peak / 32768.0)
        self.master_level = lvl if lvl > self.master_level else self.master_level * LEVEL_DECAY_PER_TICK

        pcm = (float_to_s16le(samples)
               if (sources or has_bgm or self.reverb != "off"
                   or self._delay_line._delay_frames)
               else SILENCE_TICK)
        if self.sink:
            self.sink.write(pcm)
        self._write_recording(pcm)
        self.ticks += 1

    def _broadcast_bgm(self, stereo, n):
        """伴奏を ON AIR の参加者へ配る（歌い手の手元モニター用）。

        ★ON AIR の人にだけ送る
          48kHz モノラルで 1 人あたり約 768kbps。待機中の全員へ配ると
          ホストの上り帯域がその人数倍になる。歌っている人が聴ければ足りる。

        ★モノラルへ落とす
          伴奏の左右差は歌うために要らない。帯域を半分にする方が実利がある。
        """
        with self._lock:
            targets = [p for p in self.participants.values()
                       if p.state == STATE_ACTIVE and p.conn is not None]
        if not targets:
            return
        mono = array.array("h", bytes(n * BYTES_PER_SAMPLE))
        j = 0
        for i in range(n):
            v = (stereo[j] + stereo[j + 1]) >> 1
            mono[i] = v
            j += 2
        if sys.byteorder != "little":
            mono.byteswap()
        payload = bytes((DOWNSTREAM_TYPE_BGM, 0, 0, 0)) + mono.tobytes()
        for p in targets:
            p.push_downstream(payload)

    # ---------------- 録音（設計書 5.3） ----------------
    @property
    def is_recording(self):
        return self._wave is not None

    def start_recording(self):
        if self._wave is not None:
            return self._wave_path
        try:
            os.makedirs(self.recordings_dir, exist_ok=True)
            # ★秒単位の名前は衝突する。停止してすぐ録り直すと、同じ秒に入って
            #   前のテイクを黙って上書きしてしまう。空いている名前まで送る。
            base = time.strftime("karaoke_%Y%m%d_%H%M%S")
            path = os.path.join(self.recordings_dir, base + ".wav")
            serial = 2
            while os.path.exists(path):
                path = os.path.join(self.recordings_dir, f"{base}_{serial}.wav")
                serial += 1
            wf = wave.open(path, "wb")
            wf.setnchannels(OUTPUT_CHANNELS)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(SAMPLE_RATE)
        except Exception as e:
            log_print(f"[Karaoke] 録音開始に失敗: {e}")
            return None
        self._wave = wf
        self._wave_path = path
        self._record_started_at = time.time()
        log_print(f"[Karaoke] recording -> {path}")
        return path

    def stop_recording(self):
        wf, path = self._wave, self._wave_path
        self._wave = None
        if wf:
            try:
                wf.close()
            except Exception:
                pass
            log_print(f"[Karaoke] recording saved: {path}")
        return path

    def _write_recording(self, pcm):
        wf = self._wave
        if not wf:
            return
        try:
            wf.writeframes(pcm)
        except Exception as e:
            log_print(f"[Karaoke] 録音書き込みに失敗: {e}")
            self.stop_recording()


# --------------------------------------------------------------------------
# FFmpeg 側の組み立て（純関数。テストから直接検証する）
# --------------------------------------------------------------------------
def build_remote_mic_input(pipe_name, rate=SAMPLE_RATE, channels=OUTPUT_CHANNELS):
    """名前付きパイプを読む FFmpeg 入力引数。

    ★`-thread_queue_size` を積んでおく。積まないと、他の入力が詰まったときに
      「Thread message queue blocking」で音が飛ぶ。
    """
    return [
        "-f", "s16le",
        "-ar", str(int(rate)),
        "-ac", str(int(channels)),
        "-thread_queue_size", "1024",
        "-i", pipe_name,
    ]


def format_volume(v):
    try:
        fv = float(v)
    except (TypeError, ValueError):
        fv = 1.0
    return str(round(clamp(fv, 0.0, 2.0), 2))
