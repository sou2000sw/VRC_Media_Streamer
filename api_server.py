import os
import sys
import re
import json
import http.server
import socketserver
import threading
import time
import ipaddress
import hmac
from urllib.parse import urlparse, parse_qs
from streamer_core import BASE_PATH, HLS_DIR, StreamerCore, log_print, is_video_url_or_file, is_image_url_or_file, enumerate_dshow_audio_devices, enumerate_capture_displays, enumerate_capture_windows
from version import APP_VERSION

def _ui_html_candidates():
    """
    ui/index.html の探索候補を優先順で返す。

    1. EXE と同じフォルダ  … 利用者が UI を差し替えたい場合の上書き先
    2. スクリプトと同じ場所 … 開発時（リポジトリ直下の ui/）
    3. カレントディレクトリ
    4. BASE_PATH           … PyInstaller onefile に同梱された既定 UI (sys._MEIPASS)
    """
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.getcwd())
    roots.append(BASE_PATH)

    candidates = []
    seen = set()
    for root in roots:
        if not root or root in seen:
            continue
        seen.add(root)
        candidates.append(os.path.join(root, "ui", "index.html"))
        candidates.append(os.path.join(root, "plugin", "ui", "index.html"))
    return candidates


def get_ui_html():
    """
    Web リモコン UI (ui/index.html) を読み込む。

    v2.6.0 以降、UI の正本は ui/index.html ただ一つ。api_server.py 側に UI を複製すると
    必ずどちらかが腐るため（実際 v2.6.0 の内蔵テンプレートは <body> ごと欠落して配信されていた）、
    内蔵の複製は持たない。正本が見つからない場合は「壊れた UI」ではなく、
    原因と復旧手順を示す診断ページを返す（fail-closed）。
    """
    for path in _ui_html_candidates():
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception as e:
                log_print(f"[APIServer] Failed to read UI asset {path}: {e}")
    log_print("[APIServer] UI asset 'ui/index.html' not found. Serving diagnostic page.")
    return UI_MISSING_TEMPLATE


# --- Web リモコンの同梱アセット (ui/vendor/) ---------------------------------
# Tailwind / RemixIcon / hls.js は v2.9.4 まで CDN 直リンクだった。
# ホストPCがオフライン、あるいは CDN が塞がれた回線（社内・学校・一部モバイル）では
# UI が「素の HTML」になって操作不能になるため、同梱ファイルから配信する。
# 拡張子は許可制。ui/ 配下を何でも配ると index.html 以外の同梱物まで露出する。
VENDOR_ALLOWED_TYPES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}
# gzip して意味があるのはテキストだけ。woff2 は既に圧縮済みで、掛け直すと逆に増える。
VENDOR_GZIP_TYPES = (".js", ".css")
_VENDOR_CACHE = {}          # {abs_path: (mtime, size, raw_bytes, gzip_bytes|None)}
_VENDOR_CACHE_LOCK = threading.Lock()


def _ui_vendor_path(rel_name):
    """ui/vendor/<rel_name> の実体パスを返す（見つからなければ None）。

    探索順は _ui_html_candidates() と同じ思想（EXE 隣 → スクリプト隣 → cwd → 同梱）。
    UI を差し替えたい利用者が index.html だけ置き換えると vendor が食い違うため、
    index.html を採用したフォルダの vendor を優先する。
    """
    if not rel_name or "/" in rel_name or "\\" in rel_name or rel_name.startswith("."):
        return None
    if os.path.splitext(rel_name)[1].lower() not in VENDOR_ALLOWED_TYPES:
        return None

    for html_path in _ui_html_candidates():
        candidate = os.path.join(os.path.dirname(html_path), "vendor", rel_name)
        if os.path.isfile(candidate):
            # 念のため、正規化後も vendor ディレクトリ配下に留まっていることを確認する。
            vendor_root = os.path.realpath(os.path.join(os.path.dirname(html_path), "vendor"))
            real = os.path.realpath(candidate)
            if os.path.commonpath([vendor_root, real]) == vendor_root:
                return real
    return None


def _app_asset_path(rel_name):
    """assets/<rel_name> の実体パスを返す（見つからなければ None）。

    アプリ自身の画像（アイコン等）。第三者ライブラリの ui/vendor/ とは出所が違うので
    置き場も配信経路も分けてある。探索順は UI と同じ思想
    （EXE 隣 → スクリプト隣 → cwd → PyInstaller 同梱）。
    """
    if not rel_name or "/" in rel_name or "\\" in rel_name or rel_name.startswith("."):
        return None

    roots = []
    if getattr(sys, "frozen", False):
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    roots.append(os.getcwd())
    roots.append(BASE_PATH)

    for root in roots:
        if not root:
            continue
        candidate = os.path.join(root, "assets", rel_name)
        if os.path.isfile(candidate):
            return candidate
    return None


def read_vendor_asset(rel_name, accept_gzip=False):
    """同梱アセットを (bytes, content_type, encoding) で返す。無ければ None。

    毎リクエストで 450KB を読み直す/圧縮し直すのは無駄なので、mtime+size をキーに
    メモリキャッシュする（ファイルを差し替えたら自動で読み直す）。
    """
    path = _ui_vendor_path(rel_name)
    if not path:
        return None
    ext = os.path.splitext(path)[1].lower()
    try:
        st = os.stat(path)
        key = path
        with _VENDOR_CACHE_LOCK:
            cached = _VENDOR_CACHE.get(key)
            if cached and cached[0] == st.st_mtime and cached[1] == st.st_size:
                _, _, raw, gz = cached
            else:
                with open(path, "rb") as f:
                    raw = f.read()
                gz = None
                if ext in VENDOR_GZIP_TYPES:
                    import gzip
                    gz = gzip.compress(raw, 6)
                    if len(gz) >= len(raw):
                        gz = None
                _VENDOR_CACHE[key] = (st.st_mtime, st.st_size, raw, gz)
    except Exception as e:
        log_print(f"[APIServer] Failed to read vendor asset {path}: {e}")
        return None

    if accept_gzip and gz is not None:
        return gz, VENDOR_ALLOWED_TYPES[ext], "gzip"
    return raw, VENDOR_ALLOWED_TYPES[ext], None


UI_MISSING_TEMPLATE = """<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VRC_Media_Streamer - UI アセット未検出</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; padding:2rem 1.25rem; background:#121214; color:#e4e4e7;
         font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans JP",sans-serif;
         line-height:1.7; }
  main { max-width:44rem; margin:0 auto; }
  h1 { font-size:1.25rem; margin:0 0 .25rem; color:#f43f5e; }
  p  { color:#a1a1aa; font-size:.9rem; }
  ol { color:#a1a1aa; font-size:.9rem; padding-left:1.2rem; }
  code { background:#202024; border:1px solid #27272a; border-radius:.25rem;
         padding:.1rem .35rem; font-size:.85em; color:#38bdf8; }
  .card { background:#18181b; border:1px solid #27272a; border-radius:.6rem;
          padding:1rem 1.25rem; margin-top:1.25rem; }
  .url { display:block; margin-top:.4rem; word-break:break-all; color:#38bdf8;
         font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:.85rem; }
</style>
</head>
<body>
<main>
  <h1>Web リモコン UI を読み込めませんでした</h1>
  <p>UI の正本である <code>ui/index.html</code> が見つかりません。
     配信機能（HLS）自体は正常に稼働しています。</p>

  <div class="card">
    <strong>VRChat / プレイヤー用 ストリーム URL</strong>
    <span class="url">__TUNNEL_STREAM_URL__</span>
  </div>

  <div class="card">
    <strong>復旧手順</strong>
    <ol>
      <li><code>ui/index.html</code> を <code>VRC_Media_Streamer.exe</code> と同じフォルダの
          <code>ui/</code> に配置する（フォルダごと）。</li>
      <li>ソースからビルドした場合は
          <code>python build_exe.py</code> で再ビルドする（UI は EXE に同梱されます）。</li>
      <li>それでも直らない場合は起動ログの
          <code>[APIServer] UI asset ... not found</code> 行を確認してください。</li>
    </ol>
  </div>
</main>
</body>
</html>
"""

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

