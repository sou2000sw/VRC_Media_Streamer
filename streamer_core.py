import os
import sys
import time
import re
import io
import json
import math
import random
import socket
import threading
import subprocess
import shutil
import atexit
import urllib.request
import urllib.parse
import hashlib
import secrets
import collections
import yt_dlp
import qrcode
import uuid
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# パス解決ヘルパー
if getattr(sys, 'frozen', False):
    BASE_PATH = sys._MEIPASS
    APP_DIR = os.path.dirname(sys.executable)
else:
    BASE_PATH = os.path.dirname(os.path.abspath(__file__))
    APP_DIR = BASE_PATH

from version import APP_VERSION

CONFIG_FILE = os.path.join(APP_DIR, "config.json")
HLS_DIR = os.path.join(APP_DIR, "hls_output")
IMAGE_CACHE_DIR = os.path.join(HLS_DIR, "images")
RADIO_CACHE_DIR = os.path.join(IMAGE_CACHE_DIR, "radio_cache")
STANDBY_IMAGE_PATH = os.path.join(HLS_DIR, "standby.png")
DEFAULT_STANDBY_IMAGE_PATH = os.path.join(BASE_PATH, "assets", "standby_default.jpg")
QR_OVERLAY_PATH = os.path.join(HLS_DIR, "qr_overlay.png")
CLOUDFLARED_EXE = os.path.join(BASE_PATH, "cloudflared.exe")
LOCAL_FFMPEG = os.path.join(APP_DIR, "ffmpeg.exe")
LOCAL_FFPROBE = os.path.join(APP_DIR, "ffprobe.exe")
# タスク25: アプリ単位の音声取り込み補助exe。配布時は ffmpeg.exe と同じ場所に置く。
# 開発中はビルド出力（native/app_audio_capture/build/）を直接使う。
LOCAL_APP_AUDIO_EXE = os.path.join(APP_DIR, "app_audio_capture.exe")
DEV_APP_AUDIO_EXE = os.path.join(BASE_PATH, "native", "app_audio_capture",
                                 "build", "app_audio_capture.exe")
VIDEO_STORAGE_DIR = os.path.join(HLS_DIR, "videos")