RATE_LIMIT_LOCK = threading.Lock()
LAST_QUEUE_REQUESTS = {} # {ip: timestamp} URL追加用（最小間隔方式）
QUEUE_RATE_LIMIT_SECONDS = 2.5
UPLOAD_REQUEST_TIMES = {} # {ip: [timestamp, ...]} 写真アップロード用（時間枠内の合計枚数方式）
UPLOAD_RATE_LIMIT_BURST = 20    # 一括アップロードで許可する枚数
UPLOAD_RATE_LIMIT_WINDOW = 60.0 # 上記枚数を数える時間枠（秒）
# --- Webリモコン認証（PIN/パスワード）のブルートフォース対策 ---
# PIN は4桁で使われることが多く、対策がないと総当たりで数分〜十数分で破られる。
# 「IP単位の指数バックオフ」で個別の連打を止め、「全体スロットル」でIPを
# 使い捨てにする分散型の総当たりも頭打ちにする（片方だけでは防げない）。
AUTH_FAIL_LOCK = threading.Lock()
AUTH_FAILURES = {}                  # {ip: {"count": int, "blocked_until": float, "last": float}}
AUTH_FAIL_THRESHOLD = 5             # 連続失敗がこの回数に達したらロックアウト開始
AUTH_FAIL_BASE_LOCK_SECONDS = 30    # 初回ロック秒数（以降、失敗のたびに倍）
AUTH_FAIL_MAX_LOCK_SECONDS = 900    # ロック上限（15分）
AUTH_FAIL_FORGET_SECONDS = 900      # 最終失敗からこの時間が経てば失敗履歴を忘れる
GLOBAL_AUTH_FAIL_WINDOW = 60.0      # 全体スロットルの集計窓（秒）
GLOBAL_AUTH_FAIL_LIMIT = 100        # 集計窓内に許す全IP合計の失敗回数
GLOBAL_AUTH_LOCK_SECONDS = 60       # 全体ロックの継続秒数
GLOBAL_AUTH_FAILS = []              # 直近の失敗時刻（全IP合計）
GLOBAL_AUTH_BLOCKED_UNTIL = 0.0

MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_UPLOAD_BODY_BYTES = 20 * 1024 * 1024 # 20MB
MAX_VIDEO_UPLOAD_BODY_BYTES = 200 * 1024 * 1024 # 200MB

SENSITIVE_BODY_KEYS = ("topaz_stream_key", "generic_rtmp_key", "web_password", "password")


def redact_sensitive(payload):
    """ログへ出す前に機密値を伏せる。

    ストリームキーは「知っていれば誰でもそのキーで配信を投稿できる」ため、
    パスワードと同格に扱う必要がある。ログファイルは配布物と一緒に
    第三者へ渡ることがあるので、平文で残してはいけない。
    """
    if not isinstance(payload, dict):
        return payload
    safe = {}
    for key, value in payload.items():
        if key in SENSITIVE_BODY_KEYS and value:
            safe[key] = "***redacted***"
        else:
            safe[key] = value
    return safe


def parse_multipart_file(body_bytes, content_type_header):
    """multipart/form-data からファイルバイナリとファイル名を取得"""
    m = re.search(r'boundary=([^;]+)', content_type_header)
    if not m:
        return None, None
    boundary = m.group(1).strip().strip('"').encode("utf-8")
    parts = body_bytes.split(b"--" + boundary)
    for part in parts:
        if b"filename=" in part:
            header_end = part.find(b"\r\n\r\n")
            if header_end == -1:
                header_end = part.find(b"\n\n")
                if header_end == -1:
                    continue
                body_start = header_end + 2
            else:
                body_start = header_end + 4
            headers_part = part[:header_end].decode("utf-8", errors="ignore")
            m_fn = re.search(r'filename="([^"]+)"', headers_part)
            filename = m_fn.group(1) if m_fn else "photo.jpg"
            file_data = part[body_start:].rstrip(b"\r\n--")
            return file_data, filename
    return None, None

# ホスト専用モード（enable_web_remote:false）で、ゲストに返す案内ページ。
# トンネル経由で不特定多数が見るため、バージョン・機器名・URLは一切載せない。
# 同梱アセット (/vendor/*) も無効時は塞ぐので、CSSはここに直書きする。
HOST_ONLY_NOTICE_HTML = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>403 Forbidden</title>
<style>
  html,body{height:100%;margin:0}
  body{display:flex;align-items:center;justify-content:center;
       background:#0F172A;color:#E2E8F0;
       font-family:system-ui,-apple-system,"Segoe UI","Hiragino Kaku Gothic ProN",sans-serif}
  .card{max-width:30rem;padding:2rem;text-align:center;line-height:1.7}
  h1{margin:0 0 1rem;font-size:1.15rem;color:#38BDF8}
  p{margin:.4rem 0;font-size:.9rem;color:#94A3B8}
</style></head>
<body><div class="card">
<h1>&#x1F6E1;&#xFE0F; リモート操作は無効になっています</h1>
<p>この配信はホスト専用モードで動作しており、ホストPC以外からの操作は受け付けていません。</p>
<p>映像・音声の配信は通常どおり続いています。</p>
</div></body></html>
"""


class APIAndHLSHandler(http.server.SimpleHTTPRequestHandler):
    # MIMEタイプの明示（Windows等で .ts が text/plain になる問題やプレイヤー互換性を防止）
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }

    def __init__(self, *args, streamer_core=None, shutdown_callback=None, **kwargs):
        self.streamer_core = streamer_core
        self.shutdown_callback = shutdown_callback
        super().__init__(*args, directory=HLS_DIR, **kwargs)

    def _self_origins(self):
        """自分自身のオリジンとして認めるURLの集合"""
        port = self.streamer_core.config.get("port", 8000) if self.streamer_core else 8000
        origins = set()
        for host in ("127.0.0.1", "localhost", "[::1]"):
            origins.add(f"http://{host}:{port}")

        from streamer_core import get_local_ip
        local_ip = get_local_ip()
        origins.add(f"http://{local_ip}:{port}")

        raw_host = self.headers.get("Host", "")
        if raw_host:
            origins.add(f"http://{raw_host}")
            origins.add(f"https://{raw_host}")

        tunnel = (self.streamer_core.tunnel_raw_url if self.streamer_core else "") or ""
        if tunnel:
            origins.add(tunnel.rstrip("/"))
        return origins

    def _origin_is_self(self):
        """
        CSRF対策: Originヘッダが自分自身のオリジンか判定。
        # Origin なし（curl / Python requests / Node.js 等のネイティブ/サーバサイドクライアント）とみなして許可する。
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin.rstrip("/") in self._self_origins()

    def _host_header_is_safe(self):
        """
        DNSリビンディング対策: Hostヘッダがドメイン名の場合は拒否する。
        攻撃者ドメインを 127.0.0.1 に解決させる手口はHostが独自ドメインになるため弾ける。
        """
        raw_host = self.headers.get("Host", "")
        if not raw_host:
            return True
        hostname = urlparse(f"http://{raw_host}").hostname or ""
        hostname = hostname.lower()
        if hostname in ("localhost", ""):
            return True
        try:
            ipaddress.ip_address(hostname)
            return True  # IPリテラル直打ちはリビンディングの対象外
        except ValueError:
            pass
        tunnel = (self.streamer_core.tunnel_raw_url if self.streamer_core else "") or ""
        tunnel_host = (urlparse(tunnel).hostname or "").lower() if tunnel else ""
        return bool(tunnel_host) and hostname == tunnel_host

    def is_local_request(self):
        """
        ホストPC本人（＝停止・全消去などの破壊的操作を許してよい相手）か判定。

        既定はループバックのみ。トンネル無効時に同一LAN全体をホスト扱いしていた挙動は、
        同じWi-Fi上の任意の端末が /api/shutdown や clear_queue を叩けてしまうため撤廃した。
        従来どおりLAN内をホスト扱いしたい場合は config.json の
        "trust_lan_clients": true で明示的にオプトインする。
        なお LAN 端末は引き続き「ゲスト」として接続でき、
        allow_web_queue_add / allow_web_queue_edit / allow_web_playback_control の
        範囲でスマホからの追加・操作が可能（＝QR共有のワークフローは維持される）。
        """
        if "cf-connecting-ip" in self.headers or "x-forwarded-for" in self.headers:
            return False
        client_ip = self.client_address[0] if self.client_address else ""
        
        # ループバック判定
        is_loopback = client_ip in ("127.0.0.1", "::1", "localhost")
        
        # プライベートLAN判定 (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
        is_private_lan = False
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            is_private_lan = ip_obj.is_private or ip_obj.is_loopback
        except Exception:
            pass

        # 同一LANをホスト扱いするかどうかは明示的なオプトイン設定のみで決まる
        trust_lan = bool(
            self.streamer_core
            and self.streamer_core.config.get("trust_lan_clients", False)
        )

        if not is_loopback and not (trust_lan and is_private_lan):
            return False

        if not self._origin_is_self():
            log_print(f"[APIServer] Rejected local privilege: cross-site Origin {self.headers.get('Origin')!r}")
            return False
        if not self._host_header_is_safe():
            log_print(f"[APIServer] Rejected local privilege: suspicious Host {self.headers.get('Host')!r}")
            return False
        return True

    def web_remote_enabled(self):
        """Webリモコン（ゲスト向けの画面とAPI）を開いているか。タスク21。

        未設定は True。既存の config.json にはこのキーが無く、
        fail-closed にすると更新しただけで全員のリモコンが黙って死ぬ。
        「閉じる」は利用者が明示的に選んだときだけ。
        """
        if not self.streamer_core:
            return True
        return bool(self.streamer_core.config.get("enable_web_remote", True))

    def _client_is_strict_loopback(self):
        """ホスト専用モードで唯一通す相手＝ホストPC本人か。

        is_local_request() をそのまま使わないのは trust_lan_clients を見ないため。
        「ホスト専用」を選んだ利用者にとって、同一LANの別端末も"他人"である。

        中継ヘッダの確認は必須。cloudflared はこのPCの 127.0.0.1 へ繋いでくるので、
        接続元IPだけを見るとトンネル経由の全員がホスト扱いになり、ゲートが素通りする。
        """
        if "cf-connecting-ip" in self.headers or "x-forwarded-for" in self.headers:
            return False
        client_ip = self.client_address[0] if self.client_address else ""
        if client_ip not in ("127.0.0.1", "::1", "localhost"):
            return False
        # ホスト本人のブラウザでも、外部サイトに埋め込まれた状態からの呼び出しは通さない
        if not self._origin_is_self():
            return False
        if not self._host_header_is_safe():
            return False
        return True

    def _is_media_path(self, path):
        """VRChatのプレイヤーが再生に使うファイルか（ホスト専用モードでも開けておく対象）。

        許可リスト方式。HLS_DIR には写真プール (/images/*) も同居しており、
        「静的ファイルなら通す」にすると共有済みの写真まで外へ出る。
        """
        return path.lower().endswith((".m3u8", ".ts", ".m4s", ".mp4", ".aac"))

    def _wants_ui_document(self, path, accept_header):
        """ブラウザがリモコン画面（HTML）を開こうとしているか。

        /stream.m3u8 はアドレスバー直打ちのときだけ画面を返し、
        プレイヤー・XHR からのリクエストにはマニフェストを返す。
        """
        if path == "/":
            return True
        if path != "/stream.m3u8":
            return False
        return (
            "text/html" in accept_header
            and self.headers.get("Sec-Fetch-Dest", "") in ("document", "")
            and self.headers.get("Sec-Fetch-Mode", "") in ("navigate", "")
            and not self.headers.get("X-Requested-With")
            and "video" not in accept_header
            and "application/vnd.apple.mpegurl" not in accept_header
            and "application/x-mpegurl" not in accept_header
        )

    def reject_if_web_remote_disabled(self, path, accept_header=""):
        """ホスト専用モードの関門。塞いだら True を返す（呼び出し側は即 return）。

        認証・権限判定より前に置くこと。閉じているなら、パスワードが合っているかも、
        allow_web_* で何が許されているかも、そもそも問う必要がない。
        """
        if self.web_remote_enabled():
            return False
        if self._client_is_strict_loopback():
            return False
        # 配信そのものは止めない。VRChatのプレイヤーは認証ヘッダを付けられず、
        # ここを塞ぐと「リモコンを切ったら映像も消えた」になる。
        if self._is_media_path(path) and not self._wants_ui_document(path, accept_header):
            return False

        if self._wants_ui_document(path, accept_header):
            content = HOST_ONLY_NOTICE_HTML.encode("utf-8")
            self.send_response(403)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return True

        self.send_json_response(403, {
            "success": False,
            "error": "Forbidden: the web remote is disabled by the host.",
            "message": "Forbidden: the web remote is disabled by the host.",
            "enable_web_remote": False
        })
        return True

    def check_rate_limit(self):
        """
        連投（DoS・スパム）防止レートリミット。
        キーにはCloudflareが上書きする CF-Connecting-IP か接続元IPのみを使う。
        X-Forwarded-For はクライアントが自由に詐称できるためキーに含めない。
        """
        client_ip = self._client_rate_key()
        now = time.time()
        with RATE_LIMIT_LOCK:
            last_time = LAST_QUEUE_REQUESTS.get(client_ip, 0)
            if now - last_time < QUEUE_RATE_LIMIT_SECONDS:
                return False
            LAST_QUEUE_REQUESTS[client_ip] = now
            if len(LAST_QUEUE_REQUESTS) > 1000:
                for k in list(LAST_QUEUE_REQUESTS.keys()):
                    if now - LAST_QUEUE_REQUESTS[k] > 3600:
                        del LAST_QUEUE_REQUESTS[k]
            return True

    def check_upload_rate_limit(self):
        """
        写真アップロード用のレートリミット。

        URL追加と違い「複数枚をまとめて選ぶ」のが通常の使い方なので、最小間隔方式
        （2.5秒に1回）だとブラウザからの一括アップロードが2枚目以降すべて 429 になり、
        「1枚しかアップロードできない」状態になる。そのため一定時間内の合計枚数で
        制限する方式にして、連投防止は維持しつつ一括アップロードを通す。
        """
        client_ip = self._client_rate_key()
        now = time.time()
        with RATE_LIMIT_LOCK:
            times = [t for t in UPLOAD_REQUEST_TIMES.get(client_ip, [])
                     if now - t < UPLOAD_RATE_LIMIT_WINDOW]
            if len(times) >= UPLOAD_RATE_LIMIT_BURST:
                UPLOAD_REQUEST_TIMES[client_ip] = times
                return False
            times.append(now)
            UPLOAD_REQUEST_TIMES[client_ip] = times
            if len(UPLOAD_REQUEST_TIMES) > 1000:
                for k in list(UPLOAD_REQUEST_TIMES.keys()):
                    stamps = UPLOAD_REQUEST_TIMES.get(k)
                    if not stamps or now - stamps[-1] > 3600:
                        del UPLOAD_REQUEST_TIMES[k]
            return True

    def _client_rate_key(self):
        """
        レートリミット／ロックアウトのカウント単位。

        CF-Connecting-IP は「Cloudflare が上書きするから信用できる」ヘッダだが、それが成り立つのは
        リクエストが実際に cloudflared を通って来た場合だけ。cloudflared はホスト上で動き
        127.0.0.1 に接続してくるので、ソケットの接続元がループバックのときに限り採用する。
        LAN や直開放ポートから来た接続では接続元IPを使う。こうしないと、攻撃者が
        CF-Connecting-IP を1回ごとに変えるだけでカウントを分散させ、ロックアウトを
        完全に回避できてしまう（実測: 12回連続失敗でロック0件）。
        """
        client_ip = self.client_address[0] if self.client_address else ""
        forwarded = self.headers.get("cf-connecting-ip")
        if forwarded:
            try:
                if ipaddress.ip_address(client_ip).is_loopback:
                    return f"cf:{forwarded.strip()}"
            except ValueError:
                pass
        return client_ip

    def auth_block_remaining(self):
        """
        認証がロックアウト中なら残り秒数（1秒以上に切り上げ）、解除済みなら 0 を返す。

        全体スロットルだけが作動している場合、失敗履歴が無いクライアントは通す。
        全員を一律で締め出すと、攻撃者が1分ごとに100回失敗させるだけで
        Webリモコンを恒久的に使用不能にできてしまう（＝ゲストへのDoS）ため。
        通してもロックは実質無効化されない：入力を間違えた時点で失敗履歴が付き、
        以後は全体ロックの対象になるので「使い捨てIP1個につき1回」しか試せない
        （通常時は1個につき5回）。
        """
        now = time.time()
        key = self._client_rate_key()
        with AUTH_FAIL_LOCK:
            entry = AUTH_FAILURES.get(key)
            personal_remain = (entry.get("blocked_until", 0.0) - now) if entry else 0.0
            if personal_remain > 0:
                return int(personal_remain) + 1
            global_remain = GLOBAL_AUTH_BLOCKED_UNTIL - now
            if global_remain > 0 and entry:
                return int(global_remain) + 1
        return 0

    def register_auth_failure(self):
        """
        PIN/パスワードの入力ミスを記録し、必要ならロックアウトする。

        しきい値到達後は失敗のたびにロック時間を倍にしていく（30→60→120…上限15分）。
        待ち時間の間は 401 ではなく 429 を返すため、攻撃側は「正解かどうか」の情報を得られない。
        """
        now = time.time()
        key = self._client_rate_key()
        global GLOBAL_AUTH_BLOCKED_UNTIL
        with AUTH_FAIL_LOCK:
            entry = AUTH_FAILURES.get(key)
            if not entry or now - entry.get("last", 0.0) > AUTH_FAIL_FORGET_SECONDS:
                entry = {"count": 0, "blocked_until": 0.0, "last": now}
            entry["count"] += 1
            entry["last"] = now
            if entry["count"] >= AUTH_FAIL_THRESHOLD:
                over = entry["count"] - AUTH_FAIL_THRESHOLD
                lock_seconds = min(AUTH_FAIL_BASE_LOCK_SECONDS * (2 ** over), AUTH_FAIL_MAX_LOCK_SECONDS)
                entry["blocked_until"] = now + lock_seconds
                log_print(f"[APIServer] Auth lockout: {key} failed {entry['count']} times -> blocked {lock_seconds}s")
            AUTH_FAILURES[key] = entry

            # 全体スロットル（IPを変えながらの総当たり対策）
            GLOBAL_AUTH_FAILS.append(now)
            while GLOBAL_AUTH_FAILS and now - GLOBAL_AUTH_FAILS[0] > GLOBAL_AUTH_FAIL_WINDOW:
                GLOBAL_AUTH_FAILS.pop(0)
            if len(GLOBAL_AUTH_FAILS) >= GLOBAL_AUTH_FAIL_LIMIT and GLOBAL_AUTH_BLOCKED_UNTIL < now:
                GLOBAL_AUTH_BLOCKED_UNTIL = now + GLOBAL_AUTH_LOCK_SECONDS
                log_print(
                    f"[APIServer] Auth lockout (global): {len(GLOBAL_AUTH_FAILS)} failures in "
                    f"{int(GLOBAL_AUTH_FAIL_WINDOW)}s -> all guests blocked {GLOBAL_AUTH_LOCK_SECONDS}s"
                )

            # 古いエントリの掃除
            if len(AUTH_FAILURES) > 1000:
                for k in list(AUTH_FAILURES.keys()):
                    if now - AUTH_FAILURES[k].get("last", 0.0) > AUTH_FAIL_FORGET_SECONDS:
                        del AUTH_FAILURES[k]

    def register_auth_success(self):
        """認証に成功したらそのIPの失敗履歴を消す（正規利用者が巻き添えでロックされ続けないように）。"""
        key = self._client_rate_key()
        with AUTH_FAIL_LOCK:
            AUTH_FAILURES.pop(key, None)

    def send_auth_throttled(self, retry_after):
        """ロックアウト中の応答。Retry-After と本文の retry_after で残り秒数を伝える。"""
        payload = {
            "success": False,
            "error": "Too Many Requests",
            "message": f"認証の試行回数が多すぎます。{retry_after} 秒後にもう一度お試しください。",
            "retry_after": retry_after,
            "has_web_password": True
        }
        response_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(429)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Retry-After", str(retry_after))
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def reject_if_auth_blocked(self, path):
        """/api/* へのゲストアクセスがロックアウト中なら 429 を返して True。ホストは対象外。"""
        if not path.startswith("/api/"):
            return False
        remaining = self.auth_block_remaining()
        if not remaining:
            return False
        if self.is_local_request():
            return False
        self.send_auth_throttled(remaining)
        return True

    def may_see_share_info(self):
        """「接続 & スマホ共有」の中身（共有QR・トンネルURL）を返してよい相手か。

        ホストPC本人は常に可。ゲストは config の allow_web_share_info が明示的に
        True のときだけ。既定を False にしてあるのは、このQRがPIN付きのリモコンURL
        そのもので、渡した相手がさらに第三者へ配れてしまうため。
        """
        if self.is_local_request():
            return True
        return bool(
            self.streamer_core
            and self.streamer_core.config.get("allow_web_share_info", False)
        )

    def check_web_password_auth(self, input_password=None):
        """
        Webリモコンのパスワード/PIN認証を検証。
        - ホスト本人（localhost / ループバック）は常に認証不要（True）。
        - web_password が設定されていない（空文字）場合は常に認証不要（True）。
        - X-Web-Password ヘッダまたは Authorization: Bearer <pw>、または直接渡された input_password を検証。
        """
        if self.is_local_request():
            return True
        if not self.streamer_core:
            return True
        configured_password = str(self.streamer_core.config.get("web_password", "")).strip()
        if not configured_password:
            return True

        # 入力パスワード候補をチェック
        candidate = None
        if input_password is not None:
            candidate = str(input_password).strip()
        elif "x-web-password" in self.headers:
            candidate = self.headers.get("x-web-password", "").strip()
        elif "X-Web-Password" in self.headers:
            candidate = self.headers.get("X-Web-Password", "").strip()
        elif "authorization" in self.headers or "Authorization" in self.headers:
            auth_hdr = self.headers.get("Authorization") or self.headers.get("authorization", "")
            if auth_hdr.lower().startswith("bearer "):
                candidate = auth_hdr[7:].strip()

        # 比較は定数時間で行う（応答時間差から1文字ずつ絞り込まれるのを防ぐ）
        ok = hmac.compare_digest(candidate or "", configured_password)

        # 実際に何か入力された試行だけを数える。未入力（ヘッダなし）の 401 まで数えると、
        # ページを開いただけの正規ゲストがロックアウトされてしまう。
        if candidate:
            if ok:
                self.register_auth_success()
            else:
                self.register_auth_failure()
        return ok

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With, X-Web-Password")
        self.send_header("Access-Control-Expose-Headers", "Retry-After")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")

    def send_json_response(self, status_code, data):
        response_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        accept_header = self.headers.get("Accept", "")

        # 認証ロックアウト中のゲストは API に触れない（総当たり対策）
        if self.reject_if_auth_blocked(path):
            return

        # ホスト専用モード（タスク21）。認証も権限も、受け付けると決めた後の話。
        if self.reject_if_web_remote_disabled(path, accept_header):
            return

        # 0-a. タスク27: 参加型カラオケの WebSocket。
        # ★他のどの分岐よりも前に置く。ここから先は HTTP の応答ではなく、
        #   接続を握ったまま返らない別プロトコルになる。
        if path == "/ws/audio_session":
            from karaoke_ws import handle_audio_session
            handle_audio_session(self)
            return

        # 0. API: Auth Check
        if path == "/api/auth":
            configured_pw = str(self.streamer_core.config.get("web_password", "")).strip() if self.streamer_core else ""
            has_pw = bool(configured_pw)
            authed = self.check_web_password_auth()
            self.send_json_response(200, {
                "success": True,
                "has_web_password": has_pw,
                "authenticated": authed,
                "is_local": self.is_local_request()
            })
            return

        # 1. API: Status
        elif path == "/api/status":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "error": "Unauthorized: Web password required or invalid.",
                    "has_web_password": True
                })
                return
            if self.streamer_core:
                # ホスト本人かどうかはリクエスト単位でしか判定できないので、ここで載せる。
                # これが無いと UI 側が「常にホスト」と誤認し、ゲストにサーバー終了/再起動ボタンを見せてしまう。
                is_local = self.is_local_request()
                # ストリームキーはリモートのゲストにも届くレスポンスに載るため、
                # ホスト本人のリクエスト以外では必ずマスクされた状態で返す。
                data = self.streamer_core.get_status_data(include_secrets=is_local)
                data["is_local"] = is_local
                if isinstance(data.get("permissions"), dict):
                    data["permissions"]["is_local"] = is_local
            else:
                data = {"status": "offline", "error": "Core not initialized"}
            self.send_json_response(200, data)
            return

        # 2. API: Config (ローカルホストのみ許可)
        elif path == "/api/config":
            if not self.is_local_request():
                self.send_json_response(403, {"error": "Forbidden: Configuration access is restricted to localhost."})
                return
            if self.streamer_core:
                # localhost 限定のエンドポイントではあるが、ストリームキーは
                # 画面共有・スクリーンショット経由でも漏れる。表示用にはマスクを返し、
                # 生のキーは /api/destination (action=reveal_key) でのみ取得させる。
                safe_config = dict(self.streamer_core.config)
                for key_field in ("topaz_stream_key", "generic_rtmp_key"):
                    raw = str(safe_config.get(key_field, "") or "")
                    safe_config[key_field] = self.streamer_core.mask_stream_key(raw)
                    safe_config[f"{key_field}_set"] = bool(raw)
                self.send_json_response(200, safe_config)
            else:
                self.send_json_response(500, {"error": "Core not initialized"})
            return

        elif path == "/api/audio_devices":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "error": "Unauthorized: Web password required or invalid.",
                    "has_web_password": True
                })
                return
            if not self.is_local_request():
                self.send_json_response(403, {
                    "error": "Forbidden: Audio device enumeration is restricted to localhost."
                })
                return
            query_params = parse_qs(parsed.query)
            use_cache = query_params.get("refresh", ["0"])[0] != "1"
            devices = enumerate_dshow_audio_devices(use_cache=use_cache)
            self.send_json_response(200, {
                "success": True,
                "devices": devices
            })
            return

        elif path == "/api/capture_sources":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "error": "Unauthorized: Web password required or invalid.",
                    "has_web_password": True
                })
                return
            if not self.is_local_request():
                self.send_json_response(403, {
                    "error": "Forbidden: Capture source enumeration is restricted to localhost."
                })
                return
            query_params = parse_qs(parsed.query)
            use_cache = query_params.get("refresh", ["0"])[0] != "1"
            displays = enumerate_capture_displays(use_cache=use_cache)
            windows = enumerate_capture_windows()
            self.send_json_response(200, {
                "success": True,
                "displays": displays,
                "windows": windows
            })
            return

        # 2-b. タスク27: 参加型カラオケの状態（ホスト卓の表示用）
        elif path == "/api/karaoke":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "error": "Unauthorized: Web password required or invalid.",
                    "has_web_password": True
                })
                return
            if not self.streamer_core:
                self.send_json_response(503, {"success": False, "error": "core not ready"})
                return
            if not self.is_local_request():
                # ★ゲストには参加者一覧を見せない。誰が居るか・どのくらい繋がりが
                #   悪いかは、ホストの卓の情報であって参加者どうしで共有する話ではない。
                #   参加できるかどうかだけ返す。
                self.send_json_response(200, {
                    "success": True,
                    "host_view": False,
                    "enabled": bool(self.streamer_core.karaoke.enabled),
                    "approval_required": bool(self.streamer_core.karaoke.approval_required),
                })
                return
            # ★この GET が来ている間だけホストマイクのレベル監視が動く。
            #   卓を閉じればマイクは自然に解放される（開きっぱなしにしない）。
            self.send_json_response(200, {
                "success": True,
                "host_view": True,
                "karaoke": self.streamer_core.karaoke.status_snapshot(),
                "host_mic": self.streamer_core.get_host_mic_state(request_level=True),
                "host_mic_route": bool(self.streamer_core.config.get(
                    "karaoke_host_mic_route", False)),
            })
            return

        # 3. API: QR Code Image
        elif path == "/api/qrcode":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "error": "Unauthorized: Web password required or invalid."
                })
                return
            # このQRはPIN付きのリモコンURLそのもの。UI側で非表示にしているタブの、
            # 直叩き経路をここで塞ぐ。
            if not self.may_see_share_info():
                self.send_json_response(403, {
                    "success": False,
                    "error": "Forbidden: sharing info is disabled by the host."
                })
                return
            url = ""
            if self.streamer_core and self.streamer_core.tunnel_raw_url:
                url = self.streamer_core.tunnel_raw_url
            elif self.streamer_core:
                port = self.streamer_core.config.get("port", 8000)
                url = f"http://localhost:{port}"
            else:
                url = "http://localhost:8000"

            try:
                import qrcode
                import io
                qr = qrcode.QRCode(version=1, box_size=6, border=2)
                qr.add_data(url)
                qr.make(fit=True)
                img = qr.make_image(fill_color="#0F172A", back_color="#FFFFFF")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                png_data = buf.getvalue()

                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png_data)))
                self.end_headers()
                self.wfile.write(png_data)
                return
            except Exception as e:
                log_print(f"[APIServer] Error generating QR image: {e}")
                self.send_json_response(500, {"error": "Failed to generate QR code"})
                return

        # 3.4 アプリの意匠（favicon 用のタイル / ヘッダーの透過マーク）
        # 認証の外。ログイン画面のヘッダーにも出るうえ、機密性は無い。
        # 2枚あるのは用途が違うため: favicon は背景付きの正方形、
        # ヘッダーは背景なし（カードの色に溶けないよう白抜きの線だけ）。
        elif path in ("/app-icon.png", "/app-mark.png"):
            icon_path = _app_asset_path(
                "app_icon.png" if path == "/app-icon.png" else "app_mark.png"
            )
            if not icon_path:
                self.send_error(404, "App icon not found")
                return
            try:
                with open(icon_path, "rb") as f:
                    data = f.read()
            except Exception as e:
                log_print(f"[APIServer] Failed to read app icon: {e}")
                self.send_error(404, "App icon not readable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "public, max-age=604800")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # 3.5 Web リモコンの同梱アセット (Tailwind / RemixIcon / hls.js)
        # 認証の外に置く。ログイン画面自体がこれらを使って描画されるため、
        # ここを閉じるとパスワードを入れる画面すら崩れる（機密性のない第三者ライブラリ）。
        elif path.startswith("/vendor/"):
            rel_name = path[len("/vendor/"):]
            accept_gzip = "gzip" in self.headers.get("Accept-Encoding", "")
            asset = read_vendor_asset(rel_name, accept_gzip=accept_gzip)
            if not asset:
                self.send_error(404, "Vendor asset not found")
                return
            data, content_type, encoding = asset
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if encoding:
                self.send_header("Content-Encoding", encoding)
                self.send_header("Vary", "Accept-Encoding")
            # 中身はアプリのバージョンでしか変わらず、URL に ?v=<version> が付く。
            # トンネル経由のゲストが毎回 1.4MB を引かないよう長めにキャッシュさせる。
            self.send_header("Cache-Control", "public, max-age=604800")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        # 4. HTML Player (Root or /stream.m3u8 directly navigated in browser)
        # /stream.m3u8 はブラウザのアドレスバー直接入力（Sec-Fetch-Dest: document 等）の場合のみ UI を返し、
        # メディアプレイヤー・XHR・Fetch 等によるリクエストには HLS マニフェスト（m3u8）を返す
        elif self._wants_ui_document(path, accept_header):
            live_sync = self.streamer_core.config.get("live_sync_duration_count", 4) if self.streamer_core else 4
            tunnel_stream_url = ""
            if self.streamer_core:
                if self.streamer_core.tunnel_url:
                    tunnel_stream_url = self.streamer_core.tunnel_url
                elif not self.streamer_core.enable_tunnel:
                    port = self.streamer_core.config.get("port", 8000)
                    tunnel_stream_url = f"http://localhost:{port}/stream.m3u8"
                else:
                    tunnel_stream_url = "(トンネルURL準備中...)"
            else:
                tunnel_stream_url = "(サーバー初期化中)"

            html = get_ui_html()
            # 同梱アセットの ?v= に使う。バージョンが上がった時だけブラウザに取り直させる。
            html = html.replace("__APP_VERSION__", APP_VERSION)
            html = html.replace("__LIVE_SYNC_DURATION_COUNT__", str(live_sync))
            html = html.replace("__TUNNEL_STREAM_URL__", tunnel_stream_url)
            content = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # 4. Static HLS files (SimpleHTTPRequestHandler fallback)
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # 認証ロックアウト中のゲストは API に触れない（総当たり対策）
        if self.reject_if_auth_blocked(path):
            return

        # ホスト専用モード（タスク21）。POST は全部 /api/* なので丸ごと塞がる。
        if self.reject_if_web_remote_disabled(path, self.headers.get("Accept", "")):
            return

        # 1. API: Media Upload (写真・画像・動画アップロード)
        if path == "/api/upload":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "message": "Unauthorized: Web password required or invalid."
                })
                return

            if not self.is_local_request() and not self.streamer_core.config.get("allow_web_queue_add", True):
                self.send_json_response(403, {
                    "success": False,
                    "message": "Forbidden: Adding media from Web is disabled by the host."
                })
                return

            if not self.is_local_request() and not self.check_upload_rate_limit():
                self.send_json_response(429, {
                    "success": False,
                    "message": (f"Rate limit exceeded: up to {UPLOAD_RATE_LIMIT_BURST} uploads per "
                                f"{int(UPLOAD_RATE_LIMIT_WINDOW)} seconds. Please wait a moment.")
                })
                return

            try:
                content_len = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                content_len = 0

            max_video_upload_bytes = (
                self.streamer_core.config.get("max_video_upload_mb", 200) * 1024 * 1024
                if self.streamer_core else MAX_VIDEO_UPLOAD_BODY_BYTES
            )
            max_limit = max(MAX_UPLOAD_BODY_BYTES, max_video_upload_bytes)

            if content_len <= 0 or content_len > max_limit:
                self.send_json_response(413, {
                    "success": False,
                    "message": f"Invalid upload size or payload exceeds limit (max {max_limit // (1024*1024)}MB)"
                })
                return

            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return

            body_bytes = self.rfile.read(content_len)
            content_type = self.headers.get("Content-Type", "")

            file_bytes, filename = None, "uploaded_file"
            if "multipart/form-data" in content_type:
                file_bytes, filename = parse_multipart_file(body_bytes, content_type)
            else:
                file_bytes = body_bytes
                filename = "uploaded_video.mp4" if "video" in content_type.lower() else "uploaded_image.png"

            if not file_bytes:
                self.send_json_response(400, {"success": False, "message": "Could not parse media data from upload request"})
                return

            is_video = (
                is_video_url_or_file(filename) or
                "video" in content_type.lower() or
                (len(file_bytes) > 12 and b"ftyp" in file_bytes[:12])
            )

            if is_video:
                if len(file_bytes) > max_video_upload_bytes:
                    self.send_json_response(413, {
                        "success": False,
                        "message": f"Video upload size exceeds limit (max {max_video_upload_bytes // (1024*1024)}MB)"
                    })
                    return
                item = self.streamer_core.add_video_bytes(file_bytes, original_filename=filename)
                if item:
                    self.send_json_response(200, {
                        "success": True,
                        "type": "video",
                        "message": f"Successfully uploaded video: {item.get('title')}",
                        "item": item
                    })
                else:
                    self.send_json_response(400, {
                        "success": False,
                        "message": "Failed to process video (unsupported video format or queue full)"
                    })
                return
            else:
                if len(file_bytes) > MAX_UPLOAD_BODY_BYTES:
                    self.send_json_response(413, {
                        "success": False,
                        "message": f"Photo upload size exceeds limit (max {MAX_UPLOAD_BODY_BYTES // (1024*1024)}MB)"
                    })
                    return
                item = self.streamer_core.add_image_bytes(file_bytes, original_filename=filename)
                if item:
                    self.send_json_response(200, {
                        "success": True,
                        "type": "image",
                        "message": f"Successfully uploaded photo: {item.get('title')}",
                        "item": item
                    })
                else:
                    self.send_json_response(400, {
                        "success": False,
                        "message": "Failed to process image (unsupported image format or queue full)"
                    })
                return

        # ボディ取得（JSON用サイズ上限 64KB）
        try:
            content_len = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            content_len = 0
        if content_len > MAX_REQUEST_BODY_BYTES:
            self.send_json_response(413, {
                "success": False,
                "message": f"Request body too large (max {MAX_REQUEST_BODY_BYTES} bytes)"
            })
            return
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            body_json = json.loads(body.decode("utf-8")) if body else {}
        except Exception as e:
            log_print(f"[APIServer] Error parsing JSON body: {e}")
            body_json = {}

        log_print(f"[APIServer] POST {path} body: {redact_sensitive(body_json)}")

        # 1.5. API: Auth Check / Login
        if path == "/api/auth":
            input_pw = body_json.get("password")
            if self.check_web_password_auth(input_password=input_pw):
                self.send_json_response(200, {
                    "success": True,
                    "message": "Authentication successful"
                })
            else:
                self.send_json_response(401, {
                    "success": False,
                    "message": "Invalid password",
                    "error": "Unauthorized"
                })
            return

        # 2. API: Queue (動画・画像URL追加)
        if path == "/api/queue":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "message": "Unauthorized: Web password required or invalid."
                })
                return

            # 外部からの動画追加 許可チェック
            if not self.is_local_request() and not self.streamer_core.config.get("allow_web_queue_add", True):
                self.send_json_response(403, {
                    "success": False,
                    "message": "Forbidden: Adding items from Web is disabled by the host."
                })
                return

            # レートリミット判定 (外部からの連投・DoS防止)
            if not self.is_local_request() and not self.check_rate_limit():
                self.send_json_response(429, {
                    "success": False,
                    "message": "Rate limit exceeded. Please wait a few seconds before adding another item."
                })
                return

            url = body_json.get("url", "").strip()
            if not url:
                log_print("[APIServer] /api/queue missing url")
                self.send_json_response(400, {"success": False, "message": "Missing 'url' parameter in request body"})
                return

            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return

            items = self.streamer_core.add_to_queue(url)
            log_print(f"[APIServer] add_to_queue returned {len(items)} items")
            if items:
                self.send_json_response(200, {
                    "success": True,
                    "message": f"Successfully added {len(items)} item(s) to queue",
                    "video": items[0],
                    "items": items
                })
            else:
                self.send_json_response(400, {
                    "success": False,
                    "message": "Failed to resolve or add URL (check URL format, safety, or queue capacity)"
                })
            return

        # 3. API: Control (再生・キュー制御)
        elif path == "/api/control":
            if not self.check_web_password_auth():
                self.send_json_response(401, {
                    "success": False,
                    "message": "Unauthorized: Web password required or invalid."
                })
                return

            action = body_json.get("action", "").strip().lower()
            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return

            is_local = self.is_local_request()

            # 破壊的・全消去操作は常にローカルホスト限定
            if action in ("clear_queue", "clear_photos", "stop", "set_live_audio",
                          "set_live_audio_app", "set_live_audio_bg_source",
                          "set_screen_capture") and not is_local:
                self.send_json_response(403, {
                    "success": False,
                    "message": f"Forbidden: Action '{action}' is restricted to localhost."
                })
                return

            # キュー・写真編集操作（削除・並び替え）の権限チェック
            if action in ("delete_item", "move_item", "remove_photo", "delete_photo", "move_photo") and not is_local:
                if not self.streamer_core.config.get("allow_web_queue_edit", True):
                    self.send_json_response(403, {
                        "success": False,
                        "message": "Forbidden: Queue/Photo editing from Web is disabled by the host."
                    })
                    return

            # 再生制御操作の権限チェック
            if action in ("skip", "prev", "set_loop", "set_shuffle", "shuffle", "toggle_image_pause", "set_image_pause", "set_image_duration", "set_image_auto_advance", "set_radio_mode", "set_radio_bg_source", "set_playback_mode", "set_live_audio", "set_live_audio_app", "set_live_audio_bg_source", "set_screen_capture") and not is_local:
                if not self.streamer_core.config.get("allow_web_playback_control", True):
                    self.send_json_response(403, {
                        "success": False,
                        "message": "Forbidden: Playback control from Web is disabled by the host."
                    })
                    return

            if action == "skip":
                self.streamer_core.skip()
                self.send_json_response(200, {"success": True, "message": "Action 'skip' processed."})
            elif action == "prev":
                ok = self.streamer_core.play_prev()
                if ok:
                    self.send_json_response(200, {"success": True, "message": "Action 'prev' processed."})
                else:
                    self.send_json_response(400, {"success": False, "message": "No previous item in history."})
            elif action == "set_playback_mode":
                mode = str(body_json.get("mode", "video")).strip().lower()
                res = self.streamer_core.set_playback_mode(mode)
                self.send_json_response(200, {"success": True, "playback_mode": res, "message": f"Playback mode set to {res}."})
            elif action == "set_live_audio":
                mic_dev = body_json.get("mic_device")
                loop_dev = body_json.get("loopback_device")
                mic_vol = body_json.get("mic_volume")
                loop_vol = body_json.get("loopback_volume")
                res = self.streamer_core.set_live_audio_devices(
                    mic_device=mic_dev,
                    loopback_device=loop_dev,
                    mic_volume=mic_vol,
                    loopback_volume=loop_vol
                )
                self.send_json_response(200, {
                    "success": True,
                    "live_audio": res,
                    "message": "Live audio device settings updated."
                })
            elif action == "set_live_audio_app":
                res = self.streamer_core.set_live_audio_app(
                    enabled=body_json.get("enabled"),
                    window_title=body_json.get("window_title"),
                    volume=body_json.get("volume"),
                    mode=body_json.get("mode")
                )
                self.send_json_response(200, {
                    "success": True,
                    "live_audio_app": res,
                    "message": "App audio capture settings updated."
                })
            elif action == "set_live_audio_bg_source":
                source = str(body_json.get("source", "standby")).strip().lower()
                res = self.streamer_core.set_live_audio_bg_source(source)
                self.send_json_response(200, {
                    "success": True,
                    "live_audio_bg_source": res,
                    "message": f"Live audio background source set to {res}."
                })
            elif action == "set_screen_capture":
                res = self.streamer_core.set_screen_capture_source(
                    source_type=body_json.get("source_type"),
                    display_index=body_json.get("display_index"),
                    window_title=body_json.get("window_title"),
                    framerate=body_json.get("framerate"),
                    width=body_json.get("width"),
                    height=body_json.get("height"),
                    draw_mouse=body_json.get("draw_mouse"),
                    bitrate_kbps=body_json.get("bitrate_kbps"),
                    window_method=body_json.get("window_method"))
                self.send_json_response(200, {"success": True, "screen_capture": res,
                                              "message": "Screen capture source updated."})
            elif action == "set_radio_mode":
                enabled = bool(body_json.get("enabled", True))
                res = self.streamer_core.set_radio_mode(enabled)
                self.send_json_response(200, {"success": True, "radio_mode": res, "message": f"Radio mode set to {res}."})
            elif action == "remove_photo" or action == "delete_photo":
                photo_id = body_json.get("id")
                idx = body_json.get("index")
                target = photo_id if photo_id is not None else idx
                if target is not None:
                    ok = self.streamer_core.remove_photo(target)
                    if ok:
                        self.send_json_response(200, {"success": True, "message": "Photo removed from pool."})
                    else:
                        self.send_json_response(400, {"success": False, "message": "Photo not found or invalid index."})
                else:
                    self.send_json_response(400, {"success": False, "message": "Missing 'id' or 'index' parameter"})
            elif action == "move_photo":
                from_idx = body_json.get("from_index")
                to_idx = body_json.get("to_index")
                if from_idx is not None and to_idx is not None:
                    ok = self.streamer_core.move_photo(int(from_idx), int(to_idx))
                    if ok:
                        self.send_json_response(200, {"success": True, "message": "Photo moved successfully in pool."})
                    else:
                        self.send_json_response(400, {"success": False, "message": "Invalid photo index range."})
                else:
                    self.send_json_response(400, {"success": False, "message": "Missing 'from_index' or 'to_index'"})
            elif action == "clear_photos":
                self.streamer_core.clear_photos()
                self.send_json_response(200, {"success": True, "message": "All photos cleared from pool."})
            elif action == "set_radio_bg_source":
                source = str(body_json.get("source", "card")).strip().lower()
                res = self.streamer_core.set_radio_bg_source(source)
                self.send_json_response(200, {"success": True, "radio_bg_source": res, "message": f"Radio background source set to {res}."})
            elif action == "toggle_image_pause":
                paused = self.streamer_core.toggle_image_pause()
                self.send_json_response(200, {"success": True, "image_paused": paused, "image_auto_advance": not paused, "message": f"Photo pause toggled to {paused}."})
            elif action == "set_image_pause":
                paused = bool(body_json.get("paused", True))
                self.streamer_core.set_image_pause(paused)
                self.send_json_response(200, {"success": True, "image_paused": paused, "image_auto_advance": not paused, "message": f"Photo pause set to {paused}."})
            elif action == "set_image_duration":
                duration = body_json.get("duration", 15)
                sec = self.streamer_core.set_image_duration(duration)
                self.send_json_response(200, {"success": True, "duration": sec, "message": f"Photo duration set to {sec}s."})
            elif action == "set_image_auto_advance":
                enabled = bool(body_json.get("enabled", True))
                self.streamer_core.set_image_auto_advance(enabled)
                self.send_json_response(200, {"success": True, "image_auto_advance": enabled, "image_paused": not enabled, "message": f"Photo auto advance set to {enabled}."})
            elif action == "clear_queue":
                self.streamer_core.clear_queue()
                self.send_json_response(200, {"success": True, "message": "Action 'clear_queue' processed."})
            elif action == "stop":
                self.streamer_core.clear_queue()
                self.streamer_core.skip()
                self.send_json_response(200, {"success": True, "message": "Action 'stop' processed (queue cleared and stream skipped)."})
            elif action == "delete_item":
                idx = body_json.get("index")
                if idx is not None and isinstance(idx, int):
                    deleted = self.streamer_core.delete_queue_item(idx)
                    if deleted:
                        self.send_json_response(200, {"success": True, "message": f"Item at index {idx} removed", "item": deleted})
                    else:
                        self.send_json_response(400, {"success": False, "message": f"Index {idx} out of range"})
                else:
                    self.send_json_response(400, {"success": False, "message": "Missing or invalid 'index' parameter"})
            elif action == "move_item":
                from_idx = body_json.get("from_index")
                to_idx = body_json.get("to_index")
                if from_idx is not None and to_idx is not None:
                    ok = self.streamer_core.move_queue_item(int(from_idx), int(to_idx))
                    if ok:
                        self.send_json_response(200, {"success": True, "message": "Item moved successfully."})
                    else:
                        self.send_json_response(400, {"success": False, "message": "Invalid index range."})
                else:
                    self.send_json_response(400, {"success": False, "message": "Missing 'from_index' or 'to_index'"})
            elif action == "shuffle":
                self.streamer_core.shuffle_queue()
                self.send_json_response(200, {"success": True, "message": "Queue shuffled successfully."})
            elif action == "set_loop":
                enabled = body_json.get("enabled", True)
                res = self.streamer_core.set_loop(enabled)
                self.send_json_response(200, {"success": True, "loop_queue": res, "message": f"Loop queue set to {res}."})
            elif action == "set_shuffle":
                enabled = body_json.get("enabled", True)
                res = self.streamer_core.set_shuffle(enabled)
                self.send_json_response(200, {"success": True, "shuffle": res, "message": f"Shuffle set to {res}."})
            else:
                self.send_json_response(400, {
                    "success": False,
                    "message": f"Unknown action: '{action}'."
                })
            return

        # 3. API: Config (ローカルホスト限定)
        elif path == "/api/config":
            if not self.is_local_request():
                self.send_json_response(403, {"success": False, "message": "Forbidden: Configuration changes are restricted to localhost."})
                return
            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return
            saved = self.streamer_core.save_config(body_json)
            if saved:
                # 検証で弾いた項目があれば理由を返す（黙って無視すると、利用者は
                # 「保存したのに反映されない」としか分からない）
                self.send_json_response(200, {
                    "success": True,
                    "config": self.streamer_core.config,
                    "warnings": list(getattr(self.streamer_core, "last_config_warnings", []))
                })
            else:
                self.send_json_response(500, {"success": False, "message": "Failed to save configuration"})
            return

        # 3-b. API: 参加型カラオケのホスト卓（タスク27 / ローカルホスト限定）
        #
        # ★ゲストに開けてはいけない。ここは「誰の声を配信に乗せるか」を決める場所で、
        #   開ければ参加者が自分で自分を承認できてしまい、承認制が意味を失う。
        elif path == "/api/karaoke":
            if not self.is_local_request():
                self.send_json_response(403, {
                    "success": False,
                    "message": "Forbidden: Karaoke host control is restricted to localhost."
                })
                return
            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return

            session = self.streamer_core.karaoke
            action = str(body_json.get("action", "")).strip().lower()

            if action == "settings":
                settings = self.streamer_core.set_karaoke_settings(
                    enabled=body_json.get("enabled"),
                    approval_required=body_json.get("approval_required"),
                    latency_mode=body_json.get("latency_mode"),
                    master_volume=body_json.get("master_volume"),
                    reverb=body_json.get("reverb"),
                    offset_ms=body_json.get("offset_ms"),
                    sync_reference=body_json.get("sync_reference"),
                    host_mic_route=body_json.get("host_mic_route"),
                )
                self.send_json_response(200, {"success": True, "settings": settings,
                                              "karaoke": session.status_snapshot()})
                return

            if action in ("grant", "deny", "kick", "mix"):
                target = str(body_json.get("id", "")).strip()
                if not target or not session.get(target):
                    self.send_json_response(404, {"success": False,
                                                  "message": "その参加者は見つかりません（すでに退出した可能性があります）"})
                    return
                if action == "grant":
                    session.set_state(target, "active")
                elif action == "deny":
                    session.set_state(target, "denied")
                elif action == "kick":
                    # ★状態を denied にしてから消す。接続スレッドはこの状態変化を
                    #   見て本人へ通知し、自分で畳む。ここでソケットを直接閉じると
                    #   相手には理由の分からない切断になる。
                    session.set_state(target, "denied")
                elif action == "mix":
                    session.set_mix(target,
                                    volume=body_json.get("volume"),
                                    pan=body_json.get("pan"),
                                    host_muted=body_json.get("host_muted"))
                self.send_json_response(200, {"success": True,
                                              "karaoke": session.status_snapshot()})
                return

            if action == "host_mic":
                # ★実体は既存のライブ音声設定。カラオケ卓から触れるようにしただけで、
                #   保存先は同じ（別項目にすると、どちらが配信に乗るのか分からなくなる）。
                #   デバイスを変えると set_live_audio_devices が配信の張り直しを要求する。
                #   dshow は起動時にデバイスを掴むので、これは避けられない。
                self.streamer_core.set_host_mic(
                    device=body_json.get("device"),
                    volume=body_json.get("volume"),
                    loopback_device=body_json.get("loopback_device"),
                    loopback_volume=body_json.get("loopback_volume"),
                )
                self.send_json_response(200, {
                    "success": True,
                    "host_mic": self.streamer_core.get_host_mic_state(request_level=True),
                    "karaoke": session.status_snapshot(),
                })
                return

            # タスク27-B: 伴奏（YouTube 等）。ホスト卓からのみ。
            if action.startswith("bgm_"):
                bgm = session.bgm
                if action == "bgm_load":
                    # ★yt-dlp の解決は数秒かかることがある。ここは POST の中で
                    #   同期に行う（結果を返さないと、UI が成否を出せない）。
                    result = self.streamer_core.load_karaoke_bgm(
                        body_json.get("source"),
                        autoplay=bool(body_json.get("autoplay", True)))
                    if not result.get("success"):
                        self.send_json_response(400, result)
                        return
                    self.send_json_response(200, {
                        "success": True, "bgm": result["bgm"],
                        "karaoke": session.status_snapshot(),
                    })
                    return
                if action == "bgm_play":
                    bgm.play()
                elif action == "bgm_pause":
                    bgm.pause()
                elif action == "bgm_stop":
                    bgm.stop()
                elif action == "bgm_seek":
                    bgm.seek(body_json.get("position", 0))
                elif action == "bgm_volume":
                    bgm.set_volume(body_json.get("volume", 0.8))
                else:
                    self.send_json_response(400, {
                        "success": False,
                        "message": f"Unknown karaoke action: {action!r}"})
                    return
                self.send_json_response(200, {
                    "success": True, "bgm": bgm.snapshot(),
                    "karaoke": session.status_snapshot(),
                })
                return

            if action == "offset_auto":
                # ★基準によって符号が逆になる（remote_mic の設計メモ参照）。
                #   ホスト基準   … 歌声を早める（負）
                #   参加者基準   … 参加者を遅らせる（正）
                suggested, why = self.streamer_core.suggest_karaoke_offset()
                if suggested is None:
                    self.send_json_response(400, {"success": False, "message": why})
                    return
                settings = self.streamer_core.set_karaoke_settings(offset_ms=suggested)
                self.send_json_response(200, {
                    "success": True, "settings": settings,
                    "applied_offset_ms": suggested, "reason": why,
                    "karaoke": session.status_snapshot(),
                })
                return

            if action in ("record_start", "record_stop"):
                if action == "record_start":
                    path_saved = session.start_recording()
                    if not path_saved:
                        self.send_json_response(500, {"success": False,
                                                      "message": "録音を開始できませんでした"})
                        return
                else:
                    path_saved = session.stop_recording()
                self.send_json_response(200, {
                    "success": True,
                    "recording": session.is_recording,
                    "path": os.path.basename(path_saved or ""),
                    "karaoke": session.status_snapshot(),
                })
                return

            self.send_json_response(400, {"success": False,
                                          "message": f"Unknown karaoke action: {action!r}"})
            return

        # 4. API: Destination (配信先操作 / ローカルホスト限定)
        elif path == "/api/destination":
            if not self.is_local_request():
                self.send_json_response(403, {"success": False, "message": "Forbidden: Destination control is restricted to localhost."})
                return
            if not self.streamer_core:
                self.send_json_response(500, {"success": False, "message": "Streamer core not available"})
                return

            core = self.streamer_core
            action = str((body_json or {}).get("action", "")).strip()

            if action == "generate_key":
                # 既存キーを新しいランダムキーで作り直す（ワールド側の貼り直しが必要）
                core.config["topaz_stream_key"] = core.generate_stream_key()
                core.save_config()
                self.send_json_response(200, {
                    "success": True,
                    "destination": core.get_destination_info(include_secrets=True)
                })
                return

            if action == "reveal_key":
                self.send_json_response(200, {
                    "success": True,
                    "destination": core.get_destination_info(include_secrets=True)
                })
                return

            if action == "retry":
                # HLSへ退避している状態から、本来の配信先へ即時復帰を試みる
                core.destination_fallback_active = False
                core.destination_last_error = ""
                core._sink_fail_count = 0
                core._sink_retry_at = 0.0
                core._sink_force_restart = True
                ok = core.ensure_stream_sink()
                core.request_stream_reload()
                self.send_json_response(200, {
                    "success": bool(ok),
                    "destination": core.get_destination_info(include_secrets=True)
                })
                return

            self.send_json_response(400, {"success": False, "message": f"Unknown destination action: {action}"})
            return

        # 5. API: Shutdown (ローカルホスト限定)
        elif path == "/api/shutdown":
            if not self.is_local_request():
                self.send_json_response(403, {"success": False, "message": "Forbidden: Shutdown command is restricted to localhost."})
                return
            self.send_json_response(200, {"success": True, "message": "Server is shutting down..."})
            if self.shutdown_callback:
                threading.Thread(target=self.shutdown_callback, daemon=True).start()
            return

        else:
            self.send_json_response(404, {"error": "Not Found", "path": path})

    def list_directory(self, path):
        """
        ディレクトリ一覧の生成を禁止する。

        HLS配信（stream.m3u8 / *.ts）と写真は VRChat のプレイヤーが認証ヘッダを
        付けられないため PIN の保護外に置かざるを得ない。一方 SimpleHTTPRequestHandler の
        既定では /images/ を開くだけでアップロード済み写真が全部一覧できてしまい、
        トンネルURLを知る全員に過去の共有写真まで晒される。再生には一覧生成は不要なので塞ぐ。
        """
        self.send_error(404, "Not Found")
        return None

    def end_headers(self):
        self.send_cors_headers()
        super().end_headers()

    def log_message(self, format, *args):
        # ログの抑制 (必要に応じてデバッグログ化)
        pass