def cleanup_hls_dir_completely():
    """HLS出力ディレクトリ内の全一時ファイル・フォルダを完全消去する（atexit ハンドラ）。"""
    if not os.path.exists(HLS_DIR):
        return
    for attempt in range(5):
        try:
            remaining = False
            for item in os.listdir(HLS_DIR):
                item_path = os.path.join(HLS_DIR, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                    else:
                        os.remove(item_path)
                except Exception:
                    remaining = True
            if not remaining and not os.listdir(HLS_DIR):
                break
            time.sleep(0.2)
        except Exception:
            time.sleep(0.2)

atexit.register(cleanup_hls_dir_completely)

def get_local_ip():
    """LAN内の自ホストIPアドレスを取得 (例: 192.168.1.100)"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8000,
    "enable_tunnel": True,
    "hls_segment_time": 3,
    "hls_list_size": 15,
    "video_transition_wait_seconds": 1,
    "live_sync_duration_count": 4,
    "loop_queue": False,
    "shuffle": False,
    # Webリモコン（ゲスト向けの `/` と `/api/*`）そのものを開くかどうか。タスク21。
    # False で「ホスト専用スタンドアロンモード」: ホストPC本人（厳格なループバック）
    # 以外からの操作を全部 403 で塞ぐ。allow_web_* は「開いた上で何を許すか」の設定なので、
    # ここが False のときは一切参照されない（＝より強い上位のスイッチ）。
    # HLS配信（stream.m3u8 / *.ts）だけは開けたままにする。VRChatのプレイヤーは
    # 認証ヘッダを付けられず、ここを塞ぐと配信そのものが止まるため。
    "enable_web_remote": True,
    "allow_web_queue_add": True,
    "allow_web_queue_edit": True,
    "allow_web_playback_control": True,
    # 「接続 & スマホ共有」タブ（QRコード・トンネルURL・ワールドへ貼る再生URL）を
    # ゲスト（Webリモコン）にも見せるか。既定は False。
    # ここにはPIN付きのリモコンURLと配信先の再生URLが並ぶため、
    # 「共有された人がさらに他人へ共有できる」状態はホストが明示的に許可したときだけにする。
    "allow_web_share_info": False,
    "image_display_duration": 15,
    "image_auto_advance": False,
    "overlay_qr_enabled": False,
    "overlay_qr_video": False,
    "overlay_qr_image": False,
    "overlay_qr_mode": "bottom-right",
    "overlay_clock_enabled": False,
    "overlay_clock_video": False,
    "overlay_clock_position": "top-right",
    "playback_mode": "video",
    "live_audio_mic_device": "",
    "live_audio_loopback_device": "",
    "live_audio_mic_volume": 1.0,
    "live_audio_loopback_volume": 0.7,
    "live_audio_bitrate_kbps": 192,
    # タスク25: アプリ単位の音声取り込み（WASAPIプロセスループバック）
    # ★正本はウィンドウタイトル。PIDは再起動で変わるので保存値を当てにしない。
    "live_audio_app_enabled": False,
    "live_audio_app_window_title": "",
    "live_audio_app_volume": 1.0,
    "live_audio_app_mode": "include",   # "include" | "exclude"
    # ライブ音声の背景。ラジオと同じ選び方にする。
    # ★"card"（サムネイルカード）は入れない。あれはYouTubeのメタデータから作るもので、
    #   ライブ音声には元データが無い。
    "live_audio_bg_source": "standby",  # "standby" | "slideshow"
    "screen_capture_source_type": "display",   # "display" | "window"
    "screen_capture_display_index": 0,
    "screen_capture_window_title": "",
    "screen_capture_framerate": 30,
    "screen_capture_width": 1920,
    "screen_capture_height": 1080,
    "screen_capture_draw_mouse": True,
    "screen_capture_bitrate_kbps": 4000,
    "radio_mode": False,
    "radio_bg_source": "card",
    # ラジオの曲頭・曲尾フェード秒数（0で無効・最大5秒）: タスク17
    "radio_crossfade_duration": 3,
    "standby_mode": "image",
    "standby_image_path": "",
    "web_password": "",
    "max_video_upload_mb": 200,
    "max_video_height": 1080,
    # ホスト画面の種類。"web" = Webリモコンと同じモダンUIを WebView2 で表示、
    # "classic" = 従来の CustomTkinter 画面。WebView2 が使えない環境では
    # "web" を指定していても自動的に classic へ落ちる（gui_streamer.main）。
    "host_ui": "web",

    # --- 配信先（destination）: タスク14 ---
    # output_mode を切り替えるだけで出口（シンク）が変わる。
    # 既定は TopazChat（低遅延）。接続できない場合は自動でHLSへ退避するため、
    # 相手サーバーが落ちていても配信自体は途切れない。
    "output_mode": "topaz",
    # TopazChat のエンドポイントは個人運営でホスト変更・終了があり得るため、
    # ハードコードせず設定値として持つ（リビルドなしで追随できるようにする）。
    "topaz_rtmp_base": "rtmp://topaz.chat/live",
    "topaz_rtsp_base": "rtspt://topaz.chat/live",
    "topaz_stream_key": "",
    "generic_rtmp_url": "",
    "generic_rtmp_key": "",
    # ★TopazChat の上限（TOPAZ_MAX_VIDEO_KBPS=2000）に合わせる。
    #   720p30 の画面共有を 1500kbps に通すと1画素あたり0.054ビットしか無く、
    #   動きのある画面で明確に潰れる（実測）。上限まで使うのを既定にする。
    "rtmp_video_bitrate_kbps": 2000,
    "rtmp_audio_bitrate_kbps": 192,
    "rtmp_video_width": 1280,
    "rtmp_video_height": 720,
    "rtmp_fps": 30,
    "rtmp_gop_seconds": 2,
    "rtmp_fallback_to_hls": True,
    "rtmp_fallback_after_failures": 3,
    "rtmp_retry_backoff_max_seconds": 300,

    # --- 映像エンコーダー（タスク18）---
    # "auto" = NVENC → QSV → AMF の順に実際に動くものを探し、全滅なら libx264。
    # 明示指定しても、そのPCで動かなければ libx264 へ退避する（配信を止めない）。
    "video_encoder": "auto",

    # 初回セットアップ（配信先とストリームキーの確認）を通過したか。
    # 既定の TopazChat はストリームキーが要る。キーは再生開始時に自動生成されるが、
    # それだとワールドに貼るURLが「最初の1本を再生するまで空」になり、
    # 何を貼ればよいのか分からないまま詰まる。初回だけ明示的に確認させる。
    "setup_completed": False
}

# --- 配信先（destination）定義: タスク14 ---
OUTPUT_MODES = ("hls", "topaz", "generic_rtmp")
RTMP_OUTPUT_MODES = ("topaz", "generic_rtmp")

# TopazChat 公式README（2026-08-28 確認）に明記された上限。
# 「大きく上回ると配信が強制的に切断されます」とされているため、推奨値ではなく
# ソフト側のハードリミットとして扱い、設定値がこれを超える場合は保存時点でクランプする。
TOPAZ_MAX_VIDEO_KBPS = 2000
TOPAZ_MAX_AUDIO_KBPS = 320

# ストリームキーは「同じキーを知っていれば誰でも投稿できる」ため、短いキーは乗っ取られる。
# 初回は必ずソフト側で長いランダム文字列を生成する（手入力での上書きは可能）。
STREAM_KEY_BYTES = 30          # token_urlsafe(30) => 40文字
STREAM_KEY_MIN_LENGTH = 32

# ★実測（2026-08-28）: 入力が pipe:0 のFFmpegは、ストリーム情報が確定するまで
# 出力側のRTMPハンドシェイクを開始しない。つまり「起動直後にプロセスが生きている」ことは
# 接続成功を意味しない（誰もlistenしていない宛先でも2秒間は平然と生きていた）。
# そのため到達性は起動前にTCPで確かめ、起動後の生存確認は即死検知の保険として短く持つ。
SINK_STARTUP_PROBE_SECONDS = 1.0

# 中継の先読み秒数。HLSは手元にセグメントを溜める設計なので先行させるが、
# RTMPはライブ投稿なので実時間に近づける（詰め込むと遅延と映像破綻を招く）。
HLS_BUFFER_AHEAD_SECONDS = 15.0
RTMP_BUFFER_AHEAD_SECONDS = 1.0
RTMP_CONNECT_TIMEOUT_SECONDS = 3.0
# この秒数以上生き延びたシンクの死は「一度は繋がった上での切断」とみなし、
# 連続失敗カウントをリセットして再接続サイクルをやり直す。
SINK_STABLE_SECONDS = 30.0

# 変更されたらシンクを作り直す必要がある設定キー
DESTINATION_CONFIG_KEYS = (
    "output_mode",
    "topaz_rtmp_base", "topaz_rtsp_base", "topaz_stream_key",
    "generic_rtmp_url", "generic_rtmp_key",
    "rtmp_video_bitrate_kbps", "rtmp_audio_bitrate_kbps",
    "rtmp_video_width", "rtmp_video_height", "rtmp_fps", "rtmp_gop_seconds",
)

# ★--noconsole ビルドでは sys.stdout がダミーに差し替わり、print はどこにも残らない。
# 配布先で起きた事象を後から追う手段が無くなるため、ファイルへも必ず書く。
# 無制限に太らせると配布先のディスクを埋めるので、上限を超えたら1世代だけ退避する。
LOG_FILE_PATH = os.path.join(APP_DIR, "vrc_media_streamer.log")
LOG_FILE_MAX_BYTES = 2 * 1024 * 1024
_log_file_lock = threading.Lock()


def log_print(msg):
    try:
        print(msg, flush=True)
    except Exception:
        pass
    # ログ出力の失敗で本処理を止めない（配信中に例外を上げる価値は無い）
    try:
        with _log_file_lock:
            try:
                if os.path.getsize(LOG_FILE_PATH) > LOG_FILE_MAX_BYTES:
                    os.replace(LOG_FILE_PATH, LOG_FILE_PATH + ".1")
            except OSError:
                pass
            with open(LOG_FILE_PATH, "a", encoding="utf-8", errors="replace") as f:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", file=f)
    except Exception:
        pass

def get_ffmpeg_cmd():
    if os.path.exists(LOCAL_FFMPEG):
        return LOCAL_FFMPEG
    return "ffmpeg"

def get_ffprobe_cmd():
    if os.path.exists(LOCAL_FFPROBE):
        return LOCAL_FFPROBE
    return "ffprobe"

def get_app_audio_capture_cmd():
    """アプリ音声取り込み補助exeのパス。無ければ None（呼び出し側はフォールバックする）。"""
    for path in (LOCAL_APP_AUDIO_EXE, DEV_APP_AUDIO_EXE):
        if os.path.exists(path):
            return path
    return None

def kill_proc(proc):
    if not proc:
        return
    try:
        proc.kill()
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass
    except Exception:
        pass

def get_drawtext_font_path(bold=True):
    """FFmpegのdrawtextフィルタ用にエスケープされたフォントパスを取得"""
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/seguisb.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font_path = None
    for p in candidates:
        if os.path.exists(p):
            font_path = p
            break
    if not font_path:
        font_path = "arialbd.ttf" if bold else "arial.ttf"

    # Windowsパスのバックスラッシュをスラッシュに変換し、コロンをエスケープ (e.g. C\:/Windows/Fonts/...)
    font_path = font_path.replace("\\", "/")
    font_path_escaped = font_path.replace(":", "\\:")
    return font_path_escaped

def get_keyframe_opts(segment_seconds):
    """HLSセグメント長ちょうどにIDR(キーフレーム)を置くためのエンコードオプション。

    HLSはセグメント単位で単独デコードできることが前提。先頭がIDRでないと
    プレイヤーは次のIDRが来るまで映像を描けず、音声だけが進む——つまり
    「音と映像がずれている」ように見える。実測では全14セグメントが非IDR開始で、
    先頭からIDRまで平均0.9秒(最大1.4秒)の空白があった。

    -g はフレーム数指定なので、入力fpsが変わるとGOP秒がずれる
    (30fpsで -g 60 なら2.0秒。セグメント3秒とは6秒ごとにしか一致しない)。
    時間式で強制すれば入力fpsに関係なく境界へIDRを置ける。
    """
    seg = max(1, int(segment_seconds or 3))
    return ["-force_key_frames", f"expr:gte(t,n_forced*{seg})"]


# =============================================================================
# ラジオモードの曲間フェード（タスク17）
# =============================================================================
# 曲の変わり目のブツ切りを消すための曲頭フェードイン／曲尾フェードアウト。
#
# ★「重ねる」クロスフェードは現構造では作れない。送出は 1曲 = 1本の送信FFmpegで、
#   永続シンクの pipe:0 へ MPEG-TS を流し込んでいる（play_radio / relay_stream_data）。
#   2本を同時に同じ pipe へ流せば多重化が壊れるため、前曲末尾と次曲頭を
#   オーバーラップさせるには1本のFFmpegの中で作るしかなく、送出構造の再設計を伴う。
#
# 重ねなくても目的はほぼ達する。曲間に空く無音は 0.1 秒程度しかない:
# 次曲のPTSは accumulated_pts から続くので、プロセス起動やキュー処理にかかった
# 実時間はストリームの時間軸には現れない（耳に付いていたのは波形の断ち切りの方）。
RADIO_CROSSFADE_MAX_SECONDS = 5

# これ未満のフェードは掛けない。短い曲に長いフェードを掛けると
# 「終始音量が動いていて落ち着かない」音になるため、曲長の1/4を上限に縮めたうえで、
# 縮んだ結果が短すぎるならフェード自体をやめる。
_RADIO_FADE_MIN_SECONDS = 0.5


def normalize_radio_crossfade(value):
    """設定値を 0〜5 秒へ丸める。数値でない値・負値は 0（無効）とみなす。"""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return 0.0
    if seconds != seconds or seconds <= 0:  # NaN も無効扱い
        return 0.0
    return float(min(RADIO_CROSSFADE_MAX_SECONDS, seconds))


# --------------------------------------------------------------------------
# タスク22: PC音声（ループバック）＆マイク取り込み（dshow経路）
# --------------------------------------------------------------------------

_dshow_audio_devices_cache = (0.0, [])


def is_loopback_candidate(name: str) -> bool:
    """デバイス名がPC出力音（ループバック）取り込みに使えそうかを判定 (UIヒント用)"""
    if not name:
        return False
    name_lower = str(name).lower()
    keywords = [
        "stereo mix",
        "ステレオ ミキサー",
        "ステレオミキサー",
        "what u hear",
        "voicemeeter out",
        "virtual desktop audio",
        "cable output",
        "virtual-audio-capturer",
        "loopback",
        "wave out mix",
    ]
    return any(kw in name_lower for kw in keywords)


def decode_dshow_bytes(raw_bytes: bytes) -> str:
    """dshow出力バイト列を utf-8 -> cp932 -> utf-8 (replace) の順でデコード"""
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw_bytes.decode("cp932")
        except Exception:
            return raw_bytes.decode("utf-8", errors="replace")


def parse_dshow_audio_devices_output(output_text: str) -> list[dict]:
    """ffmpeg -list_devices true -f dshow の stderr テキストをパース"""
    devices = []
    current_dev = None
    for line in output_text.splitlines():
        m_audio = re.search(r'"([^"]+)"\s+\(audio\)', line)
        m_video = re.search(r'"([^"]+)"\s+\(video\)', line)
        m_alt = re.search(r'Alternative name\s+"([^"]+)"', line)

        if m_audio:
            name = m_audio.group(1)
            current_dev = {
                "name": name,
                "alt": "",
                "loopback_hint": is_loopback_candidate(name)
            }
            devices.append(current_dev)
        elif m_video:
            current_dev = None
        elif m_alt and current_dev is not None:
            current_dev["alt"] = m_alt.group(1)
            current_dev = None
    return devices


def enumerate_dshow_audio_devices(timeout=8, use_cache=True):
    """dshow 経由で音声入力デバイス一覧を列挙"""
    global _dshow_audio_devices_cache
    now = time.time()
    if use_cache and (now - _dshow_audio_devices_cache[0] < 30):
        return _dshow_audio_devices_cache[1]

    cmd = [get_ffmpeg_cmd(), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW
        )
        _, stderr_bytes = proc.communicate(timeout=timeout)
        text = decode_dshow_bytes(stderr_bytes or b"")
        devices = parse_dshow_audio_devices_output(text)
        _dshow_audio_devices_cache = (now, devices)
        return devices
    except subprocess.TimeoutExpired:
        log_print("[dshow] Device enumeration timed out")
        if 'proc' in locals():
            kill_proc(proc)
        return []
    except Exception as e:
        log_print(f"[dshow] Device enumeration failed: {e}")
        return []


def _fmt_audio_volume(v):
    """フィルタに埋める音量値を 0.0〜2.0 に丸めて文字列化する。"""
    try:
        fv = float(v)
    except (TypeError, ValueError):
        fv = 1.0
    fv = max(0.0, min(2.0, fv))
    fv = round(fv, 2)
    return str(fv)


def build_dshow_audio_inputs(mic_device=None, loopback_device=None,
                             mic_volume=1.0, loopback_volume=0.7,
                             start_index=1):
    """dshow音声入力のコマンド引数・フィルタ・マップラベルを構築する純粋関数"""
    mic_dev = str(mic_device).strip() if mic_device else ""
    loop_dev = str(loopback_device).strip() if loopback_device else ""

    _fmt_vol = _fmt_audio_volume

    active = []
    if mic_dev:
        active.append(("mic", mic_dev, _fmt_vol(mic_volume)))
    if loop_dev:
        active.append(("loopback", loop_dev, _fmt_vol(loopback_volume)))

    if not active:
        return ([], None, None)

    if len(active) == 1:
        dev_type, dev_name, vol_str = active[0]
        idx = start_index
        input_args = [
            "-f", "dshow",
            "-thread_queue_size", "1024",
            "-audio_buffer_size", "50",
            "-i", f"audio={dev_name}"
        ]
        if vol_str == "1.0":
            return (input_args, None, f"{idx}:a:0")
        else:
            return (input_args, f"[{idx}:a]volume={vol_str}[aout]", "[aout]")

    # 2件（マイクを先、ループバックを後の順で固定）
    mic_name, mic_vol_str = active[0][1], active[0][2]
    loop_name, loop_vol_str = active[1][1], active[1][2]
    i = start_index
    j = start_index + 1

    input_args = [
        "-f", "dshow",
        "-thread_queue_size", "1024",
        "-audio_buffer_size", "50",
        "-i", f"audio={mic_name}",
        "-f", "dshow",
        "-thread_queue_size", "1024",
        "-audio_buffer_size", "50",
        "-i", f"audio={loop_name}"
    ]
    audio_filter = f"[{i}:a]volume={mic_vol_str}[amic];[{j}:a]volume={loop_vol_str}[apc];[amic][apc]amix=inputs=2:duration=longest:dropout_transition=0[aout]"
    audio_map = "[aout]"
    return (input_args, audio_filter, audio_map)



# --------------------------------------------------------------------------
# タスク25: アプリ単位の音声（プロセスループバック）を音声グラフに合流させる
# --------------------------------------------------------------------------

APP_AUDIO_RATE = 48000
# 入力レベルの通知間隔[ms]。UIのゲージ用。細かすぎても人には読めないので5回/秒。
APP_AUDIO_LEVEL_INTERVAL_MS = 200
# レベルがこの秒数より古ければ「来ていない」と扱う。
APP_AUDIO_LEVEL_STALE_SEC = 2.0
APP_AUDIO_CHANNELS = 2


def build_app_audio_input(rate=APP_AUDIO_RATE, channels=APP_AUDIO_CHANNELS):
    """補助exeが stdout に流す生PCMを受ける ffmpeg 入力引数。

    ★取り込み側FFmpegの stdout は MPEG-TS の出口として既に使っているが、
      stdin は空いている。ここへ補助exeの stdout をOSパイプで直結するので、
      名前付きパイプもTCPも要らず、Python はバイトを一切コピーしない。
    """
    return [
        "-f", "s16le",
        "-ar", str(int(rate)),
        "-ac", str(int(channels)),
        "-thread_queue_size", "1024",
        "-i", "pipe:0"
    ]


def build_audio_inputs(app_enabled=False, app_volume=1.0,
                       mic_device=None, loopback_device=None,
                       mic_volume=1.0, loopback_volume=0.7,
                       start_index=1,
                       app_rate=APP_AUDIO_RATE, app_channels=APP_AUDIO_CHANNELS):
    """アプリ音声＋dshow(マイク/ループバック)をまとめた入力・フィルタ・マップを組む。

    アプリ音声が無効なら build_dshow_audio_inputs() をそのまま返す（既存挙動を維持）。
    有効なときは **アプリ音声を必ず先頭（start_index）** に置く。順番を固定しないと
    入力インデックスの採番が呼び出し側ごとにずれて、無音や取り違えの原因になる。
    """
    mic_dev = str(mic_device).strip() if mic_device else ""
    loop_dev = str(loopback_device).strip() if loopback_device else ""

    if not app_enabled:
        return build_dshow_audio_inputs(
            mic_device=mic_dev, loopback_device=loop_dev,
            mic_volume=mic_volume, loopback_volume=loopback_volume,
            start_index=start_index)

    input_args = build_app_audio_input(app_rate, app_channels)
    idx = start_index
    filters = [f"[{idx}:a]volume={_fmt_audio_volume(app_volume)}[aapp]"]
    labels = ["[aapp]"]
    idx += 1

    if mic_dev:
        input_args += ["-f", "dshow", "-thread_queue_size", "1024",
                       "-audio_buffer_size", "50", "-i", f"audio={mic_dev}"]
        filters.append(f"[{idx}:a]volume={_fmt_audio_volume(mic_volume)}[amic]")
        labels.append("[amic]")
        idx += 1

    if loop_dev:
        input_args += ["-f", "dshow", "-thread_queue_size", "1024",
                       "-audio_buffer_size", "50", "-i", f"audio={loop_dev}"]
        filters.append(f"[{idx}:a]volume={_fmt_audio_volume(loopback_volume)}[apc]")
        labels.append("[apc]")
        idx += 1

    if len(labels) == 1:
        # アプリ音声だけ。amix を挟むと無駄に遅延が乗るので直接 [aout] にする。
        return (input_args, filters[0].replace("[aapp]", "[aout]"), "[aout]")

    mix = ("".join(labels) +
           f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0[aout]")
    return (input_args, ";".join(filters) + ";" + mix, "[aout]")


def start_app_audio_helper(pid, mode="include", rate=APP_AUDIO_RATE,
                           channels=APP_AUDIO_CHANNELS, stats_sec=0,
                           level_ms=APP_AUDIO_LEVEL_INTERVAL_MS):
    """補助exeを起動し Popen を返す。起動できなければ None。

    ★戻り値が None でも配信は止めない（fail-soft）。音が取れないことより、
      配信そのものが落ちる方が事故として重い。
    """
    exe = get_app_audio_capture_cmd()
    if not exe:
        log_print("[AppAudio] helper exe not found -> アプリ音声を無効化して続行")
        return None
    try:
        target_pid = int(pid)
    except (TypeError, ValueError):
        log_print(f"[AppAudio] invalid pid: {pid!r}")
        return None
    if target_pid <= 0:
        log_print(f"[AppAudio] invalid pid: {target_pid}")
        return None

    cmd = [exe, "--pid", str(target_pid),
           "--mode", "exclude" if str(mode) == "exclude" else "include",
           "--rate", str(int(rate)), "--channels", str(int(channels))]
    if stats_sec:
        cmd += ["--stats", str(int(stats_sec))]
    if level_ms:
        cmd += ["--level", str(int(level_ms))]
    try:
        # ★stderr を DEVNULL にしてはいけない。補助exeの診断ログと入力レベルが
        #   そこにしか出ないため、捨てると「音が来ているのか」を誰も知り得なくなる。
        #   PIPE にした以上は必ず読み続けること（読まないとバッファが詰まって止まる）。
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, bufsize=0,
            creationflags=CREATE_NO_WINDOW
        )
    except Exception as e:
        log_print(f"[AppAudio] helper start failed: {e}")
        return None
    log_print(f"[AppAudio] helper started pid={target_pid} mode={mode}")
    return proc

_capture_displays_cache = (0.0, [])


def probe_ddagrab_display(output_idx, timeout=8):
    """ddagrab の output_idx が実在するかを1回試し、(ok, width, height) を返す。"""
    cmd = [
        get_ffmpeg_cmd(), "-hide_banner", "-f", "lavfi",
        "-i", f"ddagrab=output_idx={output_idx}:framerate=5",
        "-t", "0.3", "-f", "null", "-"
    ]
    proc = None
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW
        )
        stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)
        if proc.returncode != 0:
            return (False, 0, 0)
        err_text = decode_dshow_bytes(stderr_bytes)
        m = re.search(r"Stream #0:0.*?, (\d+)x(\d+)", err_text)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            return (True, w, h)
        return (True, 0, 0)
    except Exception:
        if proc:
            kill_proc(proc)
        return (False, 0, 0)


def enumerate_capture_displays(max_outputs=8, use_cache=True):
    """接続ディスプレイを ddagrab の output_idx 順に列挙する。"""
    global _capture_displays_cache
    now = time.time()
    if use_cache and (now - _capture_displays_cache[0] < 60.0):
        return list(_capture_displays_cache[1])

    displays = []
    for idx in range(max_outputs):
        ok, w, h = probe_ddagrab_display(idx)
        if not ok:
            break
        displays.append({
            "index": idx,
            "width": w,
            "height": h,
            "label": f"ディスプレイ{idx + 1} ({w}x{h})"
        })

    _capture_displays_cache = (now, displays)
    return list(displays)


def enumerate_capture_windows():
    """キャプチャ候補になる可視トップレベルウィンドウを列挙する。"""
    if sys.platform != "win32":
        return []

    try:
        import ctypes
        from ctypes import wintypes

        # ★ctypes.windll.user32 はプロセス内で共有・キャッシュされる。ここで
        #   argtypes を書き換えると、同じプロセスの別の利用者が壊れる（実際に
        #   検証スクリプトが "expected LP_RECT instead of pointer to RECT" で落ちた）。
        #   独立インスタンスを作って、この関数の中に閉じ込める。
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)

        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL

        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongW.restype = wintypes.LONG

        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int

        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL

        EXCLUDE_TITLES = {
            "Program Manager", "Windows 入力エクスペリエンス", "Windows Input Experience",
            "Default IME", "MSCTFIME UI", "Discord Overlay", "NVIDIA GeForce Overlay"
        }

        results = []

        def enum_windows_callback(hwnd, lparam):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                if user32.IsIconic(hwnd):
                    return True

                ex_style = user32.GetWindowLongW(hwnd, -20)  # GWL_EXSTYLE
                if ex_style & 0x00000080:  # WS_EX_TOOLWINDOW
                    return True

                length = user32.GetWindowTextLengthW(hwnd)
                if length <= 0:
                    return True

                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if not title:
                    return True

                cloaked = ctypes.c_int(0)
                dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                if cloaked.value != 0:
                    return True

                rect = RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True

                w = rect.right - rect.left
                h = rect.bottom - rect.top
                if w < 160 or h < 120:
                    return True

                if title in EXCLUDE_TITLES:
                    return True

                pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                results.append({
                    "title": title,
                    "hwnd": int(hwnd),
                    "left": int(rect.left),
                    "top": int(rect.top),
                    "width": int(w),
                    "height": int(h),
                    "pid": int(pid.value)
                })
            except Exception:
                pass
            return True

        cb = WNDENUMPROC(enum_windows_callback)
        user32.EnumWindows(cb, 0)

        title_counts = {}
        for r in results:
            t = r["title"]
            title_counts[t] = title_counts.get(t, 0) + 1

        final_windows = []
        for r in results:
            final_windows.append({
                "title": r["title"],
                "hwnd": r["hwnd"],
                "left": r["left"],
                "top": r["top"],
                "width": r["width"],
                "height": r["height"],
                "pid": r["pid"],
                "duplicate": (title_counts[r["title"]] > 1)
            })

        final_windows.sort(key=lambda x: x["title"])
        return final_windows
    except Exception:
        return []


def find_capture_window(title):
    """保存されたタイトルのウィンドウが今も存在するかを完全一致で確かめる。"""
    for w in enumerate_capture_windows():
        if w.get("title") == title:
            return w
    return None


def even_dimension(value, minimum=2):
    """yuv420p 用に偶数へ切り下げる。"""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return minimum
    if v < minimum:
        return minimum
    if v % 2 != 0:
        v -= 1
    return v


def get_window_rect_by_hwnd(hwnd):
    """ウィンドウハンドルから現在のタイトルと矩形を引く。無効なら None。

    ★ウィンドウの同一性は**タイトルではなくハンドルで持つ**。
      タイトルは動く。実測: YouTube が次の動画へ進んだだけで
      `黄色Vtuber… - YouTube - Google Chrome` が
      `親父の仕事初日 #shorts - YouTube - Google Chrome` に変わり、
      完全一致で引き直していた実装は配信開始12秒で対象を見失って停止した。
      ハンドルなら「利用者が選んだそのウィンドウ」を取り違えずに追い続けられる。
    """
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        u = ctypes.WinDLL("user32", use_last_error=True)
        u.IsWindow.argtypes = [wintypes.HWND]; u.IsWindow.restype = wintypes.BOOL
        u.IsWindowVisible.argtypes = [wintypes.HWND]; u.IsWindowVisible.restype = wintypes.BOOL
        u.IsIconic.argtypes = [wintypes.HWND]; u.IsIconic.restype = wintypes.BOOL
        u.GetWindowTextLengthW.argtypes = [wintypes.HWND]; u.GetWindowTextLengthW.restype = ctypes.c_int
        u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        u.GetWindowTextW.restype = ctypes.c_int
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_RECT)]
        u.GetWindowRect.restype = wintypes.BOOL

        h = wintypes.HWND(int(hwnd))
        if not u.IsWindow(h) or not u.IsWindowVisible(h) or u.IsIconic(h):
            return None
        r = _RECT()
        if not u.GetWindowRect(h, ctypes.byref(r)):
            return None
        w, ht = r.right - r.left, r.bottom - r.top
        if w < 16 or ht < 16:
            return None
        n = u.GetWindowTextLengthW(h)
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(h, buf, n + 1)
        return {"hwnd": int(hwnd), "title": buf.value.strip(),
                "left": int(r.left), "top": int(r.top), "width": int(w), "height": int(ht)}
    except Exception:
        return None


_ddagrab_output_map_cache = {}


def enumerate_display_monitors():
    """接続モニタの矩形を列挙する。[{left, top, width, height, primary}] を返す。"""
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class _RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                        ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

        u = ctypes.WinDLL("user32", use_last_error=True)
        PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                  ctypes.POINTER(_RECT), wintypes.LPARAM)
        u.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(_RECT), PROC, wintypes.LPARAM]
        u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]

        out = []

        def _cb(hmon, hdc, lprc, lparam):
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if u.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                r = mi.rcMonitor
                out.append({"hmon": int(hmon), "left": int(r.left), "top": int(r.top),
                            "width": int(r.right - r.left), "height": int(r.bottom - r.top),
                            "primary": bool(mi.dwFlags & 1)})
            return True

        u.EnumDisplayMonitors(None, None, PROC(_cb), 0)
        return out
    except Exception:
        return []


def get_monitor_for_window(hwnd):
    """ウィンドウが乗っているモニタの矩形。見つからなければ None。"""
    if sys.platform != "win32" or not hwnd:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.MonitorFromWindow.restype = wintypes.HMONITOR
        hm = int(u.MonitorFromWindow(wintypes.HWND(int(hwnd)), 2))  # MONITOR_DEFAULTTONEAREST
        for m in enumerate_display_monitors():
            if m["hmon"] == hm:
                return m
    except Exception:
        pass
    return None


def clamp_rect_to_monitor(left, top, width, height, monitor):
    """ウィンドウ矩形をモニタ矩形の内側へ収め、偶数寸法にする。

    ★ddagrab は「その出力の内側」しか切り出せない。モニタをはみ出す指定は
      起動できない（実測: ウィンドウ幅2568 > モニタ幅2560、オフセット -1 で失敗）。
    """
    mx, my = monitor["left"], monitor["top"]
    mw, mh = monitor["width"], monitor["height"]
    x = max(mx, int(left))
    y = max(my, int(top))
    w = min(int(left) + int(width), mx + mw) - x
    h = min(int(top) + int(height), my + mh) - y
    w -= w % 2
    h -= h % 2
    return (x, y, max(0, w), max(0, h))


def _capture_thumb(args, tag):
    """1フレームだけ取り出して 32x18 のグレースケール列を返す（照合用）。"""
    import tempfile
    path = os.path.join(tempfile.gettempdir(), f"_vrcms_probe_{tag}.png")
    try:
        p = subprocess.run([get_ffmpeg_cmd(), "-hide_banner", *args, "-frames:v", "1", "-y", path],
                           capture_output=True, creationflags=CREATE_NO_WINDOW)
        if p.returncode != 0 or not os.path.exists(path):
            return None
        from PIL import Image
        with Image.open(path) as im:
            return list(im.convert("L").resize((32, 18)).getdata())
    except Exception:
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _probe_monitor_vs_ddagrab(px, py, pw, ph, ox, oy, output_idx, timeout=15):
    """モニタの同じ場所を gdigrab と ddagrab で**同時に**1枚ずつ撮り、差を返す。

    ★別プロセスで順番に撮ってはいけない。撮る瞬間がずれるぶん、画面が動いていると
      正解でも大きく食い違う。実際それで**別のモニタを選ぶ誤判定**を踏んだ
      （同じモニタが diff=3.7 で正解した後、別の時点で diff=31.4 の誤りを掴んだ）。
      1つの ffmpeg に両方を入力として並べれば、ほぼ同時刻の絵どうしを比べられる。
    """
    import tempfile
    a = os.path.join(tempfile.gettempdir(), f"_vrcms_pair_ref_{output_idx}.png")
    b = os.path.join(tempfile.gettempdir(), f"_vrcms_pair_dda_{output_idx}.png")
    cmd = [
        get_ffmpeg_cmd(), "-hide_banner", "-v", "error",
        "-f", "gdigrab", "-framerate", "10",
        "-offset_x", str(px), "-offset_y", str(py),
        "-video_size", f"{pw}x{ph}", "-i", "desktop",
        "-f", "lavfi", "-i",
        f"ddagrab=output_idx={output_idx}:framerate=10:video_size={pw}x{ph}"
        f":offset_x={ox}:offset_y={oy}",
        "-map", "0:v", "-vf", "scale=32:18", "-frames:v", "1", "-y", a,
        "-map", "1:v", "-vf", "hwdownload,format=bgra,scale=32:18", "-frames:v", "1", "-y", b,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW)
        if proc.returncode != 0 or not (os.path.exists(a) and os.path.exists(b)):
            return None
        from PIL import Image
        with Image.open(a) as ia, Image.open(b) as ib:
            ta = list(ia.convert("L").getdata())
            tb = list(ib.convert("L").getdata())
        return sum(abs(x - y) for x, y in zip(ta, tb)) / len(ta)
    except Exception:
        return None
    finally:
        for f in (a, b):
            try:
                os.remove(f)
            except OSError:
                pass


def resolve_ddagrab_output_for_monitor(monitor, max_outputs=8):
    """モニタに対応する ddagrab の output_idx を、実際の絵を照合して決める。

    ★順番の一致を仮定してはいけない。取り違えると**別のモニタをそのまま配信する**。
      ddagrab は出力の位置を返さないため、モニタ矩形と突き合わせる術が無い。

    判定は**絶対値ではなく比**で行う。同時に撮っても完全な同時刻にはならないので、
    正解でも差はそれなりに出る（実測: 正解32.7 / 不正解90.6）。絶対値で線を引くと
    動きの多い画面で常に失格になり、遅い経路へ落ち続けてしまう。
    「次点が最良の2倍以上離れている」ことを条件にすれば、動いていても判別できる。

    決められないときは None を返し、呼び出し側は gdigrab へ退避する
    （遅いが、位置指定が絶対座標なので取り違えは起こらない）。
    """
    key = (monitor["left"], monitor["top"], monitor["width"], monitor["height"])
    if key in _ddagrab_output_map_cache:
        return _ddagrab_output_map_cache[key]

    mx, my = monitor["left"], monitor["top"]
    # ★照合窓は**モニタ全体**にする。中央だけを見ると再生中の動画に支配されて
    #   識別できない。実測（同一条件・4試行）で、中央640x360では比が
    #   1.31/1.14/2.32/1.14 となり3回は**誤った出力が最良**になったが、
    #   モニタ全体なら 4.25/49.16/6.32/4.80 と4回とも正解を明確に判別できた。
    #   タスクバー・ウィンドウ配置・壁紙まで入るぶん、モニタごとの違いが際立つ。
    px, py = mx, my
    pw, ph = monitor["width"], monitor["height"]

    # 動きの大きい瞬間に当たると差が開かず決められない。数回試す。
    # 一度決まればモニタ単位で覚えるので、費用は実質1回きり。
    for attempt in range(3):
        scored = []
        for idx in range(max_outputs):
            d = _probe_monitor_vs_ddagrab(px, py, pw, ph, px - mx, py - my, idx)
            if d is None:
                break
            scored.append((d, idx))

        if not scored:
            return None
        scored.sort()
        best_diff, best_idx = scored[0]
        second = scored[1][0] if len(scored) > 1 else None

        if second is None or second >= best_diff * 2.0:
            log_print(f"[Capture] Monitor origin=({mx},{my}) -> ddagrab output_idx={best_idx} "
                      f"(diff={best_diff:.1f}, second={second}, attempt={attempt + 1})")
            _ddagrab_output_map_cache[key] = best_idx
            return best_idx

    log_print(f"[Capture] ddagrab mapping ambiguous after 3 attempts "
              f"(best={best_diff:.1f} second={second}) -> gdigrab へ退避")
    return None


def resolve_window_capture_plan(win):
    """ウィンドウ取り込みの取り方を決める。

    戻り値は ("ddagrab", output_idx, ox, oy, w, h) か ("gdigrab", x, y, w, h)。

    ★既定を ddagrab にするのは速度のため。gdigrab(BitBlt) は切り出しが大きいほど
      遅くなり、実測で 2568x1401 では実効 23.7fps（30fps指定に対し複製38）まで落ちて
      カクつきとして見えた。同じ範囲でも ddagrab は 29.5fps を維持する
      （640x360 まで小さくすれば gdigrab でも 29.5fps 出るので、サイズ依存であることも確認済み）。
    """
    if not win:
        return None
    mon = get_monitor_for_window(win.get("hwnd"))
    if mon:
        x, y, w, h = clamp_rect_to_monitor(win["left"], win["top"], win["width"], win["height"], mon)
        if w >= 16 and h >= 16:
            idx = resolve_ddagrab_output_for_monitor(mon)
            if idx is not None:
                return ("ddagrab", idx, x - mon["left"], y - mon["top"], w, h)
    # 退避: 合成済みデスクトップからの切り出し（遅いが絵は正しい）
    x, y, w, h = clamp_window_capture_rect(win["left"], win["top"], win["width"], win["height"])
    w -= w % 2
    h -= h % 2
    if w < 16 or h < 16:
        return None
    return ("gdigrab", x, y, w, h)


def get_virtual_screen_rect():
    """仮想デスクトップ全体の矩形 (left, top, width, height)。

    マルチモニタでは原点が負になりうる（実測: 左側にもう1枚あると (-2560, 0)）。
    0 起点だと思い込むと切り出し位置が丸ごとずれる。
    """
    if sys.platform != "win32":
        return (0, 0, 0, 0)
    try:
        import ctypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetSystemMetrics.argtypes = [ctypes.c_int]
        u.GetSystemMetrics.restype = ctypes.c_int
        # SM_XVIRTUALSCREEN=76 / SM_YVIRTUALSCREEN=77 / SM_CXVIRTUALSCREEN=78 / SM_CYVIRTUALSCREEN=79
        return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                u.GetSystemMetrics(78), u.GetSystemMetrics(79))
    except Exception:
        return (0, 0, 0, 0)


def clamp_window_capture_rect(left, top, width, height, virtual_rect=None):
    """ウィンドウ矩形を仮想デスクトップの内側へ収めて (x, y, w, h) を返す。

    ★はみ出しを落とさないと ffmpeg が起動しない。実測でウィンドウが
    `(-2568, -7)` のように画面外へわずかに出ていることがあり、そのまま渡すと
    `Capture area ... extends outside window area ...` で I/O error になる。
    """
    vx, vy, vw, vh = virtual_rect if virtual_rect else get_virtual_screen_rect()
    try:
        left, top, width, height = int(left), int(top), int(width), int(height)
    except (TypeError, ValueError):
        return (0, 0, 0, 0)
    if vw <= 0 or vh <= 0:
        return (left, top, max(0, width), max(0, height))

    x = max(vx, left)
    y = max(vy, top)
    w = min(left + width, vx + vw) - x
    h = min(top + height, vy + vh) - y
    return (x, y, max(0, w), max(0, h))


def build_screen_capture_input(source_type="display", display_index=0, window_title="",
                               framerate=30, draw_mouse=True, window_plan=None):
    """画面キャプチャ入力の ffmpeg 引数を組み立てる。(input_args, needs_hwdownload) を返す。

    ★ウィンドウ取り込みに `gdigrab -i "title=..."` を使ってはいけない。
      あれはウィンドウのDCから BitBlt するので、**GPU合成されたウィンドウが
      真っ黒（または真っ白）になる**。実測: Chrome / Electron(Claude) は
      mean=0.0 の完全な黒、Unity(VRChat) は mean=255.0 の完全な白だった。
      共有したいアプリはほぼ全部これに当たるので、事実上使えない。
      代わりに **合成済みのデスクトップをウィンドウ矩形で切り出す**。
      同じ3ウィンドウが mean=30.6 / 37.2 / 133.7 と正しく映ることを実測で確認済み。
      副作用として、手前に重なった別ウィンドウはそのまま映り込む。
    """
    try:
        fps = int(framerate)
    except (TypeError, ValueError):
        fps = 30
    if fps < 1 or fps > 60:
        fps = 30

    if source_type == "window" and window_title and window_plan:
        kind = window_plan[0]
        if kind == "ddagrab":
            _, idx, ox, oy, w, h = window_plan
            dm = "true" if draw_mouse else "false"
            input_args = [
                "-f", "lavfi", "-thread_queue_size", "1024",
                "-i", (f"ddagrab=output_idx={idx}:framerate={fps}:draw_mouse={dm}"
                       f":video_size={w}x{h}:offset_x={ox}:offset_y={oy}")
            ]
            return (input_args, True)
        if kind == "gdigrab":
            _, x, y, w, h = window_plan
            dm = "1" if draw_mouse else "0"
            # ★offset_x/offset_y は仮想画面の**絶対座標**。原点からの相対値を
            #   渡すと `extends outside window area` で起動しない（実測で確認）。
            input_args = [
                "-f", "gdigrab", "-thread_queue_size", "1024",
                "-framerate", str(fps), "-draw_mouse", dm,
                "-offset_x", str(x), "-offset_y", str(y),
                "-video_size", f"{w}x{h}",
                "-i", "desktop"
            ]
            return (input_args, False)

    # ディスプレイ取り込み（ウィンドウを解決できなかった場合もここへ落ちる）
    try:
        idx = int(display_index)
        if idx < 0:
            idx = 0
    except (TypeError, ValueError):
        idx = 0
    dm = "true" if draw_mouse else "false"
    input_args = [
        "-f", "lavfi", "-thread_queue_size", "1024",
        "-i", f"ddagrab=output_idx={idx}:framerate={fps}:draw_mouse={dm}"
    ]
    return (input_args, True)


def clamp_capture_size_to_destination(width, height, dest_width, dest_height):
    """送出解像度を配信先の解像度以下に抑える。(w, h) を返す。

    ★配信先がRTMP系のとき、シンクは映像を必ず配信先の解像度へ作り直す。
      そこへ 1080p を送っても、縮小されて捨てられるだけで得は無い。
      むしろ送出側の帯域が同じなら、1080p は 720p より1画素あたりのビットが
      減るぶん**途中で痩せる**。実測で、動きのある画面を 1080p / 2000kbps で
      送ると、取り込みが8.8fps相当の動きを持っていても1.3fpsまで潰れた。
      同じ帯域なら配信先と同じ寸法で送った方が良い。

    ビットレートは絞らない。送出が高品質なほど二段目の再エンコードの入力が
    良くなるので、上限を掛けると逆効果になる。
    """
    def _even(v, minimum=2):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return minimum
        if v < minimum:
            return minimum
        return v - (v % 2)

    w, h = _even(width), _even(height)
    dw, dh = _even(dest_width), _even(dest_height)
    if dw >= 2 and w > dw:
        w = dw
    if dh >= 2 and h > dh:
        h = dh
    return (w, h)


def build_screen_video_filter(needs_hwdownload, out_width=1920, out_height=1080,
                              clock_filter=None, in_label="0:v", out_label="vout"):
    """[0:v] から [vout] までの映像フィルタチェーン1本を組み立てる。"""
    w = even_dimension(out_width)
    h = even_dimension(out_height)
    parts = []
    parts.append(f"[{in_label}]")
    if needs_hwdownload:
        parts.append("hwdownload,format=bgra,")
    parts.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=bicubic,")
    parts.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,")
    parts.append("format=yuv420p")
    if clock_filter:
        parts.append("," + clock_filter)
    parts.append(f"[{out_label}]")
    return "".join(parts)


def build_radio_audio_filter(crossfade_seconds, duration=0, seek_seconds=0,
                             base="aresample=async=1"):
    """ラジオ送出の -af 文字列を組み立てる。

    seek_seconds > 0 は「設定変更のホットリロードで曲の途中から張り直した」場合。
    ここでフェードインを掛けると、設定を保存するたびに再生中の曲の音量が
    一度落ちて上がる（利用者には原因の分からない音量ゆらぎに見える）ので掛けない。

    duration が 0（長さ不明）の曲にはフェードアウトを掛けられない。開始位置が
    決まらないうえ、-shortest で入力が尽きる瞬間も事前には読めないため。
    """
    filters = [base] if base else []

    fade = normalize_radio_crossfade(crossfade_seconds)
    try:
        total = max(0.0, float(duration or 0))
    except (TypeError, ValueError):
        total = 0.0
    try:
        seek = max(0.0, float(seek_seconds or 0))
    except (TypeError, ValueError):
        seek = 0.0

    if fade > 0 and total > 0:
        fade = min(fade, total / 4.0)
    if fade < _RADIO_FADE_MIN_SECONDS:
        return ",".join(filters)

    if seek <= 0:
        filters.append(f"afade=t=in:st=0:d={fade:g}")

    if total > 0:
        start = total - seek - fade
        if start > 0:
            filters.append(f"afade=t=out:st={start:.3f}:d={fade:g}")

    return ",".join(filters)


# =============================================================================
# 映像エンコーダーの選択（タスク18: NVENC / QSV / AMF 対応）
# =============================================================================
# 既定は "auto"。起動時に**実際に1回エンコードしてみて**通ったものだけを使う。
# `ffmpeg -encoders` の一覧は当てにならない: 同梱ビルドは h264_nvenc / h264_qsv /
# h264_amf を常に「載せて」おり、GPUもドライバも無い環境でそのまま列挙される。
# ★実測(2026-09-06 / このPC): 一覧には4種すべて出るが、実際に通るのは
#   h264_nvenc と libx264 だけ。h264_qsv は "Error creating a MFX session: -9"、
#   h264_amf は "DLL amfrt64.dll failed to open" で初期化に失敗した。
VIDEO_ENCODERS = ("auto", "libx264", "h264_nvenc", "h264_qsv", "h264_amf")

# auto のときに試す順番。NVENC が最も枯れていて低遅延指定も素直なため先頭。
HW_ENCODER_PRIORITY = ("h264_nvenc", "h264_qsv", "h264_amf")

# プローブ結果のキャッシュ。エンコーダーの可否は実行中に変わらない
# （GPUの抜き差しは再起動を伴う）ので、プロセス内で1度だけ確かめる。
_ENCODER_PROBE_CACHE = {}
_ENCODER_PROBE_LOCK = threading.Lock()


def build_video_encoder_opts(encoder, *, v_kbps, max_kbps, buf_kbps,
                             h264_profile="baseline", sw_preset="ultrafast",
                             sw_tune="zerolatency", level="3.1",
                             gop_frames=None, fps=None, bf_zero=True,
                             sc_threshold_zero=False):
    """`-c:v` から始まる映像エンコード引数一式を組み立てる。

    **エンコーダーごとに完全に別の一覧を返す。共通部分に足し込む形にしてはいけない。**
    ★実測: x264 の値をNVENCに渡すと即座に落ちる
      （`-preset ultrafast` → "Unable to parse preset option value ultrafast"）。
    「とりあえず全部付ける」実装は、HWエンコーダーでは起動不能を意味する。

    引数は「意味」で受け取り、方言への翻訳をここに閉じ込める。
    呼び出し側（動画・写真・待機画面・RTMP送出）は方言を知らなくてよい。
    """
    rate = ["-b:v", f"{v_kbps}k", "-maxrate", f"{max_kbps}k", "-bufsize", f"{buf_kbps}k"]

    if encoder == "h264_nvenc":
        opts = [
            "-c:v", "h264_nvenc",
            # p1=最速。配信は実時間で足りればよく、画質はビットレートで決まる。
            "-preset", "p1" if sw_tune == "zerolatency" else "p4",
            "-tune", "ull" if sw_tune == "zerolatency" else "hq",
            "-rc", "cbr",
            "-profile:v", h264_profile,
        ]
        if level:
            # ★NVENCは 1080p で level 3.1 を拒否する
            #   ("InitializeEncoder failed: invalid param (8): Invalid Level")。
            #   libx264 は黙って辻褄を合わせるので、同じ値を流用すると
            #   「x264では動くのにNVENCだけ起動しない」になる。1080p の実力値へ上げる。
            opts += ["-level", "4.1" if str(level) == "3.1" else str(level)]
        opts += ["-pix_fmt", "yuv420p"] + rate
        if bf_zero:
            opts += ["-bf", "0"]
        # -sc_threshold は libx264 専用。NVENC に渡すと弾かれるので出さない。
    elif encoder == "h264_qsv":
        # このPCにIntel GPUが無く実機確認できていない。誤っていてもプローブが
        # 落として libx264 へ退避するため、配信が止まることはない。
        opts = [
            "-c:v", "h264_qsv",
            "-preset", "veryfast",
            "-profile:v", h264_profile,
        ]
        if level:
            opts += ["-level", "4.1" if str(level) == "3.1" else str(level)]
        # QSVはNV12で受ける。yuv420pを明示するとフォーマット不一致で落ちる環境がある。
        opts += ["-pix_fmt", "nv12"] + rate
        if bf_zero:
            opts += ["-bf", "0"]
    elif encoder == "h264_amf":
        # 同上（AMD GPU無しのため未検証。プローブが可否を決める）。
        opts = [
            "-c:v", "h264_amf",
            "-usage", "lowlatency" if sw_tune == "zerolatency" else "transcoding",
            "-quality", "speed",
            "-rc", "cbr",
            # ★AMFのプロファイル定数は x264 と綴りが違う。"baseline" を渡すと
            #   "Undefined constant or missing '(' in 'baseline'" で起動できない
            #   （このPCではDLLが無く到達しないが、エラー文からは判別できた）。
            "-profile:v", "constrained_baseline" if h264_profile == "baseline" else h264_profile,
        ]
        if level:
            opts += ["-level", "4.1" if str(level) == "3.1" else str(level)]
        opts += ["-pix_fmt", "yuv420p"] + rate
        if bf_zero:
            opts += ["-bf", "0"]
    else:
        # libx264（既定・フォールバック）。
        # ここは既存の実装と1バイトも変えない。preset/tune/level の値は
        # 過去の画質実測（CHANGELOG 2026-08-30）で決まったものなので、
        # 「統一のため」に触らないこと。
        opts = ["-c:v", "libx264", "-preset", sw_preset]
        if sw_tune:
            opts += ["-tune", sw_tune]
        opts += ["-profile:v", h264_profile]
        if level:
            opts += ["-level", str(level)]
        if bf_zero:
            opts += ["-bf", "0"]
        if sc_threshold_zero:
            opts += ["-sc_threshold", "0"]
        opts += ["-pix_fmt", "yuv420p"] + rate

    if gop_frames:
        opts += ["-g", str(gop_frames), "-keyint_min", str(gop_frames)]
    if fps:
        opts += ["-r", str(fps)]
    return opts


def probe_video_encoder(encoder, timeout=20):
    """そのエンコーダーが**このPCで実際に動くか**を1回だけ確かめる（結果はキャッシュ）。

    `ffmpeg -encoders` を見るだけでは不十分。同梱ビルドはGPUの有無に関わらず
    h264_nvenc / h264_qsv / h264_amf を列挙するので、一覧を信じると
    「配信を始めた瞬間に落ちる」設定を選んでしまう。

    そこで **本番と同じ形の引数**で 1080p を数フレームだけ実際に encode する。
    引数の方言違い（level・preset・pix_fmt）もここで一緒に検出できる。
    """
    if encoder == "libx264":
        return True   # 同梱ビルドの必須エンコーダー。これが無ければ何も配信できない。
    with _ENCODER_PROBE_LOCK:
        if encoder in _ENCODER_PROBE_CACHE:
            return _ENCODER_PROBE_CACHE[encoder]

    cmd = [get_ffmpeg_cmd(), "-hide_banner", "-loglevel", "error",
           "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=0.2"]
    cmd += build_video_encoder_opts(encoder, v_kbps=2500, max_kbps=3000, buf_kbps=2000)
    cmd += ["-f", "null", "-"]

    ok = False
    detail = ""
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        try:
            _out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            kill_proc(proc)
            _out, err = "", "probe timed out"
        # 終了コードだけで判定する。stderr の文言はFFmpegの版で変わるうえ、
        # 成功時にも警告が出る。
        ok = (proc.returncode == 0)
        detail = (err or "").strip().splitlines()[0] if err else ""
    except Exception as e:
        ok, detail = False, str(e)

    with _ENCODER_PROBE_LOCK:
        _ENCODER_PROBE_CACHE[encoder] = ok
    log_print(f"[Encoder] Probe {encoder}: {'available' if ok else 'unavailable'}"
              + (f" ({detail})" if not ok and detail else ""))
    return ok


def resolve_video_encoder(requested):
    """設定値を「実際に使うエンコーダー名」へ解決する。

    - "auto": NVENC → QSV → AMF の順に試し、通ったものを使う。全滅なら libx264。
    - 明示指定: そのエンコーダーが**動くことを確かめてから**使う。動かなければ
      libx264 へ退避する。利用者が選んだ設定を尊重して落ちるより、
      配信が続く方が価値が高い（設定画面には実際に使われている方を表示する）。
    """
    requested = str(requested or "auto").strip() or "auto"
    if requested not in VIDEO_ENCODERS:
        log_print(f"[Encoder] Unknown video_encoder {requested!r}; falling back to auto.")
        requested = "auto"

    if requested == "libx264":
        return "libx264"
    if requested == "auto":
        for candidate in HW_ENCODER_PRIORITY:
            if probe_video_encoder(candidate):
                return candidate
        return "libx264"
    if probe_video_encoder(requested):
        return requested
    log_print(f"[Encoder] {requested} is not usable on this PC; using libx264 instead.")
    return "libx264"



def get_live_clock_drawtext_filter(x="w-tw-45", y="26", font_size=28, bold=True):
    """リアルタイムLIVE時計オーバーレイ用 drawtext フィルタ文字列を生成"""
    font_path = get_drawtext_font_path(bold=bold)
    return (
        f"drawtext=fontfile='{font_path}':"
        # %T は strftime の %H:%M:%S 相当。時刻書式に「:」を直接書くと、
        # フィルタグラフ解析でエスケープが外れて localtime に4引数が渡り、
        # 「%{localtime} requires at most 1 arguments」で描画自体が消える。
        f"text='● LIVE %{{localtime\\:%T}} JST':"
        f"fontsize={font_size}:fontcolor=white:"
        f"box=1:boxcolor=0x0F172A@0.82:boxborderw=8:"
        f"x={x}:y={y}"
    )

def get_clock_filter_for_config(config=None):
    """configの設定（overlay_clock_position）に基づいて drawtext フィルタ文字列を生成"""
    if config is None:
        config = {}
    clock_pos = config.get("overlay_clock_position", "top-right") if isinstance(config, dict) else "top-right"
    if clock_pos == "top-left":
        clock_x, clock_y = "45", "26"
    elif clock_pos == "bottom-right":
        clock_x, clock_y = "w-tw-45", "h-th-26"
    elif clock_pos == "bottom-left":
        clock_x, clock_y = "45", "h-th-26"
    else:  # "top-right" default
        clock_x, clock_y = "w-tw-45", "26"
    return get_live_clock_drawtext_filter(x=clock_x, y=clock_y, font_size=28)

def get_pil_font(size=24, bold=False):
    """PIL用の日本語対応フォントを安全に取得"""
    candidates = [
        "C:/Windows/Fonts/meiryob.ttc" if bold else "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothB.ttc" if bold else "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "meiryob.ttc" if bold else "meiryo.ttc",
        "arialbd.ttf" if bold else "arial.ttf",
        "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()

MAX_PLAYLIST_ITEMS = 50
MAX_QUEUE_CAPACITY = 200
MAX_PHOTO_CAPACITY = 200

# ストリーム再構築要求のデバウンス。
# 写真の追加/削除は1枚ごとに再構築を要求するため、GUIから70枚まとめて追加すると
# 約22秒（実測309ms/枚）にわたり毎回 ffmpeg が kill→再起動され、HLSセグメントが
# 安定して出力されず配信が停止する。最後の要求から静穏になるまで待って1回だけ再構築する。
RELOAD_DEBOUNCE_SECONDS = 1.0
# 要求が途切れず続く場合でも、この秒数を超えたら反映する（際限なく先送りしない）。
RELOAD_MAX_DEFER_SECONDS = 10.0

def is_safe_url(url):
    """URLが安全か（http/https、SSRF・ローカルアドレス拒否）を検証"""
    if not url or not isinstance(url, str):
        return False, "Empty or invalid URL"
    url = url.strip()
    if len(url) > 2048:
        return False, "URL too long (max 2048 chars)"

    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
    except Exception:
        return False, "Malformed URL"

    if parsed.scheme not in ("http", "https"):
        return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http/https are allowed."

    host = (parsed.hostname or "").lower()
    if not host:
        return False, "Missing hostname in URL"

    # ローカル・プライベートIP、イントラネットアドレスのブロック (SSRF対策)
    blocked_hosts = ("localhost", "127.0.0.1", "0.0.0.0", "::1")
    if host in blocked_hosts or host.endswith(".local") or host.endswith(".lan") or host.endswith(".internal"):
        return False, "Access to local/private network addresses is forbidden"

    import ipaddress
    import socket

    def _is_forbidden_ip(ip_str):
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return False
        # IPv4射影IPv6 (::ffff:127.0.0.1) は元のIPv4に戻して判定する
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
        return (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified)

    # 表記そのものがIPアドレスの場合
    if _is_forbidden_ip(host):
        return False, "Access to private/loopback IP is forbidden"

    # ホスト名を実際に解決して判定する。
    # これにより 10進表記 (http://2130706433/) や、内部IPを指すドメイン名も弾ける。
    try:
        resolved = socket.getaddrinfo(host, None)
    except Exception:
        return False, "Hostname could not be resolved"

    for info in resolved:
        if _is_forbidden_ip(info[4][0]):
            return False, "Hostname resolves to a private/loopback address"

    return True, "OK"

def is_image_url_or_file(path_or_url):
    """パスまたはURLが画像形式かどうかを判定"""
    if not path_or_url or not isinstance(path_or_url, str):
        return False
    clean = path_or_url.split("?")[0].split("#")[0].lower()
    return clean.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))

def is_video_url_or_file(path_or_url):
    """パスまたはURLが動画形式かどうかを判定"""
    if not path_or_url or not isinstance(path_or_url, str):
        return False
    clean = path_or_url.split("?")[0].split("#")[0].lower()
    return clean.endswith((".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".ts", ".flv"))

def _run_probe(cmd, timeout):
    """probe用の外部プロセスを実行し、呼び出し元を絶対に永久ブロックさせない。

    subprocess.run(timeout=...) は TimeoutExpired を投げる前に kill() したうえで
    タイムアウト無しの communicate() を呼ぶ。子プロセスが低速な外付けHDD/USB/
    ネットワークドライブの I/O 待ちで止まっていると TerminateProcess は即座には
    効かず、この2回目の communicate() が戻らない。呼び出し元スレッドはそこで
    永久に刺さる。そのため reap 側にもタイムアウトを置き、最後は子を捨てて必ず戻る。

    戻り値: (stdout, stderr) いずれも str。失敗時は ("", "")。
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,   # --noconsole ビルドでは stdin ハンドルが無効。
                                        # ffmpeg は対話コマンド用に stdin を読むため必須。
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
    except Exception:
        return "", ""

    try:
        return proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        log_print(f"[Probe] Timed out after {timeout}s: {os.path.basename(str(cmd[-1]))}")
    except Exception:
        pass

    try:
        proc.kill()
    except Exception:
        pass
    try:
        # kill が効かない（I/O待ちで停止中）場合でもここで諦めて戻る。
        # 子はデーモン扱いで放置し、OSがドライブ復帰後に回収する。
        proc.communicate(timeout=2)
    except Exception:
        pass
    return "", ""


def get_video_file_duration(file_path):
    """ffprobe または ffmpeg を用いてローカル動画の再生時間（秒）を取得"""
    if not file_path or not os.path.exists(file_path):
        return 0.0

    # 外付けHDD/USB/NAS 上のファイルはシーク1回が数秒かかる。
    # ffprobe は 0.3秒前後で終わるが、ffmpeg -i へのフォールバックは
    # ローカルSSDでも約3秒かかる（実測）ため、遅いメディアを想定した秒数にする。
    try:
        out, _ = _run_probe([
            get_ffprobe_cmd(),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ], timeout=20)
        if out.strip():
            val = float(out.strip())
            if val > 0:
                return val
    except Exception:
        pass

    try:
        _, err = _run_probe([get_ffmpeg_cmd(), "-i", file_path], timeout=30)
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", err)
        if m:
            hours, minutes, seconds = float(m.group(1)), float(m.group(2)), float(m.group(3))
            return hours * 3600 + minutes * 60 + seconds
    except Exception:
        pass

    log_print(f"[Probe] Could not determine duration: {os.path.basename(str(file_path))}")
    return 0.0


# ストリームコピーを許す画素フォーマット。yuvj420p はレンジ表記が違うだけの同一構造。
# 4:2:2 / 10bit は AVPro 側で再生できない環境があるため通さない。
COPY_SAFE_PIX_FMTS = frozenset({"yuv420p", "yuvj420p"})


def probe_video_stream_params(file_path):
    """ローカル動画の映像ストリーム諸元を取得する。取得できなければ None。

    ここで見るのは「再エンコードせずにそのまま流せるか」の判断に必要な項目だけ。
    低速メディアで固まらないよう、必ず _run_probe 経由で叩く。
    """
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        out, _ = _run_probe([
            get_ffprobe_cmd(),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,pix_fmt,height,r_frame_rate,avg_frame_rate",
            "-of", "default=noprint_wrappers=1",
            file_path
        ], timeout=20)
    except Exception:
        return None

    params = {}
    for line in out.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            params[k.strip()] = v.strip()
    return params or None


def _parse_fps(value):
    """ffprobe の "30000/1001" 形式を float にする。不明なら 0.0。"""
    try:
        num, _, den = str(value).partition("/")
        den = float(den) if den else 1.0
        return float(num) / den if den else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def can_stream_copy_local_video(params, max_height):
    """再エンコードせずにそのまま送出してよいローカル動画かを判定する。

    ローカルファイルを無条件に再エンコードすると、URL追加なら無劣化で届く映像が
    アップロードした途端に作り直される（実測: 4.76Mbps の原本が 2500kbps へ再圧縮され
    SSIM 1.000 → 0.9918）。**同じ品質で出す**には、安全に通せるものは通すしかない。

    通す条件は「受信側FFmpegとAVProがそのまま扱える形であること」に限る:
      - H.264 / yuv420p 系（HEVC・VP9・10bit・4:2:2 は再生できない環境がある）
      - 配信上限の高さ以内（4K をそのまま投げても VRChat 側で扱えない）
      - CFR であること。スマホ動画に多い VFR をコピーすると、
        タイムスタンプがそのまま下流へ渡って音ズレの原因になる。
    判定できない項目が一つでもあれば「通さない」に倒す（fail-closed）。
    """
    if not params:
        return False, "probe failed"
    if params.get("codec_name") != "h264":
        return False, f"codec={params.get('codec_name')}"
    if params.get("pix_fmt") not in COPY_SAFE_PIX_FMTS:
        return False, f"pix_fmt={params.get('pix_fmt')}"
    try:
        height = int(params.get("height") or 0)
    except (TypeError, ValueError):
        height = 0
    if height <= 0:
        return False, "height unknown"
    if max_height and height > max_height:
        return False, f"height={height}>{max_height}"

    r_fps = _parse_fps(params.get("r_frame_rate"))
    avg_fps = _parse_fps(params.get("avg_frame_rate"))
    if r_fps <= 0 or avg_fps <= 0:
        return False, "fps unknown"
    # 1%を超えて食い違うものは可変フレームレートとみなす
    if abs(r_fps - avg_fps) / max(r_fps, avg_fps) > 0.01:
        return False, f"vfr({r_fps:.2f}/{avg_fps:.2f})"

    return True, f"h264 {height}p {avg_fps:.2f}fps"


def extract_pts_from_ts_chunk(chunk):
    """MPEG-TSチャンクから再生位置PTS（秒）を抽出する。

    映像PES・音声PESそれぞれの最新PTSを個別に拾い、**遅れている方（min）** を返す。
    以前は「チャンク内で最後に見つかったPTS」をそのまま返していたため、
    映像だけが音声より数十秒先行して多重化された場合（concat スライドショー背景で発生）、
    relay_stream_data のペーシングが先行した映像PTSを実際の配信位置と誤認し、
    先読みバッファ制御が効かずに実時間の数倍速で送出しきってしまっていた。
    配信位置として意味を持つのは遅れている側なので min を採用する。
    """
    length = len(chunk)
    if length < 188:
        return None
    latest_video_pts = None
    latest_audio_pts = None
    offset = 0
    while offset + 188 <= length:
        if chunk[offset] == 0x47:
            pkt = chunk[offset:offset+188]
            payload_unit_start = bool(pkt[1] & 0x40)
            adaptation_field_ctrl = (pkt[3] >> 4) & 0x03
            
            payload_offset = 4
            if adaptation_field_ctrl in (2, 3):
                adaptation_len = pkt[4]
                payload_offset += 1 + adaptation_len
                
            if payload_unit_start and payload_offset + 9 <= 188:
                if pkt[payload_offset] == 0x00 and pkt[payload_offset+1] == 0x00 and pkt[payload_offset+2] == 0x01:
                    stream_id = pkt[payload_offset+3]
                    is_video = 0xE0 <= stream_id <= 0xEF
                    is_audio = 0xC0 <= stream_id <= 0xDF
                    if is_video or is_audio:
                        flags2 = pkt[payload_offset+7]
                        pts_flag = (flags2 >> 7) & 0x01
                        if pts_flag and payload_offset + 14 <= 188:
                            b0 = pkt[payload_offset+9]
                            b1 = pkt[payload_offset+10]
                            b2 = pkt[payload_offset+11]
                            b3 = pkt[payload_offset+12]
                            b4 = pkt[payload_offset+13]
                            pts = (((b0 & 0x0E) << 29) | ((b1 & 0xFF) << 22) |
                                   ((b2 & 0xFE) << 14) | ((b3 & 0xFF) << 7) |
                                   ((b4 & 0xFE) >> 1))
                            pts_sec = pts / 90000.0
                            if is_video:
                                latest_video_pts = pts_sec
                            else:
                                latest_audio_pts = pts_sec
            offset += 188
        else:
            next_sync = chunk.find(b'\x47', offset + 1)
            if next_sync == -1:
                break
            offset = next_sync

    found = [p for p in (latest_video_pts, latest_audio_pts) if p is not None]
    if not found:
        return None
    return min(found)

class LayeredConfig(dict):
    """3層（既定値 < config.json < CLI/環境変数）の設定を、単一の dict として見せる。

    `self.config[...]` の参照箇所がコード全体で200箇所を超えるため、dict を別の型へ
    差し替えず dict のサブクラスにしている。dict としての中身は常に「実効値」
    （3層をマージした結果）なので、既存の読み取り・書き込みは無修正で動く。

    書き込みには意味の異なる2種類があり、混ぜると壊れる:
      - ``cfg[key] = value`` : 利用者が設定を変えた → 永続層(user)へ記録する。
        ただし CLI で上書き中のキーは、その起動中の実効値を CLI 値のまま保つ。
      - ``set_override(key, value)`` : その起動限りの指定 → 永続層には絶対に触れない。

    以前は「CLI値を実効設定へ直接載せ、保存直前に元の値へ戻す」方式だったが、
    GUI の設定画面がフォーム全体（＝CLI上書き後の実効値）を送り返すため、
    「利用者が変更した」と誤認して CLI 値が config.json へ焼き付いていた。
    """

    def __init__(self, defaults=None):
        super().__init__()
        self._defaults = dict(defaults or {})
        self._user = {}
        self._overrides = {}
        self._override_sources = {}
        self._recompute()

    # --- 層の入れ替え ---------------------------------------------------
    def load_user(self, data):
        """config.json から読んだ内容を永続層として据える（実効値は再計算）。"""
        self._user = dict(data or {})
        self._recompute()

    def set_override(self, key, value, source="cli"):
        """その起動限りの上書きを設定する。永続層には触れない。"""
        self._overrides[key] = value
        self._override_sources[key] = source
        self._recompute()

    def clear_override(self, key):
        """上書きを解除する（利用者がその項目を明示的に変更したとき）。"""
        existed = self._overrides.pop(key, None) is not None
        self._override_sources.pop(key, None)
        if existed:
            self._recompute()
        return existed

    # --- 参照 -----------------------------------------------------------
    def is_overridden(self, key):
        return key in self._overrides

    def override_source(self, key):
        """上書きの出所（"cli" / "env" / "api" 等）。上書きが無ければ None。"""
        return self._override_sources.get(key)

    def overrides(self):
        return dict(self._overrides)

    def override_sources(self):
        return dict(self._override_sources)

    def persistable(self):
        """config.json へ書き出すべき内容（既定値＋利用者設定。上書きは含めない）。

        既定値も含めるのは、従来どおり人が読める完全な config.json を保つため。
        含めなくても動作は同じだが、既存ファイルの項目が保存のたびに消えてしまう。
        """
        merged = dict(self._defaults)
        merged.update(self._user)
        return merged

    def defaults(self):
        return dict(self._defaults)

    # --- 書き込み（＝永続層への記録） -----------------------------------
    def __setitem__(self, key, value):
        self._user[key] = value
        self._recompute_key(key)

    def __delitem__(self, key):
        self._user.pop(key, None)
        self._recompute_key(key)

    def pop(self, key, *args):
        current = self.get(key, *args) if args else self[key]
        self._user.pop(key, None)
        self._recompute_key(key)
        return current

    def update(self, *args, **kwargs):
        incoming = dict(*args, **kwargs)
        for key, value in incoming.items():
            self[key] = value

    def setdefault(self, key, default=None):
        if key in self:
            return self[key]
        self[key] = default
        return self[key]

    def clear(self):
        self._user = {}
        self._recompute()

    # --- 実効値の再計算 --------------------------------------------------
    def _effective(self, key):
        if key in self._overrides:
            return self._overrides[key]
        if key in self._user:
            return self._user[key]
        return self._defaults.get(key)

    def _recompute_key(self, key):
        if key in self._overrides or key in self._user or key in self._defaults:
            dict.__setitem__(self, key, self._effective(key))
        else:
            dict.pop(self, key, None)

    def _recompute(self):
        dict.clear(self)
        merged = dict(self._defaults)
        merged.update(self._user)
        merged.update(self._overrides)
        dict.update(self, merged)


class StreamerCore:
    def __init__(self, override_port=None, override_host=None, override_enable_tunnel=None,
                 overrides=None, config_path=None):
        # config.json のパスは差し替え可能にしてある。モジュール定数のまま固定すると
        # 単体テストが利用者の実ファイルを書き換えてしまう（実際に汚染が起きた）。
        self.config_path = config_path or CONFIG_FILE
        self.config = LayeredConfig(DEFAULT_CONFIG)
        self.load_config()
        # コマンドライン引数・環境変数による上書きは「その起動限りの指定」であり、
        # config.json には焼き付けない。LayeredConfig の上書き層に載せることで、
        # 実効値としては最優先されつつ、保存対象からは構造的に外れる。
        for key, value in (("port", override_port), ("host", override_host)):
            if value is not None:
                self.config.set_override(key, value, "cli")
        if override_enable_tunnel is not None:
            self.config.set_override("enable_tunnel", bool(override_enable_tunnel), "cli")
        # 汎用の上書き（--set / 環境変数 / 追加CLI引数）。{key: (value, source)} 形式。
        for key, entry in (overrides or {}).items():
            if isinstance(entry, tuple):
                value, source = entry
            else:
                value, source = entry, "cli"
            self.config.set_override(key, value, source)

        os.makedirs(HLS_DIR, exist_ok=True)
        self.clean_hls_dir(all_files=True, preserve_images=False)

        # プロセスと同期
        self.hls_proc = None
        self.send_proc = None
        self.tunnel_proc = None
        self.current_stdin = None

        # 配信先（destination）状態: タスク14
        # active_output_mode は「設定上の配信先」ではなく「今この瞬間に動いている出口」。
        # HLSへ自動退避しているときに両者がずれるため、必ず分けて持つ。
        self.active_output_mode = self.get_output_mode()
        self.destination_fallback_active = False
        self.destination_last_error = ""
        self.last_config_warnings = []   # 直近の設定保存で弾いた値の理由（UIへ返す）
        self._sink_fail_count = 0        # 現在の再接続サイクル内での連続失敗数
        self._sink_fallback_rounds = 0   # HLSへ退避した回数（バックオフ長の算出に使う）
        self._sink_started_at = 0.0
        self._sink_retry_at = 0.0
        self._sink_force_restart = False
        self._sink_stderr_tail = collections.deque(maxlen=20)

        self.play_queue = [] # list of dict: [{"title": "...", "url": "...", "duration": ..., "type": "video"}]
        self.photo_pool = [] # list of dict: [{"id": "...", "type": "image", "title": "...", "url": "...", "path": "...", "duration": ...}]
        self.history_stack = [] # 履歴管理用 (最大20件)
        self.queue_lock = threading.Lock()
        self.photo_lock = threading.Lock()
        self.process_lock = threading.Lock()
        self.slideshow_index = 0

        # 累積PTSとシームレス遷移管理
        self.accumulated_pts = 0.0
        self.last_selected_height = 0
        self.last_stream_duration = 0.0
        self.prefetch_cache = {}
        self.prefetch_lock = threading.Lock()

        # 状態
        # status: "offline", "buffering", "streaming", "finishing", "error"
        self.status = "offline"
        self.status_detail = "Offline (Queue Empty)"
        self.current_video = None # {"title": "...", "url": "...", "duration": ..., "type": ...}
        self.tunnel_url = "" # "https://xxx.trycloudflare.com/stream.m3u8"
        self.tunnel_raw_url = "" # "https://xxx.trycloudflare.com"
        self.is_running = True
        self.image_paused = not bool(self.config.get("image_auto_advance", False)) # 写真スライドショー一時停止フラグ
        self.slideshow_cursor = 0 # ラジオ背景スライドショーの再生位置（曲をまたいで巡回させる）

        self.skip_event = threading.Event()
        self.video_done_event = threading.Event()
        self.reload_stream_event = threading.Event()
        self.reload_requested_at = 0.0       # 直近の要求時刻（デバウンス判定用）
        self.reload_first_requested_at = 0.0 # 未処理の要求列の先頭時刻（先送り上限用）
        self.current_video_start_time = None

    def request_stream_reload(self):
        """ストリームの再構築を要求する。連続呼び出しはデバウンスされ1回にまとまる。"""
        now = time.time()
        if not self.reload_stream_event.is_set():
            self.reload_first_requested_at = now
        self.reload_requested_at = now
        self.reload_stream_event.set()

    def _reload_due(self):
        """再構築要求が「もう静穏になった」か。監視ループ側から呼ぶ。"""
        if not self.reload_stream_event.is_set():
            return False
        now = time.time()
        if now - self.reload_first_requested_at >= RELOAD_MAX_DEFER_SECONDS:
            return True
        return (now - self.reload_requested_at) >= RELOAD_DEBOUNCE_SECONDS

    def clean_hls_dir(self, all_files=False, preserve_images=False):
        """HLS出力ディレクトリのクリーンアップ。

        all_files=True でサブディレクトリを含めて全削除する。
        preserve_images=True のときは images/（利用者がアップロードした写真と
        ラジオカードのキャッシュ）だけを残す。起動・終了のたびにここを消していたため、
        アップロード済みの写真が毎回失われ、ラジオ背景のスライドショーが
        「設定しても何も表示されない」状態になっていた。
        """
        if not os.path.exists(HLS_DIR):
            return
        preserved = {"images", "videos"} if preserve_images else set()
        for attempt in range(5):
            try:
                remaining = False
                for item in os.listdir(HLS_DIR):
                    if item in preserved:
                        continue
                    item_path = os.path.join(HLS_DIR, item)
                    if all_files:
                        try:
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path, ignore_errors=True)
                            else:
                                os.remove(item_path)
                        except Exception:
                            remaining = True
                    else:
                        if item.endswith(".ts") or item.endswith(".m3u8"):
                            try:
                                os.remove(item_path)
                            except Exception:
                                remaining = True
                if not remaining and (not all_files or not (set(os.listdir(HLS_DIR)) - preserved)):
                    break
                time.sleep(0.2)
            except Exception as e:
                log_print(f"[Core] Warning cleaning HLS dir: {e}")
                time.sleep(0.2)

    @property
    def enable_tunnel(self):
        """設定の写しを別途持たない。以前は3箇所で代入しており、設定と食い違う余地があった。"""
        return bool(self.config.get("enable_tunnel", True))

    @enable_tunnel.setter
    def enable_tunnel(self, value):
        # 利用者による変更として永続層へ記録する。CLI で上書き中なら
        # その起動中の実効値は CLI 値のまま（LayeredConfig 側で保証）。
        self.config["enable_tunnel"] = bool(value)

    def load_config(self):
        path = getattr(self, "config_path", CONFIG_FILE)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    if isinstance(saved, dict):
                        # 永続層として据える。update() だと利用者の変更として扱われ、
                        # CLI上書きとの区別がつかなくなる。
                        self.config.load_user(saved)
                log_print(f"[Core] Loaded config from {path}")
            except Exception as e:
                log_print(f"[Core] Error reading config: {e}")

    def _write_config_file(self):
        """config.json への書き出し本体。CLI/環境変数由来の上書きは構造的に含まれない。"""
        path = getattr(self, "config_path", CONFIG_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.config.persistable(), f, indent=2, ensure_ascii=False)

    def save_config(self, new_config=None):
        destination_changed = False
        if new_config:
            # CLI/環境変数で上書き中のキーが「実効値と同じ値」で返ってきた場合は、
            # 利用者が触ったのではなく設定画面がフォーム全体をそのまま送り返しただけ。
            # ここで弾かないと、--no-tunnel で起動して別項目を保存しただけで
            # enable_tunnel:false が config.json に焼き付く（実際に起きていた）。
            echoed = [
                k for k, v in new_config.items()
                if self.config.is_overridden(k) and v == self.config.get(k)
            ]
            if echoed:
                new_config = {k: v for k, v in new_config.items() if k not in echoed}
                log_print(f"[Config] Ignored echoed override values (not persisted): {', '.join(sorted(echoed))}")
        if new_config:
            # UI/GUI が表示用のマスク値をそのまま送り返してきた場合、本物のキーを潰さない
            for key_field in ("topaz_stream_key", "generic_rtmp_key"):
                if key_field in new_config and self.is_masked_stream_key(new_config.get(key_field)):
                    new_config = dict(new_config)
                    new_config.pop(key_field, None)
            destination_changed = any(
                k in new_config and new_config.get(k) != self.config.get(k)
                for k in DESTINATION_CONFIG_KEYS
            )
        endpoint_errors = []
        if new_config:
            for field in self.ENDPOINT_SCHEMES:
                if field not in new_config:
                    continue
                normalized, reason = self.validate_endpoint(field, new_config.get(field))
                if reason:
                    # 不正な値は採用しない（黙って壊れた設定を保存しない）
                    endpoint_errors.append(reason)
                    log_print(f"[Destination] Rejected invalid endpoint: {reason}")
                    new_config = dict(new_config)
                    new_config.pop(field, None)
                elif not normalized and field.startswith("topaz_"):
                    # TopazChat のエンドポイントは空にできない。既定値へ戻す
                    new_config = dict(new_config)
                    new_config[field] = DEFAULT_CONFIG[field]
                else:
                    new_config = dict(new_config)
                    new_config[field] = normalized

        # 検証エラーは「接続状態」とは別物として持つ。destination_last_error に入れると
        # シンクの起動成功で即座に消されてしまい、利用者に理由が届かない。
        self.last_config_warnings = list(endpoint_errors)

        if new_config:
            self.config.update(new_config)
            # 利用者が明示的に「別の値」へ変更した項目は、その起動中も変更を反映させる。
            # （エコー分は上で除外済みなので、ここに残るのは意図的な変更だけ）
            for key in list(new_config.keys()):
                if self.config.is_overridden(key):
                    self.config.clear_override(key)
                    log_print(f"[Config] Override for '{key}' released by explicit change.")
        try:
            # 上限超過の設定値は「接続した瞬間に切断される」ため、保存前にクランプする
            self.clamp_rtmp_bitrates()
            self._write_config_file()
            log_print(f"[Core] Saved config to {CONFIG_FILE}")

            if destination_changed:
                # 配信先を変えたらシンクを作り直す。退避状態とリトライ計数もここで解除する。
                log_print(f"[Destination] Destination settings changed. Rebuilding sink (mode={self.get_output_mode()}).")
                self.destination_fallback_active = False
                self.destination_last_error = ""
                self._sink_fail_count = 0
                self._sink_fallback_rounds = 0
                self._sink_retry_at = 0.0
                self._sink_force_restart = True
                self.ensure_stream_sink()
                self.request_stream_reload()

            # 最新設定でQRオーバーレイ・待機画像を即座に再生成
            self.generate_qr_overlay_image()
            self.generate_standby_image()

            with self.queue_lock:
                is_queue_empty = (len(self.play_queue) == 0 and self.current_video is None)
                is_playing = (self.current_video is not None)

            # 待機中（キュー空）なら待機ストリームを即座にリロード
            if is_queue_empty and self.send_proc:
                log_print("[Core] Hot-reloading standby stream with updated settings...")
                with self.process_lock:
                    kill_proc(self.send_proc)
            elif is_playing:
                # 動画または写真の再生中なら、即座に現在のストリームをホットリロード
                log_print("[Core] Triggering hot-reload of active stream with updated settings...")
                self.request_stream_reload()

            return True
        except Exception as e:
            log_print(f"[Core] Failed to save config: {e}")
            return False

    def get_video_encoder(self):
        """今この瞬間に使う映像エンコーダー名。

        解決結果はインスタンスに保持する。プローブは実エンコードを1回走らせるので、
        再生のたびに呼ぶと切り替えが目に見えて遅くなる。設定が変わったときだけ
        引き直す（設定画面で選び直した直後から効かせるため）。
        """
        requested = str(self.config.get("video_encoder", "auto") or "auto")
        if getattr(self, "_video_encoder_requested", None) != requested:
            self._video_encoder_requested = requested
            self._video_encoder_resolved = resolve_video_encoder(requested)
            log_print(f"[Encoder] video_encoder={requested} -> using {self._video_encoder_resolved}")
        return self._video_encoder_resolved

    def is_web_remote_enabled(self):
        """Webリモコン（ゲスト向けの画面とAPI）を開いているか。タスク21。

        未設定は True（＝従来どおり開く）。既存ユーザーの設定ファイルには
        このキーが無いため、ここを fail-closed にすると更新した全員のリモコンが
        黙って死ぬ。「無効化」は利用者が明示的に選んだときだけ効かせる。
        """
        return bool(self.config.get("enable_web_remote", True))

    def get_status_data(self, include_secrets=False):
        """配信状態一式。include_secrets=True はローカルホスト（ホスト本人）専用。

        ストリームキーは /api/status 経由でゲストにも渡るため、既定ではマスクする。
        """
        with self.queue_lock:
            queue_copy = [dict(item) for item in self.play_queue]
            has_prev = len(self.history_stack) >= 2

        port = self.config.get("port", 8000)
        if self.tunnel_raw_url:
            stream_url = f"{self.tunnel_raw_url}/stream.m3u8"
            public_url = self.tunnel_raw_url
        elif not self.enable_tunnel:
            stream_url = f"http://localhost:{port}/stream.m3u8"
            public_url = f"http://localhost:{port}"
        else:
            stream_url = ""
            public_url = ""

        # ホスト専用モードでは誰も開けないURLなので、リモコンURLは配らない。
        # ここを残すと、UIもQRも「アクセスできないURL」を表示し続ける。
        web_remote_enabled = self.is_web_remote_enabled()
        if not web_remote_enabled:
            public_url = ""

        is_image = bool(self.current_video and self.current_video.get("type") == "image")

        destination = self.get_destination_info(include_secrets=include_secrets)
        # destination 導入後は「ワールドの動画プレイヤーに貼るURL」と
        # 「Webリモコンを開くURL」が別物になる。QRが焼くのは後者だけ。
        video_url = destination.get("video_url", "")
        if self.get_active_output_mode() == "hls":
            video_url = stream_url

        return {
            "status": self.status,
            "status_detail": self.status_detail,
            "app_version": APP_VERSION,
            "tunnel_url": public_url,
            # 「Cloudflareトンネルが実際に張れているか」。UIのトンネル表示はこれを見る。
            # tunnel_url / tunnel_raw_url は --no-tunnel のとき start_tunnel() が
            # localhost を代入するため、どちらも真偽判定には使えない
            # （UIが Local Test 起動でも常に Active と表示していた原因）。
            "tunnel_active": bool(self.enable_tunnel and self.tunnel_raw_url),
            "stream_url": stream_url,
            "video_url": video_url,
            "remote_url": public_url,
            "destination": destination,
            "output_mode": destination["output_mode"],
            "active_output_mode": destination["active_output_mode"],
            "local_url": f"http://localhost:{port}",
            "enable_tunnel": self.enable_tunnel,
            "current_video": self.current_video,
            "queue": queue_copy,
            "loop_queue": bool(self.config.get("loop_queue", False)),
            "shuffle": bool(self.config.get("shuffle", False)),
            "is_image": is_image,
            "image_paused": self.image_paused,
            "image_display_duration": int(self.config.get("image_display_duration", 15)),
            "image_auto_advance": bool(self.config.get("image_auto_advance", False)),
            "enable_web_remote": web_remote_enabled,
            # 設定値と「実際に使われているもの」は食い違いうる（GPUが無い等）。
            # 片方しか出さないと、退避したことが利用者から見えない。
            "video_encoder": str(self.config.get("video_encoder", "auto")),
            "active_video_encoder": self.get_video_encoder(),
            # QRはリモコンURLを焼いたものなので、リモコンが無効なら「消えている」状態を返す。
            # 設定値そのものは書き換えない（再度有効化したら元の設定に戻る）。
            "overlay_qr_enabled": web_remote_enabled and bool(self.config.get("overlay_qr_enabled", False) or self.config.get("overlay_qr_video", False) or self.config.get("overlay_qr_image", False)),
            "overlay_qr_video": web_remote_enabled and bool(self.config.get("overlay_qr_video", False)),
            "overlay_qr_image": web_remote_enabled and bool(self.config.get("overlay_qr_image", False)),
            "overlay_qr_mode": str(self.config.get("overlay_qr_mode", "bottom-right")),
            "overlay_clock_enabled": bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False)),
            "overlay_clock_video": bool(self.config.get("overlay_clock_video", False)),
            "overlay_clock_position": str(self.config.get("overlay_clock_position", "top-right")),
            "playback_mode": self.get_playback_mode(),
            "photos": self.get_photos(),
            "photo_count": len(self.get_photos()),
            "radio_mode": (self.get_playback_mode() == "radio"),
            "radio_bg_source": str(self.config.get("radio_bg_source", "standby")),
            "radio_crossfade_duration": self.get_radio_crossfade_duration(),
            "live_audio_mic_device": str(self.config.get("live_audio_mic_device", "")),
            "live_audio_loopback_device": str(self.config.get("live_audio_loopback_device", "")),
            "live_audio_mic_volume": float(self.config.get("live_audio_mic_volume", 1.0)),
            "live_audio_loopback_volume": float(self.config.get("live_audio_loopback_volume", 0.7)),
            "live_audio_app_enabled": bool(self.config.get("live_audio_app_enabled", False)),
            "live_audio_app_window_title": str(self.config.get("live_audio_app_window_title", "")),
            "live_audio_app_volume": float(self.config.get("live_audio_app_volume", 1.0)),
            "live_audio_app_mode": str(self.config.get("live_audio_app_mode", "include")),
            "app_audio_available": bool(get_app_audio_capture_cmd()),
            "app_audio_level": self.get_app_audio_level(),
            "live_audio_bg_source": str(self.config.get("live_audio_bg_source", "standby")),
            "screen_capture_source_type": str(self.config.get("screen_capture_source_type", "display")),
            "screen_capture_display_index": int(self.config.get("screen_capture_display_index", 0)),
            "screen_capture_window_title": str(self.config.get("screen_capture_window_title", "")),
            "screen_capture_framerate": int(self.config.get("screen_capture_framerate", 30)),
            "screen_capture_width": int(self.config.get("screen_capture_width", 1920)),
            "screen_capture_height": int(self.config.get("screen_capture_height", 1080)),
            "screen_capture_draw_mouse": bool(self.config.get("screen_capture_draw_mouse", True)),
            "screen_capture_bitrate_kbps": int(self.config.get("screen_capture_bitrate_kbps", 4000)),
            "standby_mode": str(self.config.get("standby_mode", "image")),
            "standby_image_path": str(self.config.get("standby_image_path", "")),
            "has_prev": has_prev,
            "has_web_password": bool(str(self.config.get("web_password", "")).strip()),
            "setup_completed": self.is_setup_completed(),
            "permissions": {
                "allow_web_queue_add": bool(self.config.get("allow_web_queue_add", True)),
                "allow_web_queue_edit": bool(self.config.get("allow_web_queue_edit", True)),
                "allow_web_playback_control": bool(self.config.get("allow_web_playback_control", True)),
                "allow_web_share_info": bool(self.config.get("allow_web_share_info", False)),
                # リモコン自体が閉じているなら、個別の許可は意味を持たない。
                # UI が「許可されているのに操作できない」と見せないよう、ここでも落とす。
                "enable_web_remote": web_remote_enabled
            }
        }

    def get_playback_mode(self):
        """現在の再生モード ('video' | 'radio' | 'slideshow' | 'live' | 'screen') を取得"""
        mode = self.config.get("playback_mode")
        if mode in ("video", "radio", "slideshow", "live", "screen"):
            return mode
        if self.config.get("radio_mode", False):
            return "radio"
        return "video"

    def set_playback_mode(self, mode: str):
        """再生モードを設定 ('video' | 'radio' | 'slideshow' | 'live' | 'screen')"""
        if mode not in ("video", "radio", "slideshow", "live", "screen"):
            log_print(f"[Core] Invalid playback mode: {mode}")
            return self.get_playback_mode()

        self.config["playback_mode"] = mode
        self.config["radio_mode"] = (mode == "radio")
        self.save_config()
        self.request_stream_reload()
        log_print(f"[Core] Playback mode set to: {mode}")
        return mode

    def set_standby_config(self, mode: str = None, image_path: str = None):
        if mode in ("image", "qr"):
            self.config["standby_mode"] = mode
        if image_path is not None:
            self.config["standby_image_path"] = image_path
        self.save_config()
        self.generate_standby_image()
        log_print(f"[Core] Standby config updated: mode={self.config.get('standby_mode')}, image_path={self.config.get('standby_image_path')}")
        return self.config.get("standby_mode")

    def set_overlay_clock(self, enabled: bool, video: bool = None, position: str = None):
        self.config["overlay_clock_enabled"] = bool(enabled)
        if video is not None:
            self.config["overlay_clock_video"] = bool(video)
        if position is not None and position in ("top-right", "top-left", "bottom-right", "bottom-left"):
            self.config["overlay_clock_position"] = position
        self.save_config()
        log_print(f"[Core] Clock overlay config updated: enabled={self.config['overlay_clock_enabled']}, video={self.config.get('overlay_clock_video', False)}, pos={self.config.get('overlay_clock_position', 'top-right')}")
        return self.config["overlay_clock_enabled"]

    def set_radio_mode(self, enabled: bool):
        mode = "radio" if enabled else "video"
        return (self.set_playback_mode(mode) == "radio")

    def get_radio_crossfade_duration(self):
        """ラジオの曲頭・曲尾フェード秒数。0 なら掛けない（タスク17）。"""
        return normalize_radio_crossfade(self.config.get("radio_crossfade_duration", 0))

    def set_radio_bg_source(self, source: str):
        if source in ("card", "standby", "slideshow"):
            self.config["radio_bg_source"] = source
            self.save_config()
            log_print(f"[Core] Radio background source set to: {source}")
        return self.config.get("radio_bg_source", "card")

    def set_loop(self, enabled: bool):
        self.config["loop_queue"] = bool(enabled)
        self.save_config()
        log_print(f"[Core] Loop queue set to: {self.config['loop_queue']}")
        return self.config["loop_queue"]

    def set_shuffle(self, enabled: bool):
        self.config["shuffle"] = bool(enabled)
        self.save_config()
        log_print(f"[Core] Shuffle set to: {self.config['shuffle']}")
        return self.config["shuffle"]

    def shuffle_queue(self):
        with self.queue_lock:
            random.shuffle(self.play_queue)
        log_print("[Core] Queue shuffled.")
        return True

    def toggle_image_pause(self):
        curr_advance = bool(self.config.get("image_auto_advance", False)) and not self.image_paused
        new_advance = not curr_advance
        self.set_image_auto_advance(new_advance)
        return self.image_paused

    def set_image_pause(self, paused: bool):
        self.image_paused = bool(paused)
        self.config["image_auto_advance"] = not self.image_paused
        self.save_config()
        log_print(f"[Core] Photo pause set to: {self.image_paused} (auto_advance: {self.config['image_auto_advance']})")
        return self.image_paused

    def set_image_duration(self, seconds: int):
        try:
            sec = max(3, min(600, int(seconds)))
            self.config["image_display_duration"] = sec
            self.save_config()
            log_print(f"[Core] Photo display duration set to: {sec}s")
            return sec
        except Exception:
            return self.config.get("image_display_duration", 15)

    def set_image_auto_advance(self, enabled: bool):
        self.config["image_auto_advance"] = bool(enabled)
        self.image_paused = not bool(enabled)
        self.save_config()
        log_print(f"[Core] Photo auto advance set to: {self.config['image_auto_advance']}")
        return self.config["image_auto_advance"]

    def play_prev(self):
        """直前に再生したアイテムに戻る"""
        with self.queue_lock:
            if len(self.history_stack) >= 2:
                # 現在再生中の履歴をポップ
                self.history_stack.pop()
                prev_item = self.history_stack.pop()
                # 現在のアイテムをキュー先頭に復元
                if self.current_video:
                    self.play_queue.insert(0, self.current_video)
                # prev_item をキューの最前面に挿入
                self.play_queue.insert(0, prev_item)
                log_print(f"[Core] Navigating to prev item: {prev_item.get('title')}")
                self.skip_video()
                return True
        log_print("[Core] No previous item in history.")
        return False

    def _ts_offset_opts(self):
        """累積PTSオフセットの出力オプション。

        ★実測(2026-08-30): -output_ts_offset は「出力」オプションであり、
        -i より前に置くと黙って無視される（10秒指定しても出力PTSは素通しだった）。
        アイテム切替のたびにPTSが 0 付近へ戻るため、受信側は
        「DTS out of order」「Packet corrupt」を起こす。HLSは寛容で表面化しなかったが、
        RTMP経路では再エンコード入力が壊れ、音声は無事なのに映像だけが乱れる。
        """
        if self.accumulated_pts > 0:
            return ["-output_ts_offset", f"{self.accumulated_pts:.3f}"]
        return []

    # ------------------------------------------------------------------
    # 配信先（destination）: タスク14
    #
    # 出口を定義しているのはこのブロックだけである。永続シンクFFmpegが pipe:0 から
    # MPEG-TS を読み、各再生アイテムのFFmpegが current_stdin へ流し込む構造のため、
    # 送信側には一切触れずにシンクを差し替えるだけで配信先を切り替えられる。
    # ------------------------------------------------------------------
    def get_output_mode(self):
        """設定上の配信先モード。未知の値は既定の 'hls' へ落とす（fail-safe）。"""
        mode = str(self.config.get("output_mode", "hls") or "hls").strip().lower()
        return mode if mode in OUTPUT_MODES else "hls"

    def get_active_output_mode(self):
        """実際に今動かすべき配信先。HLSへ自動退避中は 'hls'。"""
        if getattr(self, "destination_fallback_active", False):
            return "hls"
        return self.get_output_mode()

    def is_setup_completed(self):
        """初回セットアップ案内を出す必要がないか。

        判定に **ストリームキーの有無は使えない**。start_background_tasks() が起動時に
        ensure_stream_sink() を呼び、TopazChat ではその時点で ensure_stream_key() が
        キーを自動生成して config へ書くため、新規インストールでも初回ポーリングの
        時点では既にキーが存在する。これを「設定済み」と読むと案内が永久に出ない。

        配信先を TopazChat 以外にしている利用者は、自分で選んだ結果なので案内しない。
        """
        if bool(self.config.get("setup_completed", False)):
            return True
        return self.get_output_mode() != "topaz"

    @staticmethod
    def generate_stream_key():
        """乗っ取り防止のため十分に長いランダムキーを生成する。"""
        return secrets.token_urlsafe(STREAM_KEY_BYTES)

    @staticmethod
    def mask_stream_key(key):
        """ログ・API・GUI・QR の全経路で使う共通マスク。"""
        key = str(key or "")
        if not key:
            return ""
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:2]}{'*' * (len(key) - 4)}{key[-2:]}"

    @staticmethod
    def is_masked_stream_key(value):
        """UIが表示用のマスク値をそのまま送り返してきた場合に本物のキーを潰さないための判定。"""
        return "*" in str(value or "")

    @staticmethod
    def mask_url_key(url):
        """URL末尾のストリームキーだけを伏せた文字列（ログ出力用）。"""
        url = str(url or "")
        if "/" not in url:
            return url
        head, _, tail = url.rpartition("/")
        return f"{head}/{StreamerCore.mask_stream_key(tail)}"

    def ensure_stream_key(self, target="topaz", persist=True):
        """TopazChat のストリームキーは任意文字列で、公式に決め方の記載がない。
        短いキーだと第三者に配信を乗っ取られるため、未設定・短すぎる場合は自動生成する。
        汎用RTMPのキーは相手サーバー側で決まるので生成しない。"""
        if target == "generic_rtmp":
            return str(self.config.get("generic_rtmp_key", "") or "")

        current = str(self.config.get("topaz_stream_key", "") or "")
        if len(current) >= STREAM_KEY_MIN_LENGTH:
            return current

        new_key = self.generate_stream_key()
        self.config["topaz_stream_key"] = new_key
        log_print(f"[Destination] Generated stream key for {target}: {self.mask_stream_key(new_key)}")
        if persist:
            try:
                self._write_config_file()
            except Exception as e:
                log_print(f"[Destination] Failed to persist generated stream key: {e}")
        return new_key

    def get_output_mode_label(self, mode=None, short=False):
        """配信先の表示名。GUI・Webリモコン・ログで同じ文言を使うためにここへ集約する。

        hls 経路は Cloudflare Quick Tunnel を経由しており「外部サービス不要」ではない。
        本当にローカル完結なのはトンネルを無効にしたときだけなので、表示を実態に追従させる。
        """
        mode = mode or self.get_output_mode()
        if mode == "topaz":
            return "TopazChat" if short else "TopazChat（RTMP → RTSP 中継）"
        if mode == "generic_rtmp":
            return "汎用RTMP" if short else "汎用RTMP（自前サーバー）"
        if getattr(self, "enable_tunnel", True):
            return "Cloudflare HLS" if short else "HLS（Cloudflare トンネル経由）"
        return "ローカルHLS" if short else "HLS（ローカル配信のみ）"

    ENDPOINT_SCHEMES = {
        "topaz_rtmp_base": ("rtmp://", "rtmps://"),
        "topaz_rtsp_base": ("rtsp://", "rtspt://"),
        "generic_rtmp_url": ("rtmp://", "rtmps://"),
    }

    @classmethod
    def validate_endpoint(cls, field, value):
        """配信先エンドポイントの検証。返り値は (正規化後の値, エラー理由)。

        TopazChat は個人運営でホストが変わり得るため利用者が書き換えられるようにするが、
        スキームを間違えた値をそのまま保存すると、接続できない理由が分からなくなる。
        """
        schemes = cls.ENDPOINT_SCHEMES.get(field, ())
        text = str(value or "").strip().rstrip("/")
        if not text:
            return "", ""
        if schemes and not text.lower().startswith(schemes):
            return "", f"{field} は {' / '.join(schemes)} で始まる必要があります: {text}"
        if " " in text:
            return "", f"{field} に空白が含まれています: {text}"
        return text, ""

    def get_rtmp_limits(self, mode=None):
        """destination ごとの (映像kbps上限, 音声kbps上限)。0 は上限なし。"""
        mode = mode or self.get_output_mode()
        if mode == "topaz":
            return TOPAZ_MAX_VIDEO_KBPS, TOPAZ_MAX_AUDIO_KBPS
        return 0, 0

    def clamp_rtmp_bitrates(self):
        """上限超過は「接続した瞬間に切断される」ため、設定値の側をクランプして保存する。"""
        changed = False
        max_v, max_a = self.get_rtmp_limits()
        for field, limit, floor in (
            ("rtmp_video_bitrate_kbps", max_v, 200),
            ("rtmp_audio_bitrate_kbps", max_a, 64),
        ):
            try:
                value = int(self.config.get(field, DEFAULT_CONFIG[field]))
            except (TypeError, ValueError):
                value = int(DEFAULT_CONFIG[field])
                changed = True
            if value < floor:
                value = floor
                changed = True
            if limit and value > limit:
                log_print(f"[Destination] {field}={value}kbps exceeds the destination limit ({limit}kbps). Clamped.")
                value = limit
                changed = True
            if self.config.get(field) != value:
                self.config[field] = value
                changed = True
        return changed

    def get_rtmp_publish_url(self, mode=None):
        """RTMP投稿先URL（キー込み）。未設定なら空文字。"""
        mode = mode or self.get_output_mode()
        if mode == "topaz":
            base = str(self.config.get("topaz_rtmp_base", "") or "").strip().rstrip("/")
            key = self.ensure_stream_key("topaz")
            if not base or not key:
                return ""
            return f"{base}/{key}"
        if mode == "generic_rtmp":
            base = str(self.config.get("generic_rtmp_url", "") or "").strip().rstrip("/")
            key = str(self.config.get("generic_rtmp_key", "") or "").strip()
            if not base:
                return ""
            return f"{base}/{key}" if key else base
        return ""

    def get_video_url(self, include_secrets=False):
        """ワールドの動画プレイヤーに貼るURL。Webリモコンを開くURLとは別物である。"""
        mode = self.get_active_output_mode()
        port = self.config.get("port", 8000)
        if mode == "topaz":
            base = str(self.config.get("topaz_rtsp_base", "") or "").strip().rstrip("/")
            key = str(self.config.get("topaz_stream_key", "") or "")
            if not base or not key:
                return ""
            return f"{base}/{key if include_secrets else self.mask_stream_key(key)}"
        if mode == "generic_rtmp":
            # 再生URLは投稿先サーバーの構成依存であり、こちらでは断定できない
            return ""
        if self.tunnel_raw_url:
            return f"{self.tunnel_raw_url}/stream.m3u8"
        if not self.enable_tunnel:
            return f"http://localhost:{port}/stream.m3u8"
        return ""

    def get_destination_info(self, include_secrets=False):
        """UI/GUI へ渡す配信先の状態一式。ストリームキーは既定でマスクする。"""
        mode = self.get_output_mode()
        active = self.get_active_output_mode()
        topaz_key = str(self.config.get("topaz_stream_key", "") or "")
        generic_key = str(self.config.get("generic_rtmp_key", "") or "")
        return {
            "output_mode": mode,
            "active_output_mode": active,
            "label": self.get_output_mode_label(mode),
            "label_short": self.get_output_mode_label(mode, short=True),
            "active_label": self.get_output_mode_label(active),
            "active_label_short": self.get_output_mode_label(active, short=True),
            "fallback_active": bool(getattr(self, "destination_fallback_active", False)),
            "last_error": str(getattr(self, "destination_last_error", "")),
            "fail_count": int(getattr(self, "_sink_fail_count", 0)),
            "video_url": self.get_video_url(include_secrets=include_secrets),
            "topaz_stream_key": topaz_key if include_secrets else self.mask_stream_key(topaz_key),
            "topaz_stream_key_set": bool(topaz_key),
            "topaz_rtmp_base": str(self.config.get("topaz_rtmp_base", "") or ""),
            "topaz_rtsp_base": str(self.config.get("topaz_rtsp_base", "") or ""),
            "default_topaz_rtmp_base": DEFAULT_CONFIG["topaz_rtmp_base"],
            "default_topaz_rtsp_base": DEFAULT_CONFIG["topaz_rtsp_base"],
            "generic_rtmp_url": str(self.config.get("generic_rtmp_url", "") or ""),
            "generic_rtmp_key": generic_key if include_secrets else self.mask_stream_key(generic_key),
            "generic_rtmp_key_set": bool(generic_key),
            "rtmp_video_bitrate_kbps": int(self.config.get("rtmp_video_bitrate_kbps", 2000)),
            "rtmp_audio_bitrate_kbps": int(self.config.get("rtmp_audio_bitrate_kbps", 192)),
            "rtmp_fallback_to_hls": bool(self.config.get("rtmp_fallback_to_hls", True)),
            "max_video_bitrate_kbps": self.get_rtmp_limits()[0],
            "max_audio_bitrate_kbps": self.get_rtmp_limits()[1],
        }

    def probe_rtmp_endpoint(self, url):
        """RTMP投稿先へTCPで到達できるかを起動前に確かめる。

        FFmpeg 側の即死検知だけでは不十分である（実測: pipe:0 入力では、入力データが
        流れ始めるまで出力側の接続を試みないため、宛先が落ちていても起動直後は生きて見える）。
        ここで落としておかないと「配信できていないのに配信中に見える」状態になる。
        返り値は (到達可否, 理由)。
        """
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            port = parsed.port or 1935
        except Exception as e:
            return False, f"配信先URLを解釈できません: {e}"
        if not host:
            return False, "配信先URLにホスト名がありません"

        # socket.create_connection() にホスト名を渡すと、解決された各アドレス
        # （IPv4 / IPv6）へ順に「それぞれ満額のタイムアウト」で接続を試みる。
        # 結果として所要時間が families 倍に伸び、その間ずっと再生スレッドを止めてしまう。
        # ここでは自分で名前解決し、全体の締切を1本で管理する。
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except socket.gaierror:
            return False, f"配信先ホストを解決できません ({host})"
        if not infos:
            return False, f"配信先ホストを解決できません ({host})"

        deadline = time.time() + RTMP_CONNECT_TIMEOUT_SECONDS
        last_error = None
        for family, socktype, proto, _canonname, sockaddr in infos:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sock = socket.socket(family, socktype, proto)
            try:
                sock.settimeout(min(remaining, RTMP_CONNECT_TIMEOUT_SECONDS))
                sock.connect(sockaddr)
                return True, ""
            except (socket.timeout, TimeoutError):
                last_error = f"配信先へ接続できません（タイムアウト: {host}:{port}）"
            except OSError as e:
                last_error = f"配信先へ接続できません ({host}:{port}): {e}"
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        return False, last_error or f"配信先へ接続できません（タイムアウト: {host}:{port}）"

    def build_sink_command(self, mode):
        """destination 別のシンクFFmpegコマンドを組み立てる。返り値は (cmd, 表示用の宛先)。

        RTMP系では -c copy の素通しは成立しない:
          1) TopazChat には映像2Mbps / 音声320kbps の上限があり、超過すると強制切断される
          2) RTMP は再生アイテム切替時のタイムスタンプ跳躍・解像度/fps変化で切断されやすい
        そのためシンク側で解像度・fps・GOPを固定して再エンコードし、
        パラメータ変化そのものを消す。
        """
        ffmpeg = get_ffmpeg_cmd()
        head = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "warning", "-nostats",
            "-fflags", "+nobuffer+flush_packets+genpts+igndts",
            "-i", "pipe:0",
        ]

        if mode in RTMP_OUTPUT_MODES:
            url = self.get_rtmp_publish_url(mode)
            if not url:
                return None, ""
            self.clamp_rtmp_bitrates()
            v_kbps = int(self.config.get("rtmp_video_bitrate_kbps", 2000))
            a_kbps = int(self.config.get("rtmp_audio_bitrate_kbps", 192))
            width = int(self.config.get("rtmp_video_width", 1280))
            height = int(self.config.get("rtmp_video_height", 720))
            fps = int(self.config.get("rtmp_fps", 30))
            gop_sec = max(1, int(self.config.get("rtmp_gop_seconds", 2)))
            gop = str(fps * gop_sec)
            vf = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
            )
            cmd = head + [
                "-vf", vf,
                # ★実測(2026-08-30): -tune zerolatency はBフレームと先読みを止めるため、
                # 同じ1500kbpsで SSIM 0.9751→0.9806 / PSNR 36.61→37.58dB と明確に画質を落とす
                # （ビットレートを2000kまで上げるのと同等の劣化を、帯域を増やさず被っていた）。
                # 稼ぐはずのレイテンシは数フレーム分で、TopazChatの中継とAVProのバッファに
                # 比べて無視できるため外す。エンコード速度も 8.6x→9.2x で悪化しない。
                *build_video_encoder_opts(
                    self.get_video_encoder(),
                    v_kbps=v_kbps, max_kbps=v_kbps, buf_kbps=v_kbps * 2,
                    h264_profile="main", sw_preset="veryfast", sw_tune=None,
                    level=None, bf_zero=False, sc_threshold_zero=True,
                    gop_frames=gop),
                "-c:a", "aac", "-b:a", f"{a_kbps}k", "-ar", "44100", "-ac", "2",
                "-max_muxing_queue_size", "1024",
                "-f", "flv", url,
            ]
            return cmd, self.mask_url_key(url)

        seg_time = str(self.config.get("hls_segment_time", 3))
        list_size = str(self.config.get("hls_list_size", 15))
        cmd = head + [
            "-c:v", "copy",
            "-c:a", "copy",
            "-flush_packets", "1",
            "-f", "hls",
            "-hls_time", seg_time,
            "-hls_list_size", list_size,
            # split_by_time は「キーフレームでなくても時間で切る」ため、
            # GOP長とセグメント長が一致しない限り単独デコード不能なセグメントを量産する。
            # 送信側で境界にIDRを強制した上で、ここではキーフレームでのみ分割させる。
            "-hls_flags", "delete_segments+append_list",
            "-hls_segment_filename", os.path.join(HLS_DIR, "seg_%05d.ts"),
            os.path.join(HLS_DIR, "stream.m3u8"),
        ]
        via = "Cloudflare tunnel" if getattr(self, "enable_tunnel", True) else "local only"
        return cmd, f"HLS via {via} (segment {seg_time}s / list {list_size})"

    def _drain_sink_stderr(self, proc):
        """stderr を読み捨てないとパイプが詰まってFFmpegごと止まる。
        直近の行だけ保持して、接続失敗の理由を人間が読めるようにする。"""
        try:
            for raw in iter(proc.stderr.readline, b""):
                try:
                    line = raw.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if line:
                    self._sink_stderr_tail.append(line)
        except Exception:
            pass

    def _start_sink(self, mode):
        """シンクFFmpegを起動する。RTMP系は起動直後の即死＝接続失敗として検知する。"""
        cmd, target = self.build_sink_command(mode)
        if not cmd:
            msg = "配信先URL / ストリームキーが未設定です"
            log_print(f"[Sink] Destination '{mode}' is not configured: {msg}")
            self.destination_last_error = msg
            return False

        if mode in RTMP_OUTPUT_MODES:
            reachable, reason = self.probe_rtmp_endpoint(self.get_rtmp_publish_url(mode))
            if not reachable:
                log_print(f"[Sink] Destination '{mode}' is unreachable: {reason}")
                self.destination_last_error = reason
                return False

        self._sink_stderr_tail.clear()
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=CREATE_NO_WINDOW
            )
        except FileNotFoundError:
            log_print("[Sink] Error: ffmpeg was not found in system path.")
            self.destination_last_error = "ffmpeg が見つかりません"
            return False
        except Exception as e:
            log_print(f"[Sink] Error starting sink FFmpeg: {e}")
            self.destination_last_error = str(e)
            return False

        threading.Thread(target=self._drain_sink_stderr, args=(proc,), daemon=True).start()

        if mode in RTMP_OUTPUT_MODES:
            deadline = time.time() + SINK_STARTUP_PROBE_SECONDS
            while time.time() < deadline:
                if proc.poll() is not None:
                    detail = " / ".join(list(self._sink_stderr_tail)[-3:])
                    self.destination_last_error = detail or f"RTMP接続に失敗しました (rc={proc.returncode})"
                    log_print(f"[Sink] RTMP sink exited immediately (rc={proc.returncode}). {detail}")
                    return False
                time.sleep(0.1)

        with self.process_lock:
            self.hls_proc = proc
            self.current_stdin = proc.stdin
        self.active_output_mode = mode
        self._sink_started_at = time.time()
        if mode == self.get_output_mode():
            self.destination_last_error = ""
        log_print(f"[Sink] Destination '{mode}' started -> {target}")
        return True

    def _schedule_destination_retry(self):
        """相手サーバーを叩き続けないよう、復帰試行は指数バックオフで間隔を空ける。

        間隔は「退避した回数」で決める。以前はサイクル内の失敗回数で決めていたが、
        その値は復帰試行のたびに 0 へ戻す必要があるため、両者を兼ねられない。
        """
        self._sink_fallback_rounds += 1
        cap = max(10, int(self.config.get("rtmp_retry_backoff_max_seconds", 300)))
        backoff = min(cap, 10 * (2 ** max(0, self._sink_fallback_rounds - 1)))
        self._sink_retry_at = time.time() + backoff
        return backoff

    def ensure_stream_sink(self):
        """配信先シンクFFmpegが動いていれば維持し、未起動/停止時のみ起動する
        （ストリーム連続性を保持）。destination の切り替え点はここ1箇所だけ。"""
        with self.process_lock:
            force = bool(getattr(self, "_sink_force_restart", False))
            if not force and self.hls_proc and self.hls_proc.poll() is None and self.current_stdin:
                return True
            if self.hls_proc:
                # 先に stdin を閉じてから殺す。閉じずに参照だけ捨てると、
                # 後片付け(GC)のタイミングで BufferedWriter の finalize が失敗し、
                # 「Exception ignored while finalizing file」がログに湧く。
                if self.current_stdin:
                    try:
                        self.current_stdin.close()
                    except Exception:
                        pass
                kill_proc(self.hls_proc)
                self.hls_proc = None
                self.current_stdin = None
                time.sleep(0.2)
            self._sink_force_restart = False

        mode = self.get_active_output_mode()
        if mode not in RTMP_OUTPUT_MODES:
            return self._start_sink(mode)

        # RTMP系: 失敗しても配信そのものは止めない。規定回数試して駄目ならHLSへ退避する。
        # 失敗計数は呼び出しをまたいで持ち越す。そうしないと「起動しては数秒で切断」を
        # 繰り返す相手に対して永遠に再接続を続け、退避条件に到達できない。
        attempts = max(1, int(self.config.get("rtmp_fallback_after_failures", 3) or 3))
        while self._sink_fail_count < attempts:
            if self._start_sink(mode):
                return True
            self._sink_fail_count += 1
            log_print(f"[Destination] '{mode}' connection failed ({self._sink_fail_count}/{attempts}): {self.destination_last_error}")
            if self._sink_fail_count < attempts:
                time.sleep(min(2.0, 0.5 * self._sink_fail_count))

        if not self.config.get("rtmp_fallback_to_hls", True):
            return False

        backoff = self._schedule_destination_retry()
        self.destination_fallback_active = True
        log_print(f"[Destination] Falling back to HLS ({self.get_output_mode_label('hls', short=True)}) "
                  f"to keep the stream alive. Retrying '{mode}' in {backoff}s.")
        return self._start_sink("hls")

    # 旧名。外部（テスト・プラグイン）からの呼び出し互換のために残す。
    def ensure_hls_receiver(self):
        return self.ensure_stream_sink()

    def destination_watchdog_loop(self):
        """RTMP配信には、ローカルHLSには存在しなかった障害モード
        （接続失敗・途中切断・再接続ループ）がある。ここで明示的に面倒を見る。"""
        while self.is_running:
            time.sleep(2.0)
            if not self.is_running:
                break
            self._destination_watchdog_tick()

    def _destination_watchdog_tick(self):
        """ウォッチドッグ1回分。ループと分けてあるのは単体テストから叩けるようにするため。"""
        try:
            proc = self.hls_proc
            if proc is not None and proc.poll() is not None:
                lived = time.time() - getattr(self, "_sink_started_at", 0.0)
                log_print(f"[Sink] Destination sink died unexpectedly (rc={proc.returncode}, alive {lived:.1f}s). Restarting...")
                if self.active_output_mode in RTMP_OUTPUT_MODES:
                    if lived >= SINK_STABLE_SECONDS:
                        # 一度は安定して流れていた上での切断。単発の事故として計数をやり直す
                        self._sink_fail_count = 0
                        self._sink_fallback_rounds = 0
                    else:
                        self._sink_fail_count += 1
                self._sink_force_restart = True
                if self.ensure_stream_sink():
                    self.request_stream_reload()
                return

            if (getattr(self, "destination_fallback_active", False)
                    and self.get_output_mode() in RTMP_OUTPUT_MODES
                    and time.time() >= getattr(self, "_sink_retry_at", 0.0)):
                log_print("[Destination] Retrying primary destination after backoff...")
                self.destination_fallback_active = False
                # 新しい再接続サイクルとして数え直す。ここを 0 に戻さないと
                # ensure_stream_sink() の試行ループが一度も回らず、
                # 「接続を試さずに即HLSへ退避し直す」だけの空回りになる
                # （＝相手が復旧しても永久に戻らない）。
                self._sink_fail_count = 0
                self._sink_force_restart = True
                if self.ensure_stream_sink():
                    self.request_stream_reload()
        except Exception as e:
            log_print(f"[Sink] Watchdog error: {e}")

    def relay_stream_data(self, proc_to_read, stdin_to_write, stop_event, is_paced=True):
        """
        送信側FFmpegから配信先シンクへのストリーム中継。
        is_paced=True の場合、実時間 + 先読みバッファを維持するようにデータ流量を制御する。

        先読み秒数は配信先で変える。HLSは手元でセグメントを溜めてから配るので
        15秒先行させておくと再生が途切れにくいが、RTMPは「今の映像を今送る」
        ライブ投稿であり、同じことをすると相手サーバーへ一気に押し込むことになる。
        ★実測(2026-08-30): 15秒先読みのままRTMPへ送ると、経過4秒の時点で
        約14秒ぶんを送出していた（実時間の3.5倍）。低遅延のためにTopazChatを
        使いながら15秒先行で詰め込む形になり、遅延も映像の乱れも招く。
        OBS等の実配信と同じく、RTMP系では実時間に近いペースで送る。
        """
        rtmp_live = self.get_active_output_mode() in RTMP_OUTPUT_MODES
        BUFFER_AHEAD_SECONDS = RTMP_BUFFER_AHEAD_SECONDS if rtmp_live else HLS_BUFFER_AHEAD_SECONDS
        base_pts = None
        current_stream_pos = 0.0
        max_relative_pts = 0.0
        start_wall_time = time.time()

        try:
            while not stop_event.is_set() and self.is_running:
                if hasattr(proc_to_read.stdout, "read1"):
                    data = proc_to_read.stdout.read1(65536)
                else:
                    data = proc_to_read.stdout.read(65536)

                if not data:
                    break

                pts = extract_pts_from_ts_chunk(data)
                if pts is not None:
                    if base_pts is None:
                        base_pts = pts
                    stream_pos = pts - base_pts
                    if stream_pos >= 0:
                        current_stream_pos = stream_pos
                        if current_stream_pos > max_relative_pts:
                            max_relative_pts = current_stream_pos

                # PTSの抽出と再生進捗の更新（ペーシング有効時）
                if is_paced:
                    # 先行秒数が目標バッファ（15秒）に収まるまで「実時間が追いつくのを待ち切る」。
                    # 以前は1チャンクにつき最大0.2秒しか眠らなかったため、
                    # 送信側FFmpegの出力レートが高いと待機が追いつかず先行秒数が青天井に増加し、
                    # 曲の残り全部を数十秒で送出しきってプレイリスト更新が止まっていた
                    # （＝視聴側ではセグメントが尽きて配信停止に見える）。
                    while not stop_event.is_set() and self.is_running:
                        wall_elapsed = time.time() - start_wall_time
                        ahead = current_stream_pos - wall_elapsed
                        if ahead <= BUFFER_AHEAD_SECONDS:
                            break
                        time.sleep(min(0.2, max(0.02, ahead - BUFFER_AHEAD_SECONDS)))

                try:
                    stdin_to_write.write(data)
                    stdin_to_write.flush()
                except Exception:
                    break
        except Exception:
            pass
        finally:
            dur = max_relative_pts if max_relative_pts > 0 else (time.time() - start_wall_time)
            self.last_stream_duration = max(1.0, dur)
            if not stop_event.is_set():
                self.video_done_event.set()

    def watch_send_proc(self, proc, stop_event):
        try:
            proc.wait()
        except Exception:
            pass
        if not stop_event.is_set():
            log_print("[Monitor] Video finished naturally.")
            self.video_done_event.set()

    def get_base_ydl_opts(self):
        """yt-dlp の基本共通オプションを生成（JSチャレンジ問題回避・安定したクライアントフォールバック）"""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "tv", "web"]
                }
            }
        }
        cookie_path = os.path.abspath("cookies.txt")
        if os.path.exists(cookie_path):
            opts["cookiefile"] = cookie_path
        return opts

    def expand_playlist(self, url):
        """URLから動画情報リスト [{"url": ..., "title": ..., "duration": ...}] を展開"""
        is_safe, reason = is_safe_url(url)
        if not is_safe:
            log_print(f"[Core] Rejected unsafe URL: {reason}")
            return []

        ydl_opts = self.get_base_ydl_opts()
        ydl_opts.update({
            "extract_flat": True,
            "skip_download": True,
            "playlistend": MAX_PLAYLIST_ITEMS
        })
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if "entries" in info:
                    entries = list(info["entries"])[:MAX_PLAYLIST_ITEMS]
                    result = []
                    for e in entries:
                        if not e:
                            continue
                        e_url = e.get("url") or (f"https://www.youtube.com/watch?v={e['id']}" if e.get("id") else "")
                        if not e_url.startswith("http"):
                            e_url = f"https://www.youtube.com/watch?v={e.get('id', '')}"
                        result.append({
                            "url": e_url,
                            "title": e.get("title", "Unknown"),
                            "duration": e.get("duration", 0)
                        })
                    return result
                else:
                    return [{
                        "url": url,
                        "title": info.get("title", "Unknown"),
                        "duration": info.get("duration", 0)
                    }]
        except Exception as e:
            log_print(f"[Core] Failed to analyze URL: {e}")
            return []

    def get_max_video_height(self):
        """配信する映像の高さ上限(px)。0 以下なら無制限。"""
        try:
            return int(self.config.get("max_video_height", 1080))
        except (TypeError, ValueError):
            return 1080

    def build_format_selector(self):
        """yt-dlp の format 指定を組み立てる。

        分離(DASH)形式を優先し、取れないときだけ結合形式へ落とす。
        YouTube は結合形式を format 18 (640x360) しか残していないため、
        ここへ落ちた時点で 360p 固定になる。落ちたことは呼び出し側でログに出す。
        """
        h = self.get_max_video_height()
        cap = f"[height<={h}]" if h > 0 else ""
        return (
            f"bestvideo[vcodec^=avc1]{cap}+bestaudio[acodec^=mp4a]/"
            f"bestvideo{cap}+bestaudio/"
            f"best[vcodec^=avc1]{cap}/"
            f"best{cap}/"
            "best"
        )

    def get_stream_urls(self, youtube_url):
        ydl_opts = self.get_base_ydl_opts()
        ydl_opts.update({"format": self.build_format_selector()})
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            video_url = audio_url = None
            headers = info.get("http_headers", {})
            if "requested_formats" in info:
                for fmt in info["requested_formats"]:
                    if fmt.get("vcodec") != "none" and fmt.get("acodec") == "none":
                        video_url = fmt.get("url")
                        if fmt.get("http_headers"):
                            headers.update(fmt["http_headers"])
                    elif fmt.get("acodec") != "none" and fmt.get("vcodec") == "none":
                        audio_url = fmt.get("url")
                        if fmt.get("http_headers"):
                            headers.update(fmt["http_headers"])
            if not video_url or not audio_url:
                video_url = info.get("url")
                audio_url = None
                if info.get("http_headers"):
                    headers.update(info["http_headers"])

            # 実際に選ばれた解像度をログに出す。ここを黙らせていたため、
            # 1080p を要求しているつもりで 360p を配信し続けていても気づけなかった。
            self.last_selected_height = self._log_selected_format(info, audio_url)

            return video_url, audio_url, info.get("title", "Unknown"), info.get("duration", 0), headers

    def _log_selected_format(self, info, audio_url):
        """選択された形式の解像度をログ出力し、高さを返す。"""
        rf = info.get("requested_formats") or []
        if rf:
            height = max((f.get("height") or 0) for f in rf)
        else:
            height = info.get("height") or 0
        kind = "分離(DASH)" if audio_url else "結合"
        want = self.get_max_video_height()
        log_print(
            f"[Core] Selected format: {info.get('format_id')} "
            f"({info.get('width') or '?'}x{height or '?'}, {kind}) / 上限 {want}p"
        )
        if height and want > 0 and height < min(want, 720):
            log_print(
                f"[Core] 警告: 配信解像度が {height}p に留まりました。"
                "YouTubeが高解像度(DASH)形式をトークン必須にしているためです。"
                "exeと同じフォルダに cookies.txt (ログイン済みブラウザからエクスポート) "
                "を置くと解放されることがあります。"
            )
        return height

    def get_audio_only_stream_urls(self, youtube_url):
        ydl_opts = self.get_base_ydl_opts()
        ydl_opts.update({
            "format": "bestaudio[acodec^=mp4a]/bestaudio/best",
        })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            audio_url = info.get("url")
            headers = info.get("http_headers", {})
            if "requested_formats" in info:
                for fmt in info["requested_formats"]:
                    if fmt.get("acodec") != "none":
                        audio_url = fmt.get("url")
                        if fmt.get("http_headers"):
                            headers.update(fmt["http_headers"])
            title = info.get("title", "Unknown")
            duration = info.get("duration", 0)
            meta = {
                "id": info.get("id", ""),
                "title": title,
                "duration": duration,
                "thumbnail": info.get("thumbnail", ""),
                "artist": info.get("artist") or info.get("creator") or info.get("uploader") or info.get("channel") or "",
                "channel": info.get("channel") or info.get("uploader") or ""
            }
            return audio_url, title, duration, headers, meta

    def prefetch_item(self, item):
        """次の動画/音楽のストリームURLおよびサムネイル画像をバックグラウンドで先読み"""
        if not item or item.get("type") == "image":
            return
        url = item.get("url")
        if not url or not url.startswith("http"):
            return

        with self.prefetch_lock:
            cached = self.prefetch_cache.get(url)
            if cached and (time.time() - cached.get("timestamp", 0) < 600):
                return

        is_radio = bool(self.config.get("radio_mode", False))
        log_print(f"[Prefetch] Starting prefetch for next item: {item.get('title')} (radio={is_radio})")

        try:
            if is_radio:
                res = self.get_audio_only_stream_urls(url)
                if res and res[0]:
                    audio_url, title, duration, headers, meta = res if len(res) >= 5 else (*res[:4], {})
                    bg_source = self.config.get("radio_bg_source", "card")
                    if bg_source == "card":
                        self.generate_radio_card_image(item, metadata=meta)
                    with self.prefetch_lock:
                        self.prefetch_cache[url] = {
                            "is_radio": True,
                            "audio_url": audio_url,
                            "title": title,
                            "duration": duration,
                            "headers": headers,
                            "meta": meta,
                            "timestamp": time.time()
                        }
                    log_print(f"[Prefetch] Completed prefetch for: {title}")
            else:
                res = self.get_stream_urls(url)
                if res and (res[0] or res[1]):
                    video_url, audio_url, title, duration, headers = res
                    with self.prefetch_lock:
                        self.prefetch_cache[url] = {
                            "is_radio": False,
                            "video_url": video_url,
                            "audio_url": audio_url,
                            "title": title,
                            "duration": duration,
                            "headers": headers,
                            "timestamp": time.time()
                        }
                    log_print(f"[Prefetch] Completed prefetch for: {title}")
        except Exception as e:
            log_print(f"[Prefetch] Failed to prefetch item: {e}")

    def generate_radio_card_image(self, video_info, metadata=None):
        """YouTubeサムネイルとタイトル・アーティスト情報を合成した 1920x1080 カード画像を生成"""
        os.makedirs(RADIO_CACHE_DIR, exist_ok=True)
        url = (video_info or {}).get("url", "")
        title = (metadata or {}).get("title") or (video_info or {}).get("title", "Unknown")
        artist = (metadata or {}).get("artist") or (metadata or {}).get("uploader") or (metadata or {}).get("channel") or ""
        video_id = (metadata or {}).get("id")

        if not video_id and "v=" in url:
            try:
                video_id = url.split("v=")[1].split("&")[0]
            except Exception:
                pass
        if not video_id and "youtu.be/" in url:
            try:
                video_id = url.split("youtu.be/")[1].split("?")[0]
            except Exception:
                pass
        if not video_id:
            import hashlib
            video_id = hashlib.md5(url.encode('utf-8', errors='ignore')).hexdigest()[:12]

        cache_path = os.path.join(RADIO_CACHE_DIR, f"radio_card_{video_id}.png")
        if os.path.exists(cache_path):
            return cache_path

        # サムネイル画像の取得
        thumb_img = None
        thumb_url = (metadata or {}).get("thumbnail")
        thumb_candidates = []
        if thumb_url:
            thumb_candidates.append(thumb_url)
        if video_id and len(video_id) == 11:
            thumb_candidates.append(f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg")
            thumb_candidates.append(f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg")

        for turl in thumb_candidates:
            try:
                req = urllib.request.Request(turl, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = resp.read()
                    img = Image.open(io.BytesIO(data))
                    # YouTubeのmaxresdefaultが404でなく120x90の灰画像の場合のチェック
                    if img.size[0] > 150:
                        thumb_img = img.convert("RGB")
                        break
            except Exception:
                continue

        width, height = 1920, 1080
        card_img = Image.new("RGB", (width, height), color="#0F172A")

        # 1. 背景レイヤー (サムネイル拡大ぼかし + 落ち着いたダークオーバーレイ)
        if thumb_img:
            tw, th = thumb_img.size
            scale = max(width / tw, height / th)
            bw = int(tw * scale)
            bh = int(th * scale)
            bg_resized = thumb_img.resize((bw, bh), Image.Resampling.BILINEAR)
            bx = (bw - width) // 2
            by = (bh - height) // 2
            bg_cropped = bg_resized.crop((bx, by, bx + width, by + height))
            
            # ガウスぼかし
            bg_blurred = bg_cropped.filter(ImageFilter.GaussianBlur(radius=40))
            
            # ダークスレートの半透明オーバーレイ
            overlay = Image.new("RGBA", (width, height), (15, 23, 42, 215))
            bg_blurred = bg_blurred.convert("RGBA")
            bg_final = Image.alpha_composite(bg_blurred, overlay).convert("RGB")
            card_img.paste(bg_final, (0, 0))
        else:
            draw_bg = ImageDraw.Draw(card_img)
            draw_bg.rectangle([(0, 0), (width, height)], fill="#0F172A")

        draw = ImageDraw.Draw(card_img)

        # 2. 左側: アルバムアート (サムネイル) 描画
        art_w, art_h = 760, 428 # 16:9
        art_x = 120
        art_y = (height - art_h) // 2

        if thumb_img:
            tw, th = thumb_img.size
            scale = max(art_w / tw, art_h / th)
            aw = int(tw * scale)
            ah = int(th * scale)
            art_resized = thumb_img.resize((aw, ah), Image.Resampling.LANCZOS)
            ax = (aw - art_w) // 2
            ay = (ah - art_h) // 2
            art_cropped = art_resized.crop((ax, ay, ax + art_w, ay + art_h)).convert("RGBA")

            # 角丸マスク
            mask = Image.new("L", (art_w, art_h), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle([(0, 0), (art_w, art_h)], radius=18, fill=255)

            card_art = Image.new("RGBA", (art_w, art_h), (0, 0, 0, 0))
            card_art.paste(art_cropped, (0, 0), mask)
            
            art_border_draw = ImageDraw.Draw(card_art)
            art_border_draw.rounded_rectangle([(0, 0), (art_w - 1, art_h - 1)], radius=18, outline=(255, 255, 255, 60), width=2)

            card_img.paste(card_art, (art_x, art_y), card_art)
        else:
            draw.rounded_rectangle(
                [(art_x, art_y), (art_x + art_w, art_y + art_h)],
                radius=18,
                fill="#1E293B",
                outline="#334155",
                width=2
            )
            try:
                font_icon = ImageFont.truetype("arial.ttf", 60)
            except Exception:
                font_icon = ImageFont.load_default()
            draw.text((art_x + art_w // 2, art_y + art_h // 2), "🎵", fill="#94A3B8", anchor="mm", font=font_icon)

        # 3. 中央〜右側: 楽曲情報 (タイトル・アーティスト) 描画
        info_x = art_x + art_w + 90
        max_text_w = width - info_x - 100

        font_title = get_pil_font(50, bold=True)
        font_artist = get_pil_font(32, bold=False)
        font_resync = get_pil_font(22, bold=False)

        clean_title = title.replace("📻 ", "").strip()
        lines = []
        curr_line = ""
        for char in clean_title:
            test_line = curr_line + char
            try:
                bbox = font_title.getbbox(test_line)
                w = bbox[2] - bbox[0]
            except Exception:
                w = len(test_line) * 28
            if w > max_text_w:
                if curr_line:
                    lines.append(curr_line)
                    curr_line = char
                else:
                    lines.append(test_line)
                    curr_line = ""
                if len(lines) >= 3:
                    break
            else:
                curr_line = test_line
        if curr_line and len(lines) < 3:
            lines.append(curr_line)
        if not lines:
            lines = [clean_title]

        line_h = 64
        title_total_h = len(lines) * line_h
        artist_h = 44 if artist else 0
        content_total_h = title_total_h + (35 if artist else 0) + artist_h

        start_y = (height - content_total_h) // 2

        for i, l in enumerate(lines):
            if i == 2 and len(clean_title) > len("".join(lines)):
                l = l[:-2] + "..." if len(l) > 2 else l + "..."
            draw.text((info_x, start_y + i * line_h), l, fill="#FFFFFF", anchor="la", font=font_title)

        if artist:
            artist_y = start_y + title_total_h + 30
            draw.text((info_x, artist_y), artist, fill="#38BDF8", anchor="la", font=font_artist)

        # 4. フッター: リシンク案内バー
        footer_h = 60
        draw.rectangle([(0, height - footer_h), (width, height)], fill="#0B1120")
        draw.text(
            (width // 2, height - footer_h // 2),
            "🔄 映像が止まった・遅れた時は [Resync] を押してください / If lagging or frozen, please press Resync.",
            fill="#94A3B8",
            anchor="mm",
            font=font_resync
        )

        try:
            card_img.save(cache_path, "PNG")
            return cache_path
        except Exception as e:
            log_print(f"[Radio] Failed to save radio card: {e}")
            return None

    def get_slideshow_images(self):
        """スライドショーで利用可能な画像パス一覧を取得（写真プール photo_pool から取得）"""
        with self.photo_lock:
            images = [
                os.path.abspath(p["path"])
                for p in self.photo_pool
                if p.get("path") and os.path.exists(p["path"])
            ]

        # シャッフル設定が有効ならシャッフル
        if self.config.get("shuffle", False) and len(images) > 1:
            images_copy = list(images)
            random.shuffle(images_copy)
            return images_copy

        return images

    def get_radio_background_path(self, video_info=None, metadata=None):
        """BGM/ラジオモード用の背景画像パスを取得（カード画面、待機画面、または写真）"""
        source = self.config.get("radio_bg_source", "card")
        if source == "card" and video_info:
            card_path = self.generate_radio_card_image(video_info, metadata)
            if card_path and os.path.exists(card_path):
                return card_path

        if source == "slideshow":
            images = self.get_slideshow_images()
            if images:
                return self.get_image_for_playback(images[0])

        # デフォルト・フォールバックは待機画面 (QR & URLカード付き)
        self.generate_standby_image()
        if os.path.exists(STANDBY_IMAGE_PATH):
            return STANDBY_IMAGE_PATH
        return None

    def build_slideshow_manifest(self, track_seconds=0, label="Radio",
                                 manifest_name="slideshow_manifest.txt"):
        """スライドショー用の ffconcat マニフェストを作る。写真が無ければ None。

        ★concat + -stream_loop -1 は常にマニフェストの先頭から再生される。
          「写真枚数 x 表示秒数」が曲の長さを超えると後半の写真が一度も表示されないまま
          次の曲でまた1枚目に戻り、特定の写真が永久にスキップされていた。
          開始位置をずらし、消化した枚数だけカーソルを進めることで全写真を巡回させる。

        track_seconds に 0 を渡すと「1枚消化」として扱う。ライブ音声のように
        終わりのない配信では曲の長さという概念が無いため。
        """
        images = self.get_slideshow_images()
        if not images:
            return None

        duration_val = float(self.config.get("image_display_duration", 15))

        start = self.slideshow_cursor % len(images)
        images = images[start:] + images[:start]
        try:
            secs = float(track_seconds or 0)
        except (TypeError, ValueError):
            secs = 0.0
        if secs > 0 and duration_val > 0:
            consumed = max(1, int(math.ceil(secs / duration_val)))
        else:
            consumed = 1
        self.slideshow_cursor = (start + consumed) % len(images)

        manifest_lines = ["ffconcat version 1.0\n"]
        for idx, img in enumerate(images):
            pb_path = self.get_image_for_playback(img, unique_id=idx)
            pb_path_clean = os.path.abspath(pb_path).replace("\\", "/")
            manifest_lines.append(f"file '{pb_path_clean}'\n")
            manifest_lines.append(f"duration {duration_val}\n")
        # concat demuxer の最終要素の持続時間を有効にするため末尾に複製
        last_pb = self.get_image_for_playback(images[-1], unique_id=len(images))
        last_pb_clean = os.path.abspath(last_pb).replace("\\", "/")
        manifest_lines.append(f"file '{last_pb_clean}'\n")

        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
        manifest_path = os.path.join(IMAGE_CACHE_DIR, manifest_name)
        with open(manifest_path, "w", encoding="utf-8") as f:
            f.writelines(manifest_lines)
        log_print(f"[{label}] Prepared slideshow manifest with {len(images)} photos "
                  f"(duration: {duration_val}s/photo, start #{start + 1}, "
                  f"next #{self.slideshow_cursor + 1}).")
        return manifest_path

    def play_radio(self, video_info, seek_seconds=0):
        """BGM/ラジオモード: YouTube音声ストリーム / ローカル動画音声 + 静止画/写真を合成し、極小帯域でHLS配信"""
        url = video_info.get("url", "")
        is_local = bool(video_info.get("is_local") or video_info.get("type") == "local_video" or (video_info.get("path") and os.path.exists(video_info["path"])))
        try:
            if is_local:
                audio_url = os.path.abspath(video_info.get("path") or url)
                title = video_info.get("title") or os.path.splitext(os.path.basename(audio_url))[0]
                duration = video_info.get("duration", 0)
                if not duration:
                    duration = get_video_file_duration(audio_url)
                headers = None
                metadata = {
                    "title": title,
                    "artist": "Local Video",
                    "duration": duration,
                    "id": video_info.get("id", "")
                }
                log_print(f"[Radio] Using local video audio: {title}")
            else:
                cached = None
                with self.prefetch_lock:
                    if url in self.prefetch_cache and self.prefetch_cache[url].get("is_radio"):
                        c = self.prefetch_cache.pop(url)
                        if time.time() - c.get("timestamp", 0) < 600:
                            cached = c

                if cached:
                    audio_url = cached["audio_url"]
                    title = cached["title"]
                    duration = cached["duration"]
                    headers = cached["headers"]
                    metadata = cached.get("meta") or {"title": title, "duration": duration}
                    log_print(f"[Radio] Using pre-fetched audio URL for: {title}")
                else:
                    res = self.get_audio_only_stream_urls(url)
                    if len(res) >= 5:
                        audio_url, title, duration, headers, metadata = res[:5]
                    else:
                        audio_url, title, duration, headers = res[:4]
                        metadata = {"title": title, "duration": duration}

            if not audio_url:
                raise ValueError("No audio stream URL returned")
            self.current_video = {
                "title": f"📻 {title}",
                "url": url,
                "duration": duration,
                "is_radio": True
            }
            self.current_video_start_time = time.time() - max(0, seek_seconds)
            log_print(f"[Radio] Now Playing (BGM Audio): {title} (seek: {int(seek_seconds)}s, pts_offset: {self.accumulated_pts:.2f}s)")
        except Exception as e:
            log_print(f"[Radio] Failed to get audio stream URL: {e}")
            self.current_video = {"title": f"Failed: {video_info.get('title', 'Unknown')}", "url": url, "duration": 0, "is_radio": True}
            self.status = "error"
            self.status_detail = "Failed to load audio stream"
            return None

        if not self.ensure_stream_sink():
            self.current_video = {"title": "FFmpeg Error (Check PATH)", "url": url, "duration": 0, "is_radio": True}
            self.status = "error"
            self.status_detail = "FFmpeg Error"
            return None

        source = self.config.get("radio_bg_source", "card")
        auto_advance = bool(self.config.get("image_auto_advance", False)) and not self.image_paused

        slideshow_manifest_path = None
        if source == "slideshow" and auto_advance:
            slideshow_manifest_path = self.build_slideshow_manifest(
                track_seconds=duration, label="Radio")

        if slideshow_manifest_path and os.path.exists(slideshow_manifest_path):
            video_input_opts = [
                "-stream_loop", "-1",
                "-f", "concat",
                "-safe", "0",
                "-i", os.path.abspath(slideshow_manifest_path)
            ]
        else:
            bg_path = self.get_radio_background_path(video_info, metadata)
            if not bg_path or not os.path.exists(bg_path):
                self.generate_standby_image()
                bg_path = STANDBY_IMAGE_PATH
            video_input_opts = [
                "-loop", "1",
                "-i", os.path.abspath(bg_path)
            ]

        headers_str = ""
        if headers:
            headers_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

        input_opts = []
        if not is_local:
            input_opts.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "2",
                "-reconnect_on_network_error", "1",
                "-reconnect_on_http_error", "4xx,5xx",
                "-rw_timeout", "10000000",
            ])
            if headers_str:
                input_opts.extend(["-headers", headers_str])
        if seek_seconds > 0:
            input_opts.extend(["-ss", str(int(seek_seconds))])

        clock_video = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
        has_clock = bool(clock_video)
        clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

        # QRオーバーレイ判定（スライドショーは get_image_for_playback で合成済みのため除外）
        is_slideshow = bool(slideshow_manifest_path and os.path.exists(slideshow_manifest_path))
        overlay_radio = bool(self.config.get("overlay_qr_enabled", False)) and not is_slideshow
        qr_overlay_file = self.generate_qr_overlay_image() if overlay_radio else None
        has_qr = bool(overlay_radio and qr_overlay_file and os.path.exists(qr_overlay_file))

        cmd = [get_ffmpeg_cmd()]
        cmd.extend(video_input_opts)           # [0] = 静止画 or concat
        cmd.extend(input_opts)
        cmd.extend(["-i", audio_url])           # [1] = YouTube音声

        if has_qr:
            cmd.extend(["-loop", "1", "-i", os.path.abspath(qr_overlay_file)])  # [2] = QRオーバーレイ
            qr_mode = self.config.get("overlay_qr_mode", "bottom-right")
            overlay_filter = self._build_video_filter_complex(
                has_qr=True, has_clock=has_clock, qr_idx=2, qr_mode=qr_mode, clock_filter=clock_filter
            )
            cmd.extend([
                "-filter_complex", overlay_filter,
                "-map", "[vout]",
                "-map", "1:a:0",
            ])
        elif has_clock and clock_filter:
            cmd.extend([
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-vf", clock_filter,
            ])
        else:
            cmd.extend([
                "-map", "0:v:0",
                "-map", "1:a:0",
            ])
        # ★送出経路ごとに画質が大きく違う（ラジオ200k / 写真1500k / 動画2500k）。
        # VRC側で「これだけ汚い」と感じたとき、どの経路を通ったのかが
        # 分からないと切り分けができないため、必ず名前とビットレートを残す。
        # 曲間フェード（タスク17）。ホットリロードでの復帰(seek>0)では
        # フェードインを掛けない ＝ 設定保存のたびに音量が揺れるのを防ぐ。
        radio_af = build_radio_audio_filter(
            self.get_radio_crossfade_duration(),
            duration=duration,
            seek_seconds=seek_seconds,
        )
        log_print(
            f"[Player] Encoder path=radio 1920x1080@2fps v=200k(max250k/buf200k) "
            f"baseline/ultrafast bg={'slideshow' if is_slideshow else self.config.get('radio_bg_source', 'card')} "
            f"af={radio_af}"
        )
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-profile:v", "baseline",
            "-level", "3.1",
            "-bf", "0",
            "-sc_threshold", "0",
            # -r 2 で -g 15 は GOP 7.5秒。3秒セグメントと噛み合わないため時間式で強制する。
            *get_keyframe_opts(self.config.get("hls_segment_time", 3)),
            "-pix_fmt", "yuv420p",
            "-r", "2",
            "-b:v", "200k",
            "-maxrate", "250k",
            "-bufsize", "200k",
            "-c:a", "aac",
            "-b:a", "128k",
            "-ar", "44100",
            "-af", radio_af,
            "-shortest",
            "-fflags", "+nobuffer+flush_packets",
            "-flush_packets", "1",
            "-muxdelay", "0",
            "-muxpreload", "0",
            # 映像と音声を必ず時刻順に多重化する（先行した側を待ち合わせる）。
            # スライドショー背景は concat + -stream_loop -1 のため、マニフェストが
            # 一周するたびに映像PTSだけが音声より十数秒〜25秒先へ飛び、
            # 既定の max_interleave_delta(10秒) を超えて「過去に戻るDTS」を
            # 受信側FFmpegへ流し込んでいた。受信側HLS multiplexerはそこで
            # セグメント出力を停止し、配信が固まっていた。
            "-max_interleave_delta", "0",
            *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
        ])

        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            log_print(f"[Radio] Error starting Radio sender: {e}")
            self.status = "error"
            self.status_detail = f"Radio sender error: {e}"
            return None

        with self.process_lock:
            self.send_proc = proc

        stop_event = threading.Event()
        threading.Thread(target=self.relay_stream_data,
                         args=(proc, self.current_stdin, stop_event), daemon=True).start()
        threading.Thread(target=self.watch_send_proc,
                         args=(proc, stop_event), daemon=True).start()
        return stop_event

    def play_video(self, video_info, seek_seconds=0):
        url = video_info.get("url", "")
        is_local = bool(video_info.get("is_local") or video_info.get("type") == "local_video" or (video_info.get("path") and os.path.exists(video_info["path"])))
        try:
            if is_local:
                video_url = os.path.abspath(video_info.get("path") or url)
                audio_url = None
                title = video_info.get("title") or os.path.splitext(os.path.basename(video_url))[0]
                duration = video_info.get("duration", 0)
                if not duration:
                    duration = get_video_file_duration(video_url)
                headers = None
                log_print(f"[Player] Using local video file: {title} ({video_url})")
            else:
                cached = None
                with self.prefetch_lock:
                    if url in self.prefetch_cache and not self.prefetch_cache[url].get("is_radio"):
                        c = self.prefetch_cache.pop(url)
                        if time.time() - c.get("timestamp", 0) < 600:
                            cached = c

                if cached:
                    video_url = cached["video_url"]
                    audio_url = cached["audio_url"]
                    title = cached["title"]
                    duration = cached["duration"]
                    headers = cached["headers"]
                    log_print(f"[Player] Using pre-fetched stream URLs for: {title}")
                else:
                    video_url, audio_url, title, duration, headers = self.get_stream_urls(url)

            self.current_video = {
                "title": title,
                "url": url,
                "duration": duration
            }
            self.current_video_start_time = time.time() - max(0, seek_seconds)
            log_print(f"[Player] Now Playing: {title} (seek: {int(seek_seconds)}s, pts_offset: {self.accumulated_pts:.2f}s)")
        except Exception as e:
            log_print(f"[Player] Failed to get stream URL: {e}")
            self.current_video = {"title": f"Failed: {video_info.get('title', 'Unknown')}", "url": url, "duration": 0}
            self.status = "error"
            self.status_detail = "Failed to load stream"
            return None

        # 受信側FFmpegが未起動/停止時のみ起動（ストリームの連続性を維持）
        if not self.ensure_stream_sink():
            self.current_video = {"title": "FFmpeg Error (Check PATH)", "url": url, "duration": 0}
            self.status = "error"
            self.status_detail = "FFmpeg Error"
            return None

        headers_str = ""
        if headers:
            headers_str = "".join(f"{k}: {v}\r\n" for k, v in headers.items())

        input_opts = []
        if not is_local:
            input_opts.extend([
                "-reconnect", "1",
                "-reconnect_streamed", "1",
                "-reconnect_delay_max", "2",
                "-reconnect_on_network_error", "1",
                "-reconnect_on_http_error", "4xx,5xx",
                "-rw_timeout", "10000000",
            ])
            if headers_str:
                input_opts.extend(["-headers", headers_str])
        if seek_seconds > 0:
            input_opts.extend(["-ss", str(int(seek_seconds))])

        overlay_video = bool(self.config.get("overlay_qr_enabled", False) or self.config.get("overlay_qr_video", False))
        qr_overlay_file = self.generate_qr_overlay_image() if overlay_video else None

        clock_video = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
        has_clock = bool(clock_video)
        clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

        cmd = [get_ffmpeg_cmd(), "-fflags", "+genpts"]
        cmd.extend(input_opts)
        cmd.extend(["-i", video_url])
        if audio_url:
            cmd.extend(input_opts)
            cmd.extend(["-i", audio_url])

        has_qr = bool(overlay_video and qr_overlay_file and os.path.exists(qr_overlay_file))
        has_clock = bool(clock_video)

        # ローカルファイルを無条件に再エンコードしていたため、URL追加なら無劣化で
        # 届く映像が、アップロードした瞬間に作り直されていた。そのまま流せるものは
        # 流す。判定はファイルごとに1度だけ（低速メディアで毎回プローブを走らせない）。
        needs_reencode_local = False
        if is_local:
            if "can_stream_copy" not in video_info:
                params = probe_video_stream_params(video_info.get("path") or video_url)
                ok, why = can_stream_copy_local_video(params, self.get_max_video_height())
                video_info["can_stream_copy"] = ok
                video_info["stream_copy_reason"] = why
                log_print(f"[Player] Local video passthrough {'OK' if ok else 'NG'}: {why}")
            needs_reencode_local = not video_info.get("can_stream_copy")

        if has_qr or has_clock or needs_reencode_local:
            if has_qr:
                qr_idx = 2 if audio_url else 1
                cmd.extend(["-loop", "1", "-i", os.path.abspath(qr_overlay_file)])
                mode = self.config.get("overlay_qr_mode", "bottom-right")
            else:
                qr_idx = 0
                mode = "bottom-right"

            overlay_filter = self._build_video_filter_complex(has_qr, has_clock, qr_idx, mode, clock_filter)

            if overlay_filter:
                cmd.extend([
                    "-filter_complex", overlay_filter,
                    "-map", "[vout]"
                ])
            else:
                cmd.extend(["-map", "0:v:0"])
            if audio_url:
                cmd.extend(["-map", "1:a:0"])
            else:
                cmd.extend(["-map", "0:a:0?"])
            reason = ",".join(k for k, v in (("qr", has_qr), ("clock", has_clock),
                                             ("local:" + str(video_info.get("stream_copy_reason", "?")),
                                              needs_reencode_local)) if v)
            log_print(f"[Player] Encoder path=video/reencode v=2500k(max3000k/buf2000k) "
                      f"baseline/ultrafast reason={reason}")
            cmd.extend([
                *build_video_encoder_opts(
                    self.get_video_encoder(),
                    v_kbps=2500, max_kbps=3000, buf_kbps=2000,
                    h264_profile="baseline", bf_zero=False),
                "-c:a", "aac", "-b:a", "128k",
                "-af", "aresample=async=1",
                "-shortest",
            ])
            # セグメント境界にIDRを置く（-g のフレーム数指定では入力fps次第でずれる）
            cmd.extend(get_keyframe_opts(self.config.get("hls_segment_time", 3)))
            # ラジオ経路と同じ多重化設定。これが無いと既定の muxdelay/muxpreload と
            # max_interleave_delta(10秒) が効き、映像と音声の待ち合わせが崩れる。
            cmd.extend([
                "-fflags", "+nobuffer+flush_packets",
                "-flush_packets", "1",
                "-muxdelay", "0",
                "-muxpreload", "0",
                "-max_interleave_delta", "0",
                *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
            ])
        else:
            cmd.extend(["-map", "0:v:0"])
            if audio_url:
                cmd.extend(["-map", "1:a:0"])
            else:
                cmd.extend(["-map", "0:a:0?"])
            log_print("[Player] Encoder path=video/copy (no re-encode, source quality preserved)")
            # コピー経路ではIDR位置を制御できない（受信側がキーフレームで分割する）。
            cmd.extend(["-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-af", "aresample=async=1", "-shortest",
                        "-fflags", "+nobuffer+flush_packets", "-flush_packets", "1",
                        "-muxdelay", "0", "-muxpreload", "0", "-max_interleave_delta", "0",
                        *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"])

        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            log_print(f"[Player] Error starting FFmpeg sender: {e}")
            self.status = "error"
            self.status_detail = f"FFmpeg sender error: {e}"
            return None

        with self.process_lock:
            self.send_proc = proc

        stop_event = threading.Event()
        threading.Thread(target=self.relay_stream_data,
                         args=(proc, self.current_stdin, stop_event), daemon=True).start()
        threading.Thread(target=self.watch_send_proc,
                         args=(proc, stop_event), daemon=True).start()
        return stop_event

    _stream_video = play_video

    def _build_video_filter_complex(self, has_qr, has_clock, qr_idx, qr_mode, clock_filter):
        """QR/時計オーバーレイ用 -filter_complex 文字列を安全に構築（動画・ラジオ共通）"""
        if has_qr:
            if qr_mode == "fullscreen":
                base = f"[{qr_idx}:v][0:v]scale2ref[qr_scaled][vmain];[vmain][qr_scaled]overlay=0:0:shortest=1"
            else:
                base = f"[0:v][{qr_idx}:v]overlay=main_w-overlay_w-25:main_h-overlay_h-25:shortest=1"

            if has_clock:
                return base + f"[v_qr];[v_qr]{clock_filter}[vout]"
            else:
                return base + "[vout]"
        elif has_clock:
            return f"[0:v]{clock_filter}[vout]"
        return None

    def optimize_image_to_cache(self, img_input, output_filename=None):
        """PIL画像、バイナリ、またはファイルパスから 1920x1080 黒帯付き最適化画像を生成して保存"""
        os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
        if not output_filename:
            output_filename = f"photo_{int(time.time())}_{random.randint(1000, 9999)}.png"
        output_path = os.path.join(IMAGE_CACHE_DIR, output_filename)

        try:
            src_bytes = None
            if isinstance(img_input, str):
                img = Image.open(img_input)
                try:
                    src_bytes = os.path.getsize(img_input)
                except OSError:
                    pass
            elif isinstance(img_input, (bytes, bytearray)):
                img = Image.open(io.BytesIO(img_input))
                src_bytes = len(img_input)
            elif isinstance(img_input, Image.Image):
                img = img_input
            else:
                return None

            # ★受け取った時点の素性を必ず残す。ホスト追加とWebアップは
            # ここから先が完全に同じ経路なので、画質差を疑うときに
            # 「届いた画像が既に小さいのか」を切り分けられるのはこのログだけ。
            # exif_transpose は新しい画像を返して format を失うため、先に控える。
            src_format = getattr(img, "format", None) or "?"

            # EXIF回転補正
            img = ImageOps.exif_transpose(img)
            src_size = img.size

            # RGBモードに変換
            if img.mode != "RGB":
                img = img.convert("RGBA")
                canvas = Image.new("RGBA", img.size, (0, 0, 0, 255))
                img = Image.alpha_composite(canvas, img).convert("RGB")

            # 1920x1080 (16:9) 黒背景にアスペクト比維持でレターボックス配置
            target_w, target_h = 1920, 1080
            src_w, src_h = img.size

            ratio = min(target_w / src_w, target_h / src_h)
            new_w = max(1, int(src_w * ratio))
            new_h = max(1, int(src_h * ratio))

            log_print(
                f"[Core] Image source: {src_size[0]}x{src_size[1]} {src_format}"
                f"{f' ({src_bytes / 1024:.0f}KB)' if src_bytes else ''}"
                f" -> {new_w}x{new_h} on {target_w}x{target_h} (scale x{ratio:.2f})"
            )

            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            final_img = Image.new("RGB", (target_w, target_h), (0, 0, 0))
            offset_x = (target_w - new_w) // 2
            offset_y = (target_h - new_h) // 2
            final_img.paste(img_resized, (offset_x, offset_y))

            final_img.save(output_path, "PNG")
            return output_path
        except Exception as e:
            log_print(f"[Core] Error optimizing image: {e}")
            return None

    def add_video_file(self, file_path, title=None, original_filename=None, is_uploaded=False):
        """ローカル動画ファイルを動画キュー (play_queue) に追加"""
        with self.queue_lock:
            if len(self.play_queue) >= MAX_QUEUE_CAPACITY:
                log_print(f"[Core] Queue capacity reached ({MAX_QUEUE_CAPACITY}).")
                return None

        if not os.path.exists(file_path):
            log_print(f"[Core] Video file not found: {file_path}")
            return None

        clean_orig = original_filename or os.path.basename(file_path)
        if not title:
            base_name = os.path.splitext(clean_orig)[0]
            title = f"🎬 {base_name}" if not base_name.startswith("🎬") else base_name

        duration = get_video_file_duration(file_path)
        video_id = f"v_{uuid.uuid4().hex[:8]}"
        item = {
            "id": video_id,
            "type": "local_video",
            "title": title,
            "url": os.path.abspath(file_path),
            "path": os.path.abspath(file_path),
            "original_filename": clean_orig,
            "duration": duration,
            "is_local": True,
            "is_uploaded": is_uploaded
        }
        with self.queue_lock:
            self.play_queue.append(item)
        log_print(f"[Core] Added local video to queue: {title} (id: {video_id}, {duration:.1f}s)")
        return item

    def add_video_bytes(self, video_bytes, original_filename="video.mp4"):
        """アップロードされた動画バイナリを videos フォルダに保存してキューに追加"""
        with self.queue_lock:
            if len(self.play_queue) >= MAX_QUEUE_CAPACITY:
                log_print(f"[Core] Queue capacity reached ({MAX_QUEUE_CAPACITY}).")
                return None

        os.makedirs(VIDEO_STORAGE_DIR, exist_ok=True)
        ext = os.path.splitext(original_filename)[1].lower()
        if ext not in (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".ts", ".flv"):
            ext = ".mp4"
        saved_filename = f"upload_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
        saved_path = os.path.join(VIDEO_STORAGE_DIR, saved_filename)

        try:
            with open(saved_path, "wb") as f:
                f.write(video_bytes)
        except Exception as e:
            log_print(f"[Core] Failed to save uploaded video file: {e}")
            return None

        log_print(f"[Core] Uploaded video received: {original_filename} ({len(video_bytes) / (1024 * 1024):.1f}MB)")
        return self.add_video_file(saved_path, original_filename=original_filename, is_uploaded=True)

    def add_image_file(self, file_path, title=None):
        """ローカル画像ファイルを最適化して写真プールに追加"""
        with self.photo_lock:
            if len(self.photo_pool) >= MAX_PHOTO_CAPACITY:
                log_print(f"[Core] Photo pool capacity reached ({MAX_PHOTO_CAPACITY}).")
                return None

        cached_path = self.optimize_image_to_cache(file_path)
        if not cached_path:
            return None

        if not title:
            title = os.path.splitext(os.path.basename(file_path))[0]

        duration = int(self.config.get("image_display_duration", 15))
        photo_id = f"p_{uuid.uuid4().hex[:8]}"
        item = {
            "id": photo_id,
            "type": "image",
            "title": f"🖼 {title}",
            "url": os.path.basename(cached_path),
            "path": cached_path,
            "original_filename": os.path.basename(file_path),
            "duration": duration
        }
        with self.photo_lock:
            self.photo_pool.append(item)
        log_print(f"[Core] Added photo to pool: {title} (id: {photo_id}, {duration}s)")
        self.request_stream_reload()
        return item

    def add_image_bytes(self, image_bytes, original_filename="photo.jpg"):
        """アップロードされた画像バイナリを最適化して写真プールに追加"""
        with self.photo_lock:
            if len(self.photo_pool) >= MAX_PHOTO_CAPACITY:
                log_print(f"[Core] Photo pool capacity reached ({MAX_PHOTO_CAPACITY}).")
                return None

        cached_path = self.optimize_image_to_cache(image_bytes)
        if not cached_path:
            return None

        title = os.path.splitext(os.path.basename(original_filename))[0] or "Uploaded Photo"
        duration = int(self.config.get("image_display_duration", 15))
        photo_id = f"p_{uuid.uuid4().hex[:8]}"
        item = {
            "id": photo_id,
            "type": "image",
            "title": f"🖼 {title}",
            "url": os.path.basename(cached_path),
            "path": cached_path,
            "original_filename": original_filename,
            "duration": duration
        }
        with self.photo_lock:
            self.photo_pool.append(item)
        log_print(f"[Core] Added uploaded photo to pool: {title} (id: {photo_id}, {duration}s)")
        self.request_stream_reload()
        return item

    def get_photos(self):
        """写真プール内の有効な写真一覧を取得"""
        with self.photo_lock:
            valid = []
            for p in self.photo_pool:
                if p.get("path") and os.path.exists(p["path"]):
                    valid.append(dict(p))
            return valid

    def remove_photo(self, photo_id_or_idx):
        """写真プールから特定の写真を削除（キャッシュファイルも削除）"""
        with self.photo_lock:
            target_idx = None
            if isinstance(photo_id_or_idx, int):
                if 0 <= photo_id_or_idx < len(self.photo_pool):
                    target_idx = photo_id_or_idx
            elif isinstance(photo_id_or_idx, str):
                for idx, p in enumerate(self.photo_pool):
                    if p.get("id") == photo_id_or_idx or p.get("url") == photo_id_or_idx or p.get("path") == photo_id_or_idx:
                        target_idx = idx
                        break
            if target_idx is not None:
                removed = self.photo_pool.pop(target_idx)
                if removed.get("path") and os.path.exists(removed["path"]):
                    try:
                        os.remove(removed["path"])
                    except Exception:
                        pass
                log_print(f"[Core] Removed photo from pool: {removed.get('title')}")
                self.request_stream_reload()
                return True
            return False

    def move_photo(self, from_idx: int, to_idx: int):
        """写真プール内の写真の順序を入れ替え"""
        with self.photo_lock:
            if 0 <= from_idx < len(self.photo_pool) and 0 <= to_idx < len(self.photo_pool):
                item = self.photo_pool.pop(from_idx)
                self.photo_pool.insert(to_idx, item)
                log_print(f"[Core] Moved photo in pool from {from_idx} to {to_idx}")
                return True
            return False

    def clear_photos(self):
        """写真プール内の全写真を削除"""
        with self.photo_lock:
            for p in self.photo_pool:
                if p.get("path") and os.path.exists(p["path"]):
                    try:
                        os.remove(p["path"])
                    except Exception:
                        pass
            self.photo_pool.clear()
            self.slideshow_index = 0
            log_print("[Core] Cleared all photos from photo pool.")
            self.request_stream_reload()
            return True

    def play_image(self, image_info):
        """最適化済み静止画像をFFmpegネイティブでHLS配信（安全・低遅延）"""
        image_path = image_info.get("path")
        if not image_path or not os.path.exists(image_path):
            log_print(f"[Player] Image file not found: {image_path}")
            self.current_video = {"title": "Image not found", "url": "", "duration": 0, "type": "image"}
            self.status = "error"
            self.status_detail = "Image file not found"
            return None

        # QRオーバーレイが有効な場合はQR合成済み画像パスを取得
        playback_image_path = self.get_image_for_playback(image_path)

        if not self.ensure_stream_sink():
            self.current_video = {"title": "FFmpeg Error", "url": "", "duration": 0, "type": "image"}
            self.status = "error"
            self.status_detail = "FFmpeg Error"
            return None

        clock_video = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
        has_clock = bool(clock_video)
        clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

        cmd = [
            get_ffmpeg_cmd(), "-re",
        ]
        cmd.extend([
            "-loop", "1", "-i", os.path.abspath(playback_image_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        ])
        if has_clock and clock_filter:
            cmd.extend(["-vf", clock_filter])
        log_print("[Player] Encoder path=image 1920x1080@30fps v=1500k(buf1000k) baseline/ultrafast g=30")
        cmd.extend([
            *build_video_encoder_opts(
                self.get_video_encoder(),
                v_kbps=1500, max_kbps=1500, buf_kbps=1000,
                h264_profile="baseline", sc_threshold_zero=True,
                gop_frames=30, fps=30),
            "-c:a", "aac", "-b:a", "64k",
            "-fflags", "+nobuffer+flush_packets",
            "-flush_packets", "1",
            "-muxdelay", "0",
            "-muxpreload", "0",
            *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
        ])

        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            log_print(f"[Player] Error starting Photo sender: {e}")
            self.status = "error"
            self.status_detail = f"Photo sender error: {e}"
            return None

        with self.process_lock:
            self.send_proc = proc

        stop_event = threading.Event()
        threading.Thread(target=self.relay_stream_data,
                         args=(proc, self.current_stdin, stop_event, False), daemon=True).start()
        threading.Thread(target=self.watch_send_proc,
                         args=(proc, stop_event), daemon=True).start()
        return stop_event

    def _resolve_app_audio_pid(self):
        """設定からアプリ音声の対象PIDを解決する。無効・未選択・不在なら None。

        ★正本はウィンドウタイトル。PIDは対象アプリの再起動で変わるので、
          配信を始める瞬間にタイトルから引き直す（タスク23と同じ考え方）。
        """
        if not self.config.get("live_audio_app_enabled", False):
            return None
        title = str(self.config.get("live_audio_app_window_title", "")).strip()
        if not title:
            log_print("[AppAudio] 対象ウィンドウ未選択 -> アプリ音声なしで続行")
            return None
        win = find_capture_window(title)
        if not win:
            log_print(f"[AppAudio] 対象ウィンドウが見つからない: '{title}' -> アプリ音声なしで続行")
            return None
        pid = win.get("pid")
        log_print(f"[AppAudio] 対象ウィンドウ '{title}' -> pid={pid}")
        return pid

    def start_app_audio_capture(self):
        """アプリ音声の補助exeを起動する。使えないときは None（fail-soft）。"""
        pid = self._resolve_app_audio_pid()
        if not pid:
            return None
        proc = start_app_audio_helper(
            pid,
            mode=self.config.get("live_audio_app_mode", "include"),
            stats_sec=int(self.config.get("live_audio_app_stats_sec", 0) or 0)
        )
        if proc:
            self.app_audio_level = None
            threading.Thread(target=self._pump_app_audio_stderr,
                             args=(proc,), daemon=True).start()
        return proc

    def _pump_app_audio_stderr(self, helper_proc):
        """補助exeの stderr を読み続け、入力レベルを拾い、それ以外はログへ流す。

        ★読み続けること自体が必須。stderr を PIPE にして誰も読まないと、
          パイプのバッファが埋まった時点で補助exeが書き込みでブロックし、
          音が止まる。
        """
        try:
            for raw in iter(helper_proc.stderr.readline, b""):
                try:
                    line = raw.decode("utf-8", "replace").strip()
                except Exception:
                    continue
                if not line:
                    continue
                m = re.search(r"level peak=([\d.]+) rms=([\d.]+)", line)
                if m:
                    try:
                        self.app_audio_level = {
                            "peak": float(m.group(1)),
                            "rms": float(m.group(2)),
                            "ts": time.time(),
                        }
                    except ValueError:
                        pass
                    continue
                # レベル以外は診断情報なので残す（従来は捨てていた）。
                log_print(line)
        except Exception:
            pass
        finally:
            try:
                helper_proc.stderr.close()
            except Exception:
                pass

    def get_app_audio_level(self):
        """UIのゲージ用に、直近の入力レベルを返す。古ければ 0 扱い。"""
        lv = getattr(self, "app_audio_level", None) or {}
        ts = lv.get("ts", 0.0)
        age = time.time() - ts if ts else None
        fresh = bool(ts) and age is not None and age < APP_AUDIO_LEVEL_STALE_SEC
        return {
            "peak": float(lv.get("peak", 0.0)) if fresh else 0.0,
            "rms": float(lv.get("rms", 0.0)) if fresh else 0.0,
            "fresh": fresh,
        }

    def reap_app_audio_helper(self, sender_proc, helper_proc):
        """送出FFmpegが終わったら補助exeを確実に落とす。

        送出側の kill 箇所は多数あるので、個別に手を入れるのではなく
        送出プロセスの寿命に紐づけて回収する。
        """
        if not helper_proc:
            return
        try:
            sender_proc.wait()
        except Exception:
            pass
        kill_proc(helper_proc)
        self.app_audio_level = None
        log_print("[AppAudio] helper stopped")

    def set_live_audio_app(self, enabled=None, window_title=None, volume=None, mode=None):
        """アプリ単位の音声取り込み設定を更新する。"""
        if enabled is not None:
            self.config["live_audio_app_enabled"] = bool(enabled)
        if window_title is not None:
            self.config["live_audio_app_window_title"] = str(window_title)
        if volume is not None:
            try:
                self.config["live_audio_app_volume"] = max(0.0, min(2.0, float(volume)))
            except (TypeError, ValueError):
                pass
        if mode in ("include", "exclude"):
            self.config["live_audio_app_mode"] = mode
        self.save_config()
        self.request_stream_reload()
        return {
            "live_audio_app_enabled": bool(self.config.get("live_audio_app_enabled", False)),
            "live_audio_app_window_title": str(self.config.get("live_audio_app_window_title", "")),
            "live_audio_app_volume": float(self.config.get("live_audio_app_volume", 1.0)),
            "live_audio_app_mode": str(self.config.get("live_audio_app_mode", "include")),
            "app_audio_available": bool(get_app_audio_capture_cmd()),
        }

    def set_live_audio_devices(self, mic_device=None, loopback_device=None,
                               mic_volume=None, loopback_volume=None):
        """PC音声/マイク取り込みデバイス・音量を設定"""
        if mic_device is not None:
            self.config["live_audio_mic_device"] = str(mic_device)
        if loopback_device is not None:
            self.config["live_audio_loopback_device"] = str(loopback_device)
        if mic_volume is not None:
            try:
                v = float(mic_volume)
                self.config["live_audio_mic_volume"] = max(0.0, min(2.0, v))
            except (TypeError, ValueError):
                pass
        if loopback_volume is not None:
            try:
                v = float(loopback_volume)
                self.config["live_audio_loopback_volume"] = max(0.0, min(2.0, v))
            except (TypeError, ValueError):
                pass
        self.save_config()
        self.request_stream_reload()
        return {
            "live_audio_mic_device": self.config.get("live_audio_mic_device", ""),
            "live_audio_loopback_device": self.config.get("live_audio_loopback_device", ""),
            "live_audio_mic_volume": self.config.get("live_audio_mic_volume", 1.0),
            "live_audio_loopback_volume": self.config.get("live_audio_loopback_volume", 0.7),
        }

    def set_live_audio_bg_source(self, source: str):
        """ライブ音声の背景を切り替える。想定外の値は無視して現状を返す。"""
        if source in ("standby", "slideshow"):
            self.config["live_audio_bg_source"] = source
            self.save_config()
            self.request_stream_reload()
        return self.config.get("live_audio_bg_source", "standby")

    def set_screen_capture_source(self, source_type=None, display_index=None, window_title=None,
                                  framerate=None, width=None, height=None,
                                  draw_mouse=None, bitrate_kbps=None):
        """画面キャプチャ設定（入力ソース・フレームレート・解像度等）を更新"""
        if source_type in ("display", "window"):
            self.config["screen_capture_source_type"] = source_type
        if display_index is not None:
            try:
                idx = int(display_index)
                self.config["screen_capture_display_index"] = max(0, min(7, idx))
            except (TypeError, ValueError):
                pass
        if window_title is not None:
            new_title = str(window_title)
            # 選び直したらハンドルも取り直す（前のウィンドウを掴み続けない）
            if new_title != self.config.get("screen_capture_window_title"):
                self._screen_capture_hwnd = None
            self.config["screen_capture_window_title"] = new_title
            found = find_capture_window(new_title) if new_title else None
            self._screen_capture_hwnd = found.get("hwnd") if found else None
        if framerate is not None:
            try:
                fps = int(framerate)
                self.config["screen_capture_framerate"] = max(1, min(60, fps))
            except (TypeError, ValueError):
                pass
        if width is not None:
            try:
                w = int(width)
                w_clamped = max(320, min(3840, w))
                self.config["screen_capture_width"] = even_dimension(w_clamped)
            except (TypeError, ValueError):
                pass
        if height is not None:
            try:
                h = int(height)
                h_clamped = max(240, min(2160, h))
                self.config["screen_capture_height"] = even_dimension(h_clamped)
            except (TypeError, ValueError):
                pass
        if draw_mouse is not None:
            self.config["screen_capture_draw_mouse"] = bool(draw_mouse)
        if bitrate_kbps is not None:
            try:
                b = int(bitrate_kbps)
                self.config["screen_capture_bitrate_kbps"] = max(500, min(20000, b))
            except (TypeError, ValueError):
                pass

        self.save_config()
        self.request_stream_reload()
        return {
            "source_type": self.config.get("screen_capture_source_type", "display"),
            "display_index": self.config.get("screen_capture_display_index", 0),
            "window_title": self.config.get("screen_capture_window_title", ""),
            "framerate": self.config.get("screen_capture_framerate", 30),
            "width": self.config.get("screen_capture_width", 1920),
            "height": self.config.get("screen_capture_height", 1080),
            "draw_mouse": self.config.get("screen_capture_draw_mouse", True),
            "bitrate_kbps": self.config.get("screen_capture_bitrate_kbps", 4000),
        }

    def play_live_audio(self):
        """PC音声・マイク（dshow経路）を静止画背景でHLS/RTMPライブ配信"""
        mic_dev = str(self.config.get("live_audio_mic_device", "")).strip()
        loop_dev = str(self.config.get("live_audio_loopback_device", "")).strip()
        # タスク25: アプリ音声だけでも成立するので、3つとも無いときだけ弾く。
        app_on = bool(self.config.get("live_audio_app_enabled", False))
        if not mic_dev and not loop_dev and not app_on:
            log_print("[Player] Live audio capture warning: No devices selected")
            self.status = "error"
            self.status_detail = "ライブ音声デバイスが未選択です"
            return None

        if not self.ensure_stream_sink():
            self.status = "error"
            self.status_detail = "FFmpeg Error"
            return None

        # 背景。ラジオと同じ仕組みで「待機画面」か「スライドショー」を選べる。
        # ★スライドショーは ffconcat + -stream_loop -1 で ffmpeg 自身が巡回するので、
        #   写真を送るために配信を張り直す必要がない。終わりのないライブ音声に向く。
        bg_source = str(self.config.get("live_audio_bg_source", "standby"))
        auto_advance = bool(self.config.get("image_auto_advance", False)) and not self.image_paused

        slideshow_manifest_path = None
        if bg_source == "slideshow" and auto_advance:
            slideshow_manifest_path = self.build_slideshow_manifest(
                track_seconds=0, label="LiveAudio",
                manifest_name="slideshow_manifest_live.txt")

        if slideshow_manifest_path:
            video_input_opts = [
                "-re", "-stream_loop", "-1",
                "-f", "concat", "-safe", "0",
                "-i", os.path.abspath(slideshow_manifest_path)
            ]
        else:
            # スライドショー指定でも、写真が無い/自動送りOFFなら1枚で見せる。
            bg_image_path = None
            if bg_source == "slideshow":
                images = self.get_slideshow_images()
                if images:
                    bg_image_path = self.get_image_for_playback(images[0])
            # 待機画面。generate_standby_image() は描画に失敗しても例外を出さず
            # 進むことがあるため、パスの実在をここで必ず確かめる。None を
            # os.path.abspath() に渡すと TypeError で監視ループ側に飛ぶ。
            if not bg_image_path:
                bg_image_path = self.generate_standby_image()
            if not bg_image_path or not os.path.exists(bg_image_path):
                log_print(f"[Player] Live audio: background image unavailable ({bg_image_path})")
                self.status = "error"
                self.status_detail = "Live audio: background image unavailable"
                return None
            video_input_opts = ["-re", "-loop", "1", "-i", os.path.abspath(bg_image_path)]

        has_clock = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
        clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

        mic_vol = self.config.get("live_audio_mic_volume", 1.0)
        loop_vol = self.config.get("live_audio_loopback_volume", 0.7)

        app_helper = self.start_app_audio_capture()
        app_vol = self.config.get("live_audio_app_volume", 1.0)

        input_args, audio_filter, audio_map = build_audio_inputs(
            app_enabled=bool(app_helper),
            app_volume=app_vol,
            mic_device=mic_dev,
            loopback_device=loop_dev,
            mic_volume=mic_vol,
            loopback_volume=loop_vol,
            start_index=1
        )

        # ★入口のガードは「設定上どれか有効か」しか見ていない。アプリ音声だけを
        #   有効にしていて、いざ始める段になって対象ウィンドウが見つからない
        #   （補助exeが起動できない）と、ここで音声入力がゼロになる。
        #   そのまま進むと "-map None" という壊れたコマンドをFFmpegに渡し、
        #   何が悪いのか分からないまま配信が失敗していた。
        #   ★画面共有と違い、ここは音声だけのモード。無音を流しても意味が無く、
        #     機能が壊れているように見えるだけなので、理由を出して止める。
        if not audio_map:
            log_print("[Player] Live audio: 利用できる音声ソースがありません")
            kill_proc(app_helper)
            self.status = "error"
            self.status_detail = "音声ソースが利用できません（対象ウィンドウやデバイスを確認してください）"
            return None

        cmd = [get_ffmpeg_cmd()] + video_input_opts
        cmd.extend(input_args)

        if audio_filter and (has_clock and clock_filter):
            cmd.extend(["-filter_complex", f"[0:v]{clock_filter}[vout];{audio_filter}", "-map", "[vout]", "-map", audio_map])
        elif audio_filter and not (has_clock and clock_filter):
            cmd.extend(["-filter_complex", audio_filter, "-map", "0:v:0", "-map", audio_map])
        elif not audio_filter and (has_clock and clock_filter):
            cmd.extend(["-vf", clock_filter, "-map", "0:v:0", "-map", audio_map])
        else:
            cmd.extend(["-map", "0:v:0", "-map", audio_map])

        bitrate_kbps = str(int(self.config.get("live_audio_bitrate_kbps", 192)))
        cmd.extend([
            *build_video_encoder_opts(
                self.get_video_encoder(),
                v_kbps=800, max_kbps=1000, buf_kbps=800,
                h264_profile="baseline", sc_threshold_zero=True,
                gop_frames=15, fps=5),
            "-c:a", "aac",
            "-b:a", f"{bitrate_kbps}k",
            "-ar", "44100",
            "-fflags", "+nobuffer+flush_packets",
            "-flush_packets", "1",
            "-muxdelay", "0",
            "-muxpreload", "0",
            "-max_interleave_delta", "0",
            *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
        ])

        log_print(f"[Player] Encoder path=live_audio mic='{mic_dev}' loopback='{loop_dev}' "
                  f"mic_vol={mic_vol} loopback_vol={loop_vol} b:a={bitrate_kbps}k "
                  f"bg={'slideshow(concat)' if slideshow_manifest_path else bg_source + '(still)'}")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=(app_helper.stdout if app_helper else subprocess.DEVNULL),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            log_print(f"[Player] Error starting live audio sender: {e}")
            kill_proc(app_helper)
            self.status = "error"
            self.status_detail = f"Live audio sender error: {e}"
            return None

        with self.process_lock:
            self.send_proc = proc

        # ★親側の読み口は閉じる。閉じないと補助exeが終わってもEOFが伝わらない。
        if app_helper and app_helper.stdout:
            try:
                app_helper.stdout.close()
            except Exception:
                pass
        if app_helper:
            threading.Thread(target=self.reap_app_audio_helper,
                             args=(proc, app_helper), daemon=True).start()

        stop_event = threading.Event()
        threading.Thread(target=self.relay_stream_data,
                         args=(proc, self.current_stdin, stop_event, False), daemon=True).start()
        threading.Thread(target=self.watch_send_proc,
                         args=(proc, stop_event), daemon=True).start()
        return stop_event

    def play_screen_capture(self):
        """ホストPCの画面（ディスプレイ or ウィンドウ）を音声つきでライブ配信"""
        source_type = self.config.get("screen_capture_source_type", "display")
        display_index = self.config.get("screen_capture_display_index", 0)
        window_title = self.config.get("screen_capture_window_title", "")
        framerate = self.config.get("screen_capture_framerate", 30)
        width = self.config.get("screen_capture_width", 1920)
        height = self.config.get("screen_capture_height", 1080)
        draw_mouse = self.config.get("screen_capture_draw_mouse", True)
        bitrate_kbps = self.config.get("screen_capture_bitrate_kbps", 4000)

        win = None
        if source_type == "window":
            if not window_title:
                self.status = "error"
                self.status_detail = "キャプチャ対象のウィンドウが未選択です"
                return None
            # ★同一性はハンドルで持つ。タイトルで引き直すと、YouTubeが次の動画へ
            #   進んだだけで見失う（実測: 配信開始12秒で停止し、以後15秒間隔で
            #   失敗し続けた）。ハンドルが生きている限り、タイトルが変わっても
            #   「利用者が選んだそのウィンドウ」を追い続ける。
            win = get_window_rect_by_hwnd(getattr(self, "_screen_capture_hwnd", None))
            if win is None:
                win = find_capture_window(window_title)
                if win is not None:
                    self._screen_capture_hwnd = win.get("hwnd")
            elif win.get("title") and win["title"] != window_title:
                log_print(f"[Player] Screen capture window title changed: "
                          f"'{window_title}' -> '{win['title']}' (ハンドルで追跡継続)")
            if win is None:
                log_print(f"[Player] Screen capture window not found: '{window_title}'")
                self.status = "error"
                self.status_detail = f"ウィンドウが見つかりません: {window_title}"
                return None

        if not self.ensure_stream_sink():
            self.status = "error"
            self.status_detail = "FFmpeg Error"
            return None

        has_clock = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
        clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

        mic_dev = self.config.get("live_audio_mic_device", "")
        loop_dev = self.config.get("live_audio_loopback_device", "")
        mic_vol = self.config.get("live_audio_mic_volume", 1.0)
        loop_vol = self.config.get("live_audio_loopback_volume", 0.7)

        # タスク25: アプリ単位の音声。使えないときは None が返り、従来の dshow 経路だけになる。
        app_helper = self.start_app_audio_capture()
        app_vol = self.config.get("live_audio_app_volume", 1.0)

        input_args_a, audio_filter, audio_map = build_audio_inputs(
            app_enabled=bool(app_helper),
            app_volume=app_vol,
            mic_device=mic_dev,
            loopback_device=loop_dev,
            mic_volume=mic_vol,
            loopback_volume=loop_vol,
            start_index=1
        )

        # ★ウィンドウ矩形は「配信を始める瞬間」の値を使う。以降ウィンドウを
        #   動かしても切り出し位置は追従しない（追従させるには送出の張り直しが
        #   要り、そのたびに画が飛ぶ）。動かしたら「適用」で取り直す運用にする。
        # ★配信先がRTMP系ならシンクが必ず作り直すので、それを超える寸法で送らない。
        if self.get_active_output_mode() in RTMP_OUTPUT_MODES:
            dest_w = self.config.get("rtmp_video_width", 1280)
            dest_h = self.config.get("rtmp_video_height", 720)
            capped_w, capped_h = clamp_capture_size_to_destination(width, height, dest_w, dest_h)
            if (capped_w, capped_h) != (width, height):
                log_print(f"[Player] Screen capture size capped to destination: "
                          f"{width}x{height} -> {capped_w}x{capped_h}")
                width, height = capped_w, capped_h

        window_plan = resolve_window_capture_plan(win) if win else None
        if source_type == "window" and window_plan is None:
            log_print("[Player] Screen capture: could not resolve window capture plan.")
            kill_proc(app_helper)   # ここで抜けるなら補助exeも道連れにする
            self.status = "error"
            self.status_detail = "ウィンドウの取り込み方を決められませんでした"
            return None

        input_args_v, needs_hwdownload = build_screen_capture_input(
            source_type=source_type,
            display_index=display_index,
            window_title=window_title,
            framerate=framerate,
            draw_mouse=draw_mouse,
            window_plan=window_plan
        )
        if window_plan:
            log_print(f"[Player] Window capture via {window_plan[0]} {window_plan[1:]}")

        # ★音声デバイスが未設定でも**無音トラックを必ず載せる**。
        #   映像だけのストリームにすると HLS(-c copy) では再生できるのに、
        #   RTMP/FLV 経由（TopazChat -> VRChat/AVPro）でカクついて見える。
        #   待機画面・ラジオなど他のモードは元から anullsrc を入れており、
        #   画面共有だけが「音声トラックの無いストリーム」を送る唯一の例外だった。
        silent_audio = not audio_map
        if silent_audio:
            input_args_a = ["-f", "lavfi", "-i",
                            "anullsrc=channel_layout=stereo:sample_rate=44100"]

        cmd = [get_ffmpeg_cmd()] + input_args_v + input_args_a

        video_chain = build_screen_video_filter(needs_hwdownload, width, height, clock_filter)

        if audio_filter:
            cmd.extend(["-filter_complex", f"{video_chain};{audio_filter}"])
        else:
            cmd.extend(["-filter_complex", video_chain])

        cmd.extend(["-map", "[vout]"])
        if audio_map:
            cmd.extend(["-map", audio_map])
        else:
            # 無音入力は映像の次（index 1）に入る
            cmd.extend(["-map", "1:a"])

        try:
            fps = int(framerate)
        except (TypeError, ValueError):
            fps = 30
        fps = max(1, min(60, fps))

        try:
            b_kbps = int(bitrate_kbps)
        except (TypeError, ValueError):
            b_kbps = 4000
        b_kbps = max(500, min(20000, b_kbps))

        cmd.extend([
            *build_video_encoder_opts(
                self.get_video_encoder(),
                v_kbps=b_kbps, max_kbps=int(b_kbps * 1.15), buf_kbps=b_kbps,
                h264_profile="baseline", sc_threshold_zero=True,
                # ★GOPは必ず1秒。hls_segment_time(既定3秒)を割り切れる値でないと、
                #   HLSはキーフレームでしか切れないためセグメント長が振れる。
                #   実測: GOP2秒だと 120/60/120/60 フレーム＝4秒・2秒・4秒・2秒に
                #   なり、再生側にはカクつきとして出た。1秒にすると 90 フレーム
                #   ＝3.0秒でぴたりと揃う。他の再生モードも1秒で揃えている。
                gop_frames=fps, fps=fps)
        ])

        cmd.extend(["-c:a", "aac", "-b:a", "192k" if audio_map else "64k", "-ar", "44100"])

        cmd.extend([
            "-fflags", "+nobuffer+flush_packets", "-flush_packets", "1",
            "-muxdelay", "0", "-muxpreload", "0", "-max_interleave_delta", "0",
            *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
        ])

        log_print(f"[Player] Encoder path=screen_capture source={source_type} display={display_index} window='{window_title}' fps={fps} size={width}x{height} b:v={b_kbps}k")

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=(app_helper.stdout if app_helper else subprocess.DEVNULL),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            log_print(f"[Player] Error starting screen capture sender: {e}")
            kill_proc(app_helper)
            self.status = "error"
            self.status_detail = f"Screen capture sender error: {e}"
            return None

        with self.process_lock:
            self.send_proc = proc

        # ★親側の読み口は閉じる。閉じないと補助exeが終わってもEOFが伝わらない。
        if app_helper and app_helper.stdout:
            try:
                app_helper.stdout.close()
            except Exception:
                pass
        if app_helper:
            threading.Thread(target=self.reap_app_audio_helper,
                             args=(proc, app_helper), daemon=True).start()

        stop_event = threading.Event()
        threading.Thread(target=self.relay_stream_data,
                         args=(proc, self.current_stdin, stop_event, False), daemon=True).start()
        threading.Thread(target=self.watch_send_proc,
                         args=(proc, stop_event), daemon=True).start()
        return stop_event

    def add_to_queue(self, url):
        """URL（動画または画像）またはローカルファイルパスを解析してキューに追加"""
        with self.queue_lock:
            if len(self.play_queue) >= MAX_QUEUE_CAPACITY:
                log_print(f"[Core] Cannot add items: Queue reached max capacity ({MAX_QUEUE_CAPACITY}).")
                return []

        # ローカル動画ファイルの場合
        if is_video_url_or_file(url) and os.path.exists(url):
            item = self.add_video_file(url)
            return [item] if item else []

        # 画像URLまたはローカル画像ファイルの場合
        if is_image_url_or_file(url):
            if os.path.exists(url):
                item = self.add_image_file(url)
                return [item] if item else []
            is_safe, reason = is_safe_url(url)
            if not is_safe:
                log_print(f"[Core] Rejected unsafe image URL: {reason}")
                return []
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    img_bytes = resp.read(10 * 1024 * 1024) # max 10MB
                filename = url.split("/")[-1].split("?")[0] or "web_photo.png"
                item = self.add_image_bytes(img_bytes, filename)
                return [item] if item else []
            except Exception as e:
                log_print(f"[Core] Failed to fetch image URL: {e}")
                return []

        items = self.expand_playlist(url)
        if items:
            with self.queue_lock:
                available_space = max(0, MAX_QUEUE_CAPACITY - len(self.play_queue))
                items_to_add = items[:available_space]
                self.play_queue.extend(items_to_add)
            log_print(f"[Core] Added {len(items_to_add)} items to queue.")
            return items_to_add
        return []

    def skip(self):
        log_print("[Player] Skip requested.")
        self.skip_event.set()
        self.video_done_event.set()
        with self.process_lock:
            proc = self.send_proc
        if proc:
            kill_proc(proc)

    def clear_queue(self):
        with self.queue_lock:
            for item in self.play_queue:
                if item.get("is_uploaded") and item.get("path") and os.path.exists(item["path"]):
                    try:
                        os.remove(item["path"])
                    except Exception:
                        pass
            self.play_queue.clear()
        log_print("[Core] Queue cleared.")

    def delete_queue_item(self, idx):
        with self.queue_lock:
            if 0 <= idx < len(self.play_queue):
                removed = self.play_queue.pop(idx)
                if removed.get("is_uploaded") and removed.get("path") and os.path.exists(removed["path"]):
                    try:
                        os.remove(removed["path"])
                    except Exception:
                        pass
                log_print(f"[Core] Removed item at index {idx} ({removed.get('title')}) from queue.")
                return removed
        return None

    def move_queue_item(self, from_idx, to_idx):
        with self.queue_lock:
            if 0 <= from_idx < len(self.play_queue) and 0 <= to_idx < len(self.play_queue):
                item = self.play_queue.pop(from_idx)
                self.play_queue.insert(to_idx, item)
                return True
        return False

    def generate_qr_overlay_image(self):
        """動画・写真ストリーム上に重ねて表示するQRコードカード (RGBA) を生成（右下コンパクト/フル画面）"""
        # ホスト専用モードではQRは焼かない。ここが唯一の生成口なので、
        # 呼び出し側（動画・写真・ラジオ・待機画面）を1つずつ直す必要はない。
        # 呼び出し側はいずれも None を「オーバーレイ無し」として扱える作りになっている。
        if not self.is_web_remote_enabled():
            return None

        is_tunnel_ready = bool(self.tunnel_raw_url and "trycloudflare.com" in self.tunnel_raw_url)
        is_tunnel_enabled = getattr(self, "enable_tunnel", True)
        port = self.config.get("port", 8000)
        url = self.tunnel_raw_url if is_tunnel_ready else f"http://{get_local_ip()}:{port}"
        mode = self.config.get("overlay_qr_mode", "bottom-right")

        try:
            if mode == "fullscreen":
                # --- フル画面オーバーレイモード (1920x1080 半透明ダーク) ---
                width, height = 1920, 1080
                img = Image.new("RGBA", (width, height), color=(15, 23, 42, 225)) # 半透明ダークスレート
                draw = ImageDraw.Draw(img)

                draw.rectangle([(0, 0), (width, 90)], fill=(30, 41, 59, 240))
                draw.rectangle([(0, height - 70), (width, height)], fill=(30, 41, 59, 240))

                try:
                    font_title = ImageFont.truetype("arial.ttf", 52)
                    font_sub = ImageFont.truetype("arial.ttf", 30)
                    font_url = ImageFont.truetype("arial.ttf", 34)
                    font_info = ImageFont.truetype("arial.ttf", 24)
                except Exception:
                    font_title = font_sub = font_url = font_info = ImageFont.load_default()

                draw.text((width // 2, 45), "VRC_Media_Streamer", fill=(56, 189, 248, 255), anchor="mm", font=font_title)
                draw.text((width // 2, 140), "Scan QR code or visit URL below to request YouTube videos!", fill=(226, 232, 240, 255), anchor="mm", font=font_sub)

                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=12,
                    border=2,
                )
                qr.add_data(url)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGBA")

                qr_w, qr_h = qr_img.size
                qr_x = (width - qr_w) // 2
                qr_y = (height - qr_h) // 2 - 15

                card_pad = 22
                draw.rectangle(
                    [(qr_x - card_pad, qr_y - card_pad), (qr_x + qr_w + card_pad, qr_y + qr_h + card_pad)],
                    fill=(255, 255, 255, 255)
                )
                img.paste(qr_img, (qr_x, qr_y), qr_img)

                url_box_y = height - 160
                draw.text((width // 2, url_box_y), f"Web Request URL: {url}", fill=(248, 250, 252, 255), anchor="mm", font=font_url)
                draw.text((width // 2, url_box_y + 45), "Scan this QR code with your phone or visit the URL directly.", fill=(148, 163, 184, 255), anchor="mm", font=font_info)
                draw.text((width // 2, height - 35), "VRChat YouTube Streamer • Powered by yt-dlp & FFmpeg", fill=(100, 116, 139, 255), anchor="mm", font=font_info)

                img.save(QR_OVERLAY_PATH, "PNG")
                return QR_OVERLAY_PATH

            else:
                # --- 右下コンパクトモード (白角丸カード: QRコード + 完全URL併記) ---
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=5,
                    border=1,
                )
                qr.add_data(url)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGBA")

                qr_w, qr_h = qr_img.size # 約 150x150
                card_w = max(260, qr_w + 30)
                card_h = qr_h + 85 # QR + ラベル + URLテキスト用の高さを確保

                card = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
                draw = ImageDraw.Draw(card)

                # 角丸白カード (高い視認性を保ちつつアルファブレンド)
                radius = 12
                draw.rounded_rectangle(
                    [(0, 0), (card_w - 1, card_h - 1)],
                    radius=radius,
                    fill=(255, 255, 255, 245),
                    outline=(203, 213, 225, 245),
                    width=2
                )

                # QRコードを上部中央に配置
                qr_x = (card_w - qr_w) // 2
                card.paste(qr_img, (qr_x, 12), qr_img)

                # 下部にURLと案内を完全表記（手入力可能）
                try:
                    font_lbl = ImageFont.truetype("arial.ttf", 11)
                    font_size = 12 if len(url) <= 32 else (11 if len(url) <= 36 else 10)
                    font_url = ImageFont.truetype("arial.ttf", font_size)
                except Exception:
                    font_lbl = font_url = ImageFont.load_default()

                # ラベル「Request via QR or URL:」
                draw.text((card_w // 2, qr_h + 24), "Request via QR or URL:", fill=(100, 116, 139, 255), anchor="mm", font=font_lbl)

                # 完全なURL（手入力できるよう省略なし）
                draw.text((card_w // 2, qr_h + 46), url, fill=(15, 23, 42, 255), anchor="mm", font=font_url)

                card.save(QR_OVERLAY_PATH, "PNG")
                return QR_OVERLAY_PATH
        except Exception as e:
            log_print(f"[Core] Error generating QR overlay image: {e}")
            return None

    def get_image_for_playback(self, image_path, unique_id=None):
        """写真・スライドショー再生用: 1920x1080に正規化し、QR/URL設定に応じてオーバーレイを合成した画像パスを返す"""
        if not image_path or not os.path.exists(image_path):
            return image_path

        overlay_enabled = bool(self.config.get("overlay_qr_enabled", False) or self.config.get("overlay_qr_image", False))
        qr_path = self.generate_qr_overlay_image() if overlay_enabled else None
        has_qr = bool(qr_path and os.path.exists(qr_path))

        # キャッシュキーは「元画像 + 合成するオーバーレイの内容」だけで決まる安定値にする。
        # 以前は呼び出し側の連番 unique_id をキーに混ぜていたため、シャッフル有効時は
        # 曲が変わるたびに同じ写真が別名で再生成され、1曲ごとに写真枚数ぶんの
        # リサイズ＋PNG保存（200枚なら数十秒）が走って送信再開が遅れ、
        # さらにキャッシュファイルが際限なく増え続けていた。
        try:
            src_stat = os.stat(image_path)
            key_parts = [os.path.abspath(image_path), str(int(src_stat.st_mtime)), str(src_stat.st_size),
                         str(overlay_enabled)]
        except OSError:
            key_parts = [os.path.abspath(image_path), str(overlay_enabled)]
        if has_qr:
            try:
                qr_stat = os.stat(qr_path)
                # QRの内容（URL）が変わればキャッシュも作り直す
                key_parts.append(f"{int(qr_stat.st_mtime)}_{qr_stat.st_size}")
            except OSError:
                pass
            key_parts.append(str(self.config.get("overlay_qr_mode", "bottom-right")))
        path_hash = hashlib.md5("_".join(key_parts).encode()).hexdigest()[:12]
        temp_path = os.path.join(IMAGE_CACHE_DIR, f"playback_prep_{path_hash}.png")
        try:
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
                return temp_path
        except OSError:
            pass

        try:
            # 1. 元画像を読み込み、EXIFの向きを補正
            src_img = Image.open(image_path)
            src_img = ImageOps.exif_transpose(src_img)
            if src_img.mode != "RGB":
                src_img = src_img.convert("RGBA")

            # 2. 1920x1080 キャンバスにアスペクト比を維持してレターボックス配置
            target_w, target_h = 1920, 1080
            src_w, src_h = src_img.size
            ratio = min(target_w / src_w, target_h / src_h)
            new_w = max(1, int(src_w * ratio))
            new_h = max(1, int(src_h * ratio))

            img_resized = src_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 255))
            offset_x = (target_w - new_w) // 2
            offset_y = (target_h - new_h) // 2

            if img_resized.mode == "RGBA":
                canvas.paste(img_resized, (offset_x, offset_y), img_resized)
            else:
                canvas.paste(img_resized, (offset_x, offset_y))

            # 3. QRコード・URLカードのオーバーレイ合成（有効な場合）
            if has_qr:
                qr_img = Image.open(qr_path).convert("RGBA")
                qw, qh = qr_img.size
                mode = self.config.get("overlay_qr_mode", "bottom-right")

                if mode == "fullscreen":
                    canvas.alpha_composite(qr_img, dest=(0, 0))
                else:
                    pos_x = max(0, target_w - qw - 25)
                    pos_y = max(0, target_h - qh - 25)
                    canvas.alpha_composite(qr_img, dest=(pos_x, pos_y))

            # 4. キャッシュファイルとして保存。
            # 配信中のFFmpegが concat マニフェスト経由で同じパスを読み直すため、
            # 書きかけのファイルを掴ませないよう一時名で書いてから置換する。
            os.makedirs(IMAGE_CACHE_DIR, exist_ok=True)
            tmp_write_path = f"{temp_path}.{uuid.uuid4().hex[:6]}.part"
            canvas.convert("RGB").save(tmp_write_path, "PNG")
            os.replace(tmp_write_path, temp_path)
            return temp_path
        except Exception as e:
            log_print(f"[Core] Failed to prepare playback image ({image_path}): {e}")
            return image_path

    def _draw_notice_banner(self, img, text):
        """画像の下部に案内バー（半透明ダーク帯＋スカイブルー枠＋テキスト）を合成"""
        try:
            overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay)
            w, h = img.size
            bar_y1 = h - 130
            bar_y2 = h - 50
            draw.rounded_rectangle(
                [(60, bar_y1), (w - 60, bar_y2)],
                radius=14,
                fill=(15, 23, 42, 230),
                outline=(56, 189, 248, 220),
                width=2
            )
            font_notice = get_pil_font(28, bold=True)
            draw.text((w // 2, (bar_y1 + bar_y2) // 2), text, fill="#F8FAFC", anchor="mm", font=font_notice)

            canvas = img.convert("RGBA")
            combined = Image.alpha_composite(canvas, overlay)
            return combined.convert("RGB")
        except Exception as e:
            log_print(f"[Core] Error drawing notice banner: {e}")
            return img

    def generate_standby_image(self, notice_text=None):
        """待機用画面（固定画像またはQRコード & URL付き 1920x1080）を生成して保存"""
        standby_mode = self.config.get("standby_mode", "image")
        # QR案内画面は「このURLへスマホでアクセスして」という画面そのもの。
        # ホスト専用モードでは誰もアクセスできないので、固定画像モードへ倒す。
        if standby_mode == "qr" and not self.is_web_remote_enabled():
            log_print("[Core] Web remote is disabled; standby QR screen falls back to image mode.")
            standby_mode = "image"

        if standby_mode == "image":
            # ==================== 固定画像モード (デフォルト) ====================
            custom_path = self.config.get("standby_image_path", "")
            target_image_path = None
            if custom_path and os.path.exists(custom_path):
                target_image_path = custom_path
            elif os.path.exists(DEFAULT_STANDBY_IMAGE_PATH):
                target_image_path = DEFAULT_STANDBY_IMAGE_PATH

            if target_image_path:
                try:
                    img = Image.open(target_image_path)
                    img = ImageOps.exif_transpose(img)
                    if img.mode != "RGB":
                        img = img.convert("RGBA")
                        canvas = Image.new("RGBA", img.size, (0, 0, 0, 255))
                        img = Image.alpha_composite(canvas, img).convert("RGB")

                    target_w, target_h = 1920, 1080
                    src_w, src_h = img.size
                    ratio = min(target_w / src_w, target_h / src_h)
                    new_w = max(1, int(src_w * ratio))
                    new_h = max(1, int(src_h * ratio))

                    img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    final_img = Image.new("RGB", (target_w, target_h), (0, 0, 0))
                    offset_x = (target_w - new_w) // 2
                    offset_y = (target_h - new_h) // 2
                    final_img.paste(img_resized, (offset_x, offset_y))

                    # overlay_qr_enabled なら QR オーバーレイを合成 (v2.6.0 standby_mode 追加時の考慮漏れ修正)
                    if bool(self.config.get("overlay_qr_enabled", False)):
                        qr_path = self.generate_qr_overlay_image()
                        if qr_path and os.path.exists(qr_path):
                            try:
                                qr_img = Image.open(qr_path).convert("RGBA")
                                canvas = final_img.convert("RGBA")
                                qr_mode = self.config.get("overlay_qr_mode", "bottom-right")
                                if qr_mode == "fullscreen":
                                    canvas.alpha_composite(qr_img, dest=(0, 0))
                                else:
                                    qw, qh = qr_img.size
                                    pos_x = max(0, target_w - qw - 25)
                                    pos_y = max(0, target_h - qh - 25)
                                    canvas.alpha_composite(qr_img, dest=(pos_x, pos_y))
                                final_img = canvas.convert("RGB")
                            except Exception as e:
                                log_print(f"[Core] Error compositing QR overlay on standby image: {e}")

                    if notice_text:
                        final_img = self._draw_notice_banner(final_img, notice_text)

                    final_img.save(STANDBY_IMAGE_PATH, "PNG")
                    return STANDBY_IMAGE_PATH
                except Exception as e:
                    log_print(f"[Core] Error rendering custom standby image ({target_image_path}): {e}")

            # フォールバック (画像が開けない場合、シンプルな待機画面を生成)
            img = Image.new("RGB", (1920, 1080), color="#0F172A")
            draw = ImageDraw.Draw(img)
            font_title = get_pil_font(52, bold=True)
            font_sub = get_pil_font(30, bold=False)
            draw.text((960, 480), "VRC_Media_Streamer", fill="#38BDF8", anchor="mm", font=font_title)
            draw.text((960, 560), "Standby — Queue is Empty", fill="#94A3B8", anchor="mm", font=font_sub)
            # overlay_qr_enabled なら QR オーバーレイを合成
            if bool(self.config.get("overlay_qr_enabled", False)):
                qr_path = self.generate_qr_overlay_image()
                if qr_path and os.path.exists(qr_path):
                    try:
                        qr_img = Image.open(qr_path).convert("RGBA")
                        canvas = img.convert("RGBA")
                        qr_mode = self.config.get("overlay_qr_mode", "bottom-right")
                        if qr_mode == "fullscreen":
                            canvas.alpha_composite(qr_img, dest=(0, 0))
                        else:
                            qw, qh = qr_img.size
                            pos_x = max(0, 1920 - qw - 25)
                            pos_y = max(0, 1080 - qh - 25)
                            canvas.alpha_composite(qr_img, dest=(pos_x, pos_y))
                        img = canvas.convert("RGB")
                    except Exception as e:
                        log_print(f"[Core] Error compositing QR overlay on fallback standby: {e}")

            if notice_text:
                img = self._draw_notice_banner(img, notice_text)

            try:
                img.save(STANDBY_IMAGE_PATH, "PNG")
            except Exception as e:
                log_print(f"[Core] Failed to save fallback standby image: {e}")
            return STANDBY_IMAGE_PATH

        # ==================== QRコード & URL 案内画面モード ====================
        is_tunnel_ready = bool(self.tunnel_raw_url and "trycloudflare.com" in self.tunnel_raw_url)
        is_tunnel_enabled = getattr(self, "enable_tunnel", True)
        port = self.config.get("port", 8000)
        url = self.tunnel_raw_url if is_tunnel_ready else (f"http://{get_local_ip()}:{port}" if not is_tunnel_enabled else f"http://localhost:{port}")
        mode = self.config.get("overlay_qr_mode", "bottom-right")

        width, height = 1920, 1080
        img = Image.new("RGB", (width, height), color="#0F172A") # Dark slate
        draw = ImageDraw.Draw(img)

        # 1. Background accents
        draw.rectangle([(0, 0), (width, 90)], fill="#1E293B")
        draw.rectangle([(0, height - 70), (width, height)], fill="#1E293B")

        font_title = get_pil_font(52, bold=True)
        font_head = get_pil_font(44, bold=True)
        font_sub = get_pil_font(30, bold=False)
        font_url = get_pil_font(34, bold=True)
        font_info = get_pil_font(24, bold=False)
        font_card_url = get_pil_font(16, bold=False)
        font_footer = get_pil_font(22, bold=False)

        draw.text((width // 2, 45), "VRC_Media_Streamer", fill="#38BDF8", anchor="mm", font=font_title)

        if mode == "fullscreen":
            # ==================== フル画面モード (中央大画面QR) ====================
            if is_tunnel_ready:
                draw.text((width // 2, 140), "Queue is Empty — Request a video from your smartphone or browser!", fill="#94A3B8", anchor="mm", font=font_sub)
            elif not is_tunnel_enabled:
                draw.text((width // 2, 140), f"Local Test Mode (http://localhost:{port}) — Add videos via Web!", fill="#34D399", anchor="mm", font=font_sub)
            else:
                draw.text((width // 2, 140), "Connecting to Cloudflare Tunnel... Please wait a moment.", fill="#F59E0B", anchor="mm", font=font_sub)

            try:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=12,
                    border=2,
                )
                qr.add_data(url)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGB")
                
                qr_w, qr_h = qr_img.size
                qr_x = (width - qr_w) // 2
                qr_y = (height - qr_h) // 2 - 15

                card_pad = 22
                draw.rectangle(
                    [(qr_x - card_pad, qr_y - card_pad), (qr_x + qr_w + card_pad, qr_y + qr_h + card_pad)],
                    fill="#FFFFFF"
                )
                img.paste(qr_img, (qr_x, qr_y))
            except Exception as e:
                log_print(f"[Core] Error generating QR code: {e}")

            url_box_y = height - 160
            if is_tunnel_ready:
                draw.text((width // 2, url_box_y), f"Web Request URL: {url}", fill="#F8FAFC", anchor="mm", font=font_url)
                draw.text((width // 2, url_box_y + 45), "Scan this QR code with your phone or visit the URL to add YouTube videos to the queue.", fill="#64748B", anchor="mm", font=font_info)
            elif not is_tunnel_enabled:
                draw.text((width // 2, url_box_y), f"Local Stream URL: {url}/stream.m3u8", fill="#38BDF8", anchor="mm", font=font_url)
                draw.text((width // 2, url_box_y + 45), f"Open {url} in your PC browser to request videos locally.", fill="#64748B", anchor="mm", font=font_info)
            else:
                draw.text((width // 2, url_box_y), "Public URL will appear here once connected...", fill="#94A3B8", anchor="mm", font=font_url)
                draw.text((width // 2, url_box_y + 45), "Establishing secure tunnel to Cloudflare network.", fill="#64748B", anchor="mm", font=font_info)

        else:
            # ==================== 右下コンパクトモード (右下に小さく配置) ====================
            # 画面左側〜中央: リクエスト手順と案内
            draw.text((120, 260), "Now Idle • Queue is Empty", fill="#F8FAFC", anchor="lt", font=font_head)
            draw.text((120, 330), "Add YouTube videos or photos to start streaming!", fill="#94A3B8", anchor="lt", font=font_sub)

            # Web Request URL (大きく完全表記)
            draw.rectangle([(120, 420), (1200, 560)], fill="#1E293B", outline="#334155", width=2)
            draw.text((150, 450), "Web Request URL (手入力・ブラウザ用):", fill="#38BDF8", anchor="lt", font=font_info)
            draw.text((150, 495), url, fill="#FFFFFF", anchor="lt", font=font_url)

            draw.text((120, 610), "📱 Scan the QR code on the right with your smartphone", fill="#CBD5E1", anchor="lt", font=font_info)
            draw.text((120, 655), "🌐 Or enter the Web Request URL above in any browser", fill="#94A3B8", anchor="lt", font=font_info)

            # 画面右下: QRコードカード (完全URL付き)
            try:
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    box_size=7,
                    border=2,
                )
                qr.add_data(url)
                qr.make(fit=True)
                qr_img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF").convert("RGB")
                
                qr_w, qr_h = qr_img.size
                card_w = qr_w + 32
                card_h = qr_h + 80
                card_x = width - card_w - 90
                card_y = (height - card_h) // 2 + 30

                # 白角丸カード
                draw.rounded_rectangle(
                    [(card_x, card_y), (card_x + card_w, card_y + card_h)],
                    radius=14,
                    fill="#FFFFFF",
                    outline="#E2E8F0",
                    width=2
                )
                img.paste(qr_img, (card_x + 16, card_y + 16))

                draw.text((card_x + card_w // 2, card_y + qr_h + 30), "Scan to Request", fill="#64748B", anchor="mm", font=font_card_url)
                draw.text((card_x + card_w // 2, card_y + qr_h + 55), "スマホでスキャン", fill="#0F172A", anchor="mm", font=font_card_url)
            except Exception as e:
                log_print(f"[Core] Error generating compact QR code on standby: {e}")

        draw.text(
            (width // 2, height - 35),
            "🔄 映像が止まった・遅れた時は [Resync] を押してください / If lagging or frozen, please press Resync.",
            fill="#94A3B8",
            anchor="mm",
            font=font_footer
        )

        if notice_text:
            img = self._draw_notice_banner(img, notice_text)

        try:
            img.save(STANDBY_IMAGE_PATH, "PNG")
        except Exception as e:
            log_print(f"[Core] Failed to save standby image: {e}")
        return STANDBY_IMAGE_PATH

    def screen_capture_source_available(self):
        """画面共有の取り込み対象が今この瞬間に掴めるか。"""
        if str(self.config.get("screen_capture_source_type", "display")) != "window":
            return True
        if get_window_rect_by_hwnd(getattr(self, "_screen_capture_hwnd", None)):
            return True
        title = str(self.config.get("screen_capture_window_title", "")).strip()
        if not title:
            return False
        found = find_capture_window(title)
        if found:
            self._screen_capture_hwnd = found.get("hwnd")
            return True
        return False

    def play_standby_loop(self, empty_slideshow=False, screen_unavailable=False):
        """キューが空、スライドショー写真未登録、または画面共有の対象が見つからないときに
        待機画面（QRコード・URL付き静止画）をHLS配信する。

        ★画面共有で対象を見失ったときに「何も送らない」を選んではいけない。
          ワールド側は映像が来ないだけで、利用者からは配信そのものが死んだように見える
          （実機で実際にそうなった）。待機画面を出し続け、対象が戻れば自動で復帰する。
        """
        last_tunnel_url = self.tunnel_raw_url
        if empty_slideshow:
            notice_text = "📷 スライドショー写真が未登録です（Webリモコンから写真をアップロードできます）"
        elif screen_unavailable:
            notice_text = "🖥️ 画面共有: 共有対象のウィンドウが見つかりません（Webリモコンで選び直してください）"
        else:
            notice_text = None

        while self.is_running and not self.skip_event.is_set():
            if screen_unavailable:
                if self.get_playback_mode() != "screen":
                    break
                if self.screen_capture_source_available():
                    break
                self.status = "offline"
                self.status_detail = "画面共有: 対象が見つかりません（待機画面を配信中）"
            elif empty_slideshow:
                if self.get_playback_mode() != "slideshow":
                    break
                with self.photo_lock:
                    if len(self.photo_pool) > 0:
                        break
                self.status = "offline"
                self.status_detail = "Slideshow (No Photos — Standby Notice)"
            else:
                # 実時間ソースのモードへ切り替えたら待機ループから抜ける。
                # ここを slideshow だけにしていると、切り替えても待機画面が
                # 出続けて「切り替わらない」ように見える。
                if self.get_playback_mode() in ("slideshow", "live", "screen"):
                    break
                with self.queue_lock:
                    if len(self.play_queue) > 0:
                        break
                self.status = "offline"
                self.status_detail = "Standby (Waiting for Videos)"

            # 待機画像を生成（最新のトンネルURLと案内テキストを反映）
            self.generate_standby_image(notice_text=notice_text)
            if not os.path.exists(STANDBY_IMAGE_PATH):
                time.sleep(0.5)
                continue

            if not self.ensure_stream_sink():
                time.sleep(1)
                continue

            clock_video = bool(self.config.get("overlay_clock_enabled", False) or self.config.get("overlay_clock_video", False))
            has_clock = bool(clock_video)
            clock_filter = get_clock_filter_for_config(self.config) if has_clock else None

            cmd = [
                get_ffmpeg_cmd(), "-re",
            ]
            cmd.extend([
                "-loop", "1", "-i", os.path.abspath(STANDBY_IMAGE_PATH),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            ])
            if has_clock and clock_filter:
                cmd.extend(["-vf", clock_filter])
            cmd.extend([
                *build_video_encoder_opts(
                    self.get_video_encoder(),
                    v_kbps=1500, max_kbps=1500, buf_kbps=1000,
                    h264_profile="baseline", sc_threshold_zero=True,
                    gop_frames=30, fps=30),
                "-c:a", "aac", "-b:a", "64k",
                "-fflags", "+nobuffer+flush_packets",
                "-flush_packets", "1",
                "-muxdelay", "0",
                "-muxpreload", "0",
                *self._ts_offset_opts(), "-f", "mpegts", "pipe:1"
            ])

            try:
                proc = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, bufsize=0,
                    creationflags=CREATE_NO_WINDOW
                )
            except Exception as e:
                log_print(f"[Player] Error starting Standby sender: {e}")
                time.sleep(1)
                continue

            with self.process_lock:
                self.send_proc = proc

            stop_event = threading.Event()
            threading.Thread(target=self.relay_stream_data,
                             args=(proc, self.current_stdin, stop_event, False), daemon=True).start()
            threading.Thread(target=self.watch_send_proc,
                             args=(proc, stop_event), daemon=True).start()

            url_updated = False
            while self.is_running and not self.skip_event.is_set():
                if self._reload_due():
                    self.reload_stream_event.clear()
                    break

                if empty_slideshow:
                    if self.get_playback_mode() != "slideshow":
                        break
                    with self.photo_lock:
                        if len(self.photo_pool) > 0:
                            break
                else:
                    if self.get_playback_mode() == "slideshow":
                        break
                    with self.queue_lock:
                        if len(self.play_queue) > 0:
                            break

                if self.tunnel_raw_url != last_tunnel_url:
                    last_tunnel_url = self.tunnel_raw_url
                    url_updated = True
                    log_print(f"[Player] Tunnel URL updated ({last_tunnel_url}). Refreshing standby stream with public QR...")
                    break

                time.sleep(0.5)

            stop_event.set()
            with self.process_lock:
                if self.send_proc:
                    kill_proc(self.send_proc)
                self.send_proc = None

            self.accumulated_pts += self.last_stream_duration + 0.1
            log_print(f"[Player] Standby exited. Updated accumulated_pts: {self.accumulated_pts:.2f}s")

            if url_updated:
                time.sleep(0.3)
                continue
            else:
                break

    def queue_monitor_loop(self):
        log_print("[Monitor] Queue monitor started.")
        while self.is_running:
            try:
                current_mode = self.get_playback_mode()

                # ==================== モード0: ライブ音声取り込み ====================
                if current_mode == "live":
                    self.current_video = {"title": "ライブ音声取り込み", "url": "", "duration": 0, "type": "live_audio"}
                    self.skip_event.clear()
                    self.video_done_event.clear()
                    self.status = "streaming"
                    self.status_detail = "Live audio capture"

                    # ★ライブモードには「曲の終わり」が無いので、失敗しても
                    # すぐ同じ分岐へ戻ってくる。デバイスが掴めない状態
                    # （抜かれた・他アプリが排他で握っている）だと ffmpeg が
                    # 即死し、0.1秒間隔でプロセスを生成し続ける暴走になる。
                    # 短命で終わった回数に応じて待ち時間を伸ばす。
                    fail_streak = getattr(self, "_live_audio_fail_streak", 0)
                    live_started_at = time.time()

                    stop_event = self.play_live_audio()
                    if stop_event is None:
                        self._live_audio_fail_streak = min(fail_streak + 1, 10)
                        time.sleep(min(1.0 + fail_streak * 2.0, 15.0))
                        continue

                    while self.is_running and not self.skip_event.is_set():
                        if self.get_playback_mode() != "live":
                            break

                        if self._reload_due():
                            self.reload_stream_event.clear()
                            stop_event.set()
                            with self.process_lock:
                                if self.send_proc:
                                    kill_proc(self.send_proc)
                                self.send_proc = None
                            time.sleep(0.2)
                            break

                        with self.process_lock:
                            proc = self.send_proc
                            h_proc = self.hls_proc

                        if proc and proc.poll() is not None:
                            log_print(f"[Monitor] Live audio sender exited (exit={proc.returncode}).")
                            self.status = "error"
                            self.status_detail = "Live audio sender exited (check capture device)"
                            break

                        if h_proc and h_proc.poll() is not None:
                            log_print("[Monitor] Receiver FFmpeg crashed or exited during live audio.")
                            self.status = "error"
                            self.status_detail = "Offline (Receiver Error)"
                            break

                        time.sleep(0.2)

                    stop_event.set()
                    with self.process_lock:
                        if self.send_proc:
                            kill_proc(self.send_proc)
                        self.send_proc = None

                    self.accumulated_pts += self.last_stream_duration + 0.1
                    if self.skip_event.is_set():
                        self.skip_event.clear()
                    self.video_done_event.clear()

                    # 3秒未満で終わった＝掴めていない。連続したぶんだけ待つ。
                    if (time.time() - live_started_at) < 3.0:
                        self._live_audio_fail_streak = min(fail_streak + 1, 10)
                        time.sleep(min(1.0 + fail_streak * 2.0, 15.0))
                    else:
                        self._live_audio_fail_streak = 0
                        time.sleep(0.1)
                    continue

                # ==================== モード0b: 画面共有 ====================
                if current_mode == "screen":
                    self.current_video = {"title": "画面共有", "url": "", "duration": 0, "type": "screen_capture"}
                    self.skip_event.clear()
                    self.video_done_event.clear()
                    self.status = "streaming"
                    self.status_detail = "Screen capture"

                    fail_streak = getattr(self, "_screen_capture_fail_streak", 0)
                    screen_started_at = time.time()

                    stop_event = self.play_screen_capture()
                    if stop_event is None:
                        self._screen_capture_fail_streak = min(fail_streak + 1, 10)
                        # ★無映像のまま放置しない。待機画面を出し続け、対象が
                        #   戻ってきたら自動で復帰する（この関数は対象が掴めた
                        #   時点で抜ける）。実機で「配信自体が死ぬ」と見えたのは
                        #   ここで何も送っていなかったため。
                        self.current_video = {"title": "画面共有（対象を待機中）", "url": "",
                                              "duration": 0, "type": "screen_capture"}
                        self.play_standby_loop(screen_unavailable=True)
                        time.sleep(min(0.5 + fail_streak * 0.5, 5.0))
                        continue

                    while self.is_running and not self.skip_event.is_set():
                        if self.get_playback_mode() != "screen":
                            break

                        if self._reload_due():
                            self.reload_stream_event.clear()
                            stop_event.set()
                            with self.process_lock:
                                if self.send_proc:
                                    kill_proc(self.send_proc)
                                self.send_proc = None
                            time.sleep(0.2)
                            break

                        with self.process_lock:
                            proc = self.send_proc
                            h_proc = self.hls_proc

                        if proc and proc.poll() is not None:
                            log_print(f"[Monitor] Screen capture sender exited (exit={proc.returncode}).")
                            self.status = "error"
                            self.status_detail = "Screen capture sender exited"
                            break

                        if h_proc and h_proc.poll() is not None:
                            log_print("[Monitor] Receiver FFmpeg crashed or exited during screen capture.")
                            self.status = "error"
                            self.status_detail = "Offline (Receiver Error)"
                            break

                        time.sleep(0.2)

                    stop_event.set()
                    with self.process_lock:
                        if self.send_proc:
                            kill_proc(self.send_proc)
                        self.send_proc = None

                    self.accumulated_pts += self.last_stream_duration + 0.1
                    if self.skip_event.is_set():
                        self.skip_event.clear()
                    self.video_done_event.clear()

                    if (time.time() - screen_started_at) < 3.0:
                        self._screen_capture_fail_streak = min(fail_streak + 1, 10)
                        time.sleep(min(1.0 + fail_streak * 2.0, 15.0))
                    else:
                        self._screen_capture_fail_streak = 0
                        time.sleep(0.1)
                    continue

                # ==================== モード1: 写真スライドショー ====================
                if current_mode == "slideshow":
                    photos = self.get_photos()
                    if not photos:
                        self.current_video = None
                        self.play_standby_loop(empty_slideshow=True)
                        time.sleep(0.3)
                        continue

                    # 写真を順番（またはシャッフル）に取得
                    with self.photo_lock:
                        if self.config.get("shuffle", False):
                            next_photo = random.choice(self.photo_pool)
                        else:
                            self.slideshow_index %= len(self.photo_pool)
                            next_photo = self.photo_pool[self.slideshow_index]
                            self.slideshow_index = (self.slideshow_index + 1) % len(self.photo_pool)

                    log_print(f"[Monitor] Showing Photo in slideshow: {next_photo.get('title')}")
                    self.current_video = next_photo
                    self.skip_event.clear()
                    self.video_done_event.clear()
                    self.status = "streaming"
                    self.status_detail = f"Showing Photo: {next_photo.get('title')}"

                    stop_event = self.play_image(next_photo)
                    if stop_event is None:
                        log_print("[Monitor] Failed to display photo. Skipping to next.")
                        self.status = "error"
                        self.status_detail = "Failed to load photo"
                        time.sleep(1)
                        continue

                    elapsed = 0.0
                    duration_for_log = float(self.config.get("image_display_duration", 15))
                    while self.is_running and not self.skip_event.is_set():
                        # モード切替検知
                        if self.get_playback_mode() != "slideshow":
                            break

                        # 設定変更・写真更新ホットリロード要求
                        if self._reload_due():
                            self.reload_stream_event.clear()
                            log_print("[Monitor] Hot-reloading slideshow photo stream...")
                            stop_event.set()
                            with self.process_lock:
                                if self.send_proc:
                                    kill_proc(self.send_proc)
                                self.send_proc = None
                            time.sleep(0.2)
                            break

                        auto_advance = bool(self.config.get("image_auto_advance", True))
                        if not self.image_paused and auto_advance:
                            elapsed += 0.2
                            duration = float(self.config.get("image_display_duration", 15))
                            if elapsed >= duration:
                                log_print(f"[Monitor] Photo display time elapsed ({duration}s).")
                                break

                        time.sleep(0.2)
                        with self.process_lock:
                            proc = self.send_proc
                            h_proc = self.hls_proc
                        if proc and proc.poll() is not None:
                            if elapsed < duration_for_log:
                                log_print(
                                    f"[Monitor] WARNING: Photo sender exited after {elapsed:.1f}s "
                                    f"(expected {duration_for_log}s, exit={proc.returncode}). "
                                    f"Photo: {next_photo.get('title')}"
                                )
                            break
                        if h_proc and h_proc.poll() is not None:
                            log_print("[Monitor] Receiver FFmpeg crashed or exited during photo.")
                            self.status = "error"
                            self.status_detail = "Offline (Receiver Error)"
                            break

                    stop_event.set()
                    with self.process_lock:
                        proc = self.send_proc
                        if proc:
                            kill_proc(proc)
                        self.send_proc = None

                    self.accumulated_pts += self.last_stream_duration + 0.1
                    log_print(f"[Monitor] Photo finished. Updated accumulated_pts: {self.accumulated_pts:.2f}s")

                    if self.skip_event.is_set():
                        log_print("[Monitor] Photo skipped.")
                        self.skip_event.clear()
                    self.video_done_event.clear()
                    time.sleep(0.1)
                    continue

                # ==================== モード2 & 3: 通常動画 / ラジオBGM ====================
                next_item = None
                with self.queue_lock:
                    if self.play_queue:
                        if self.config.get("shuffle", False):
                            idx = random.randrange(len(self.play_queue))
                            next_item = self.play_queue.pop(idx)
                        else:
                            next_item = self.play_queue.pop(0)

                if not next_item:
                    self.current_video = None
                    self.status = "offline"
                    self.status_detail = "Standby (Waiting for Videos)"
                    self.play_standby_loop(empty_slideshow=False)
                    time.sleep(0.3)
                    continue

                # 履歴に追加 (最大20件)
                with self.queue_lock:
                    self.history_stack.append(next_item)
                    if len(self.history_stack) > 20:
                        self.history_stack.pop(0)

                is_radio = (current_mode == "radio")
                log_print(f"[Monitor] Loading: {next_item.get('title')} (is_radio: {is_radio})")
                self.current_video = next_item
                self.skip_event.clear()
                self.video_done_event.clear()

                self.status = "buffering"
                self.status_detail = f"Loading {'[Radio]' if is_radio else ''}: {next_item.get('title')}..."

                if is_radio:
                    stop_event = self.play_radio(next_item)
                else:
                    stop_event = self.play_video(next_item)

                if stop_event is None:
                    log_print("[Monitor] Failed to play. Skipping to next.")
                    self.status = "error"
                    self.status_detail = "Failed to load stream"
                    time.sleep(1)
                    continue

                self.status = "streaming"
                self.status_detail = "Active (Radio BGM)" if is_radio else "Active (Streaming)"

                # 次の曲のバックグラウンド先読み（プリフェッチ）を開始
                with self.queue_lock:
                    next_queued = self.play_queue[0] if self.play_queue else None
                if next_queued:
                    threading.Thread(target=self.prefetch_item, args=(next_queued,), daemon=True).start()

                # 終了 or スキップを待つ (ホットリロード対応)
                while self.is_running and not self.skip_event.is_set():
                    # 再生モードがスライドショーへ切り替わった場合
                    if self.get_playback_mode() == "slideshow":
                        log_print("[Monitor] Switched to slideshow mode during video playback. Transitioning...")
                        break

                    # 設定変更による即時ホットリロード要求
                    if self._reload_due():
                        self.reload_stream_event.clear()
                        seek = max(0, time.time() - (self.current_video_start_time or time.time()))
                        is_radio_now = (self.get_playback_mode() == "radio")
                        log_print(f"[Monitor] Hot-reloading active stream (radio={is_radio_now}) with updated settings at seek={int(seek)}s...")
                        stop_event.set()
                        with self.process_lock:
                            if self.send_proc:
                                kill_proc(self.send_proc)
                            self.send_proc = None
                        time.sleep(0.1)
                        if is_radio_now:
                            stop_event = self.play_radio(next_item, seek_seconds=seek)
                        else:
                            stop_event = self.play_video(next_item, seek_seconds=seek)
                        if stop_event is None:
                            break

                    with self.process_lock:
                        h_proc = self.hls_proc
                    if h_proc and h_proc.poll() is not None:
                        log_print("[Monitor] Receiver FFmpeg crashed or exited.")
                        self.status = "error"
                        self.status_detail = "Offline (Receiver Error)"
                        break

                    item_dur = float(next_item.get("duration") or 0)
                    elapsed_play = (time.time() - self.current_video_start_time) if self.current_video_start_time else 0

                    # 送信側がデータ送信完了（先読み完了）した場合
                    if self.video_done_event.is_set():
                        if item_dur > 0:
                            if elapsed_play >= item_dur:
                                log_print(f"[Monitor] Video playback finished naturally ({int(elapsed_play)}s / {int(item_dur)}s).")
                                break
                        else:
                            # duration不明の場合は即座に完了
                            break

                    # 曲の長さを大幅に超過した際のタイムアウト・フェイルセーフ
                    if item_dur > 0 and elapsed_play > item_dur + 10:
                        log_print(f"[Monitor] Video reached duration limit ({int(elapsed_play)}s / {int(item_dur)}s). Finishing.")
                        break

                    self.video_done_event.wait(timeout=0.3)

                # 自然終了（スキップではない）の場合、最後のバッファをプレイヤーが再生しきるまで設定秒数待機
                wait_secs = self.config.get("video_transition_wait_seconds", 1)
                if not self.skip_event.is_set() and self.is_running and wait_secs > 0:
                    log_print(f"[Monitor] Waiting {wait_secs} seconds for player buffer completion...")
                    self.status = "finishing"
                    self.status_detail = "Finishing Video..."
                    self.skip_event.wait(timeout=wait_secs)

                stop_event.set()
                with self.process_lock:
                    proc = self.send_proc
                    if proc:
                        kill_proc(proc)
                    self.send_proc = None

                # 動画再生時間を累積PTSに加算
                self.accumulated_pts += self.last_stream_duration + 0.1
                log_print(f"[Monitor] Video finished. Updated accumulated_pts: {self.accumulated_pts:.2f}s")

                # ループ再生が有効な場合、終了した動画をキューの末尾に再追加
                if self.config.get("loop_queue", False) and next_item:
                    with self.queue_lock:
                        self.play_queue.append(next_item)
                    log_print(f"[Monitor] Loop queue: re-added '{next_item.get('title')}' to end of queue.")

                if self.skip_event.is_set():
                    log_print("[Monitor] Video skipped.")
                    self.skip_event.clear()
                self.video_done_event.clear()

            except Exception as e:
                log_print(f"[Monitor] Exception in queue loop: {e}")
                self.status = "error"
                self.status_detail = "Offline (Monitor Error)"
                time.sleep(1)

    def start_tunnel(self):
        if not getattr(self, "enable_tunnel", True):
            port = self.config.get("port", 8000)
            self.tunnel_raw_url = f"http://localhost:{port}"
            self.tunnel_url = f"http://localhost:{port}/stream.m3u8"
            log_print(f"[Tunnel] Tunnel is DISABLED. Using local URL: {self.tunnel_url}")
            return None

        log_print("Starting Cloudflare Quick Tunnel...")
        if not os.path.exists(CLOUDFLARED_EXE):
            log_print(f"Error: cloudflared.exe not found at {CLOUDFLARED_EXE}")
            self.tunnel_url = "cloudflared.exe missing!"
            self.tunnel_raw_url = ""
            return None

        port = self.config.get("port", 8000)
        cmd = [os.path.abspath(CLOUDFLARED_EXE), "tunnel", "--url", f"http://localhost:{port}"]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW
            )
            with self.process_lock:
                self.tunnel_proc = proc
        except Exception as e:
            log_print(f"Error executing cloudflared: {e}")
            self.tunnel_url = "Launch error!"
            self.tunnel_raw_url = ""
            return None

        def read_tunnel_output():
            established = False
            while self.is_running:
                line = proc.stderr.readline()
                if not line:
                    break
                m = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line)
                if m:
                    self.tunnel_raw_url = m.group(0)
                    self.tunnel_url = self.tunnel_raw_url + "/stream.m3u8"
                    log_print(f"Cloudflare Tunnel Established: {self.tunnel_url}")
                    established = True
                    
            if not established and self.is_running:
                self.tunnel_url = "Tunnel failed to connect."

        threading.Thread(target=read_tunnel_output, daemon=True).start()
        return proc

    def start_background_tasks(self):
        """トンネル、常駐シンクプロセス、配信先ウォッチドッグ、キュー監視のバックグラウンド開始"""
        self.ensure_stream_sink()
        self.start_tunnel()
        t = threading.Thread(target=self.queue_monitor_loop, daemon=True)
        t.start()
        threading.Thread(target=self.destination_watchdog_loop, daemon=True).start()

    def shutdown(self):
        log_print("[Core] Shutting down StreamerCore...")
        self.is_running = False
        with self.process_lock:
            if self.current_stdin:
                try:
                    self.current_stdin.close()
                except Exception:
                    pass
                self.current_stdin = None
            kill_proc(self.send_proc)
            kill_proc(self.hls_proc)
            kill_proc(self.tunnel_proc)
            self.send_proc = None
            self.hls_proc = None
            self.tunnel_proc = None
        
        # プロセス終了・ファイルロック解除を確実に待ってから HLS ディレクトリ内を完全消去
        time.sleep(0.5)
        self.clean_hls_dir(all_files=True, preserve_images=False)
        log_print("[Core] HLS output directory completely cleaned.")
        log_print("[Core] Shutdown complete.")