class APIServer:
    def __init__(self, streamer_core, on_shutdown=None):
        self.streamer_core = streamer_core
        self.on_shutdown = on_shutdown
        self.httpd = None
        self.server_thread = None

    def create_handler(self, *args, **kwargs):
        return APIAndHLSHandler(*args, streamer_core=self.streamer_core,
                                shutdown_callback=self._trigger_shutdown, **kwargs)

    def _trigger_shutdown(self):
        time.sleep(0.5)
        if self.on_shutdown:
            self.on_shutdown()
        else:
            self.stop()
            if self.streamer_core:
                self.streamer_core.shutdown()
            sys.exit(0)

    def start(self):
        port = self.streamer_core.config.get("port", 8000)
        host = self.streamer_core.config.get("host", "127.0.0.1")

        # config の host をそのまま尊重する。
        # 以前はトンネル無効時に host 設定を無視して全インターフェースへバインドしており、
        # "127.0.0.1" 指定でも実際は 0.0.0.0 で待ち受けていた（ログ表示も実態と食い違っていた）。
        # LAN公開したい場合は host を "0.0.0.0" にするか、起動時に --host 0.0.0.0 を渡す。
        bind_host = "" if host in ("0.0.0.0", "") else host
        listens_on_all = bind_host == ""

        from streamer_core import get_local_ip
        local_ip = get_local_ip()

        try:
            self.httpd = ThreadedHTTPServer((bind_host, port), self.create_handler)
            endpoints = f"Local: http://127.0.0.1:{port}"
            if listens_on_all:
                endpoints += f", LAN: http://{local_ip}:{port}"
            log_print(f"[APIServer] Listening on {'0.0.0.0' if listens_on_all else host}:{port} ({endpoints})")
            if listens_on_all:
                trust_lan = bool(self.streamer_core.config.get("trust_lan_clients", False))
                log_print(
                    "[APIServer] Bound to ALL interfaces. LAN clients are treated as "
                    + ("HOSTS (trust_lan_clients=true)" if trust_lan
                       else "guests (allow_web_* permissions apply)")
                )
            self.server_thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
            self.server_thread.start()
            return True
        except Exception as e:
            log_print(f"[APIServer] Failed to bind on {host}:{port}: {e}")
            return False

    def stop(self):
        if self.httpd:
            log_print("[APIServer] Stopping HTTP server...")
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                pass
            self.httpd = None
