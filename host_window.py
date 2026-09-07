# -*- coding: utf-8 -*-
"""ホスト画面（モダンUI）。Webリモコンと同じ画面をデスクトップウィンドウとして開く。

**なぜWebViewなのか**
ホスト用の CustomTkinter 画面と Webリモコン(`ui/index.html`) で同じ機能を二重に
実装してきた結果、デザインも機能網羅も食い違っていた（設定はホスト8セクション /
Web5項目、配信プレビューはWebのみ、等）。画面の正本を `ui/index.html` 一つに寄せ、
ホストはそれを WebView2 で表示するだけにすることで、二重管理そのものを無くす。

**ネイティブ機能は残す**
ブラウザからは絶対にできないこと（容量無制限のローカル動画追加、待機画像の選択、
アプリ終了、ストリームキーの平文取得）だけを `window.pywebview.api` として橋渡しする。
Webアップロード経路（200MB上限・ファイルのコピーが発生）とは別物なので、ここは削れない。

**壊れたら従来画面へ落ちる**
WebView2 ランタイムが無い環境ではウィンドウを作れない。その場合は False を返し、
呼び出し側(`gui_streamer.main`)が従来の CustomTkinter 画面を開く。
「起動したのに何も出ない」が最悪なので fail-safe にしてある。
"""

import os
import sys
import threading

from streamer_core import log_print

VIDEO_FILE_TYPES = (
    "Video Files (*.mp4;*.mov;*.webm;*.mkv;*.avi;*.m4v;*.ts;*.flv)",
    "All files (*.*)",
)
IMAGE_FILE_TYPES = (
    "Image Files (*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif)",
    "All files (*.*)",
)

WINDOW_WIDTH = 1180
WINDOW_HEIGHT = 820
WINDOW_MIN_SIZE = (940, 620)
# Webリモコン側の背景色(#121214)と揃える。既定の白のままだと、
# ページ描画までの一瞬だけ白い矩形が光ってダークUIとして見苦しい。
WINDOW_BG = "#121214"


def is_available():
    """WebView ホスト画面を開ける環境かどうか。"""
    try:
        import webview  # noqa: F401
    except Exception:
        return False
    return True


class HostBridge:
    """JS から `window.pywebview.api.<name>()` で呼ばれるネイティブ機能。

    このオブジェクトは WebView ウィンドウの中にしか露出しない。ブラウザで開いた
    Webリモコン（＝フレンドのスマホ）からは存在しないので、ここに置いた機能は
    ホスト本人専用になる。とはいえ戻り値はそのまま画面へ出るため、
    ストリームキーを含むものは呼び出しを明示的に分けてある。
    """

    def __init__(self, streamer_core, api_server):
        # 内部参照は必ず `_` 始まりにすること。pywebview は js_api オブジェクトの
        # **公開属性を再帰的に walk して** JS 側の関数を生やす（webview/util.py の
        # get_functions）。`self.window` のように公開で持つと .NET の Window を
        # 舐めに行って `maximum recursion depth exceeded` を吐き、StreamerCore の
        # メソッドまでページへ露出する。`_` 始まりは走査から除外される。
        self._core = streamer_core
        self._api_server = api_server
        self._window = None
        # 「開始済みなら素通り」ではなく「先に始まった方を待つ」ためのロック。
        # 理由は _shutdown() のコメントを参照。
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = threading.Event()

    # --- 基本情報 ---------------------------------------------------------
    def host_info(self):
        """ホスト画面であることと、ネイティブ機能の可否をUIへ伝える。"""
        return {
            "is_host_window": True,
            "platform": sys.platform,
            "can_pick_files": True,
        }

    # --- ファイル選択（ブラウザでは代替できないもの） ---------------------
    def add_video_files(self):
        """ローカル動画をキューへ追加する。**容量上限なし**。

        Webアップロード経路(200MB上限)と違い、ファイルをコピーせず元の場所を
        参照して配信するため、外付けHDD上の長尺MP4でもそのまま追加できる。
        """
        paths = self._pick_files(VIDEO_FILE_TYPES)
        if not paths:
            return {"selected": 0}
        self._add_in_background(paths, self._core.add_video_file, "video")
        return {"selected": len(paths)}

    def add_photo_files(self):
        """ローカル画像を写真プールへ追加する。こちらも容量上限なし。"""
        paths = self._pick_files(IMAGE_FILE_TYPES)
        if not paths:
            return {"selected": 0}
        self._add_in_background(paths, self._core.add_image_file, "photo")
        return {"selected": len(paths)}

    def select_standby_image(self):
        """待機画面の画像を選ぶ。設定へ焼いて待機画像を作り直す。"""
        paths = self._pick_files(IMAGE_FILE_TYPES, allow_multiple=False)
        if not paths:
            return {"selected": 0}
        path = paths[0]
        try:
            self._core.save_config({
                "standby_image_path": path,
                "standby_mode": "image",
            })
            self._core.generate_standby_image()
        except Exception as e:
            log_print(f"[HostWindow] Failed to apply standby image: {e}")
            return {"selected": 0, "error": str(e)}
        return {"selected": 1, "path": path}

    # --- 秘匿値 -----------------------------------------------------------
    def reveal_video_url(self):
        """ワールド用URLを**ストリームキー込み**で返す。

        画面共有や配信に映り込むと第三者に配信を乗っ取られるため、既定はマスク表示。
        本人が明示的に押したときだけここを通す。
        """
        try:
            return {"url": self._core.get_video_url(include_secrets=True) or ""}
        except Exception as e:
            log_print(f"[HostWindow] Failed to reveal video url: {e}")
            return {"url": ""}

    # --- アプリ操作 -------------------------------------------------------
    def open_external(self, url):
        """既定のブラウザで開く。WebViewの中で外部サイトへ遷移させないため。"""
        try:
            import webbrowser
            webbrowser.open(str(url))
            return {"success": True}
        except Exception as e:
            log_print(f"[HostWindow] Failed to open external url: {e}")
            return {"success": False}

    def exit_app(self):
        """配信を停止してアプリを終了する。"""
        self._shutdown()
        try:
            if self._window:
                self._window.destroy()
        except Exception:
            pass
        return {"success": True}

    # --- 内部 -------------------------------------------------------------
    def _shutdown(self):
        """コアとサーバーを止める。

        ×ボタンと終了ボタンの両方から来るので、二重に呼ばれても平気にしてある。
        ただし **「開始済みなら素通り」にしてはいけない**。×で閉じたときは
        pywebview の closed イベント（別スレッド）でここへ入るが、その処理が
        途中のうちに webview.start() が戻り、run_host_window() の保険の呼び出しが
        素通りして main が sys.exit(0) する。デーモンスレッドはそこで打ち切られ、
        後片付けが飛ぶ。★実測 2026-09-03: ×で3回閉じたうち、HTTPサーバー停止まで
        到達したのは1回、コアの「Shutdown complete」は2回だけだった。
        （FFmpeg の kill は core.shutdown() の先頭にあるため孤児は出ていなかったが、
        処理順に依存しているだけで、保証されていたわけではない。）

        そのためロックで直列化し、後から来た方は**先に始まった方の完了を待つ**。
        """
        with self._shutdown_lock:
            if self._shutdown_done.is_set():
                return
            log_print("Shutting down streamer server and processes...")
            try:
                self._core.shutdown()
            except Exception as e:
                log_print(f"[HostWindow] Error during core shutdown: {e}")
            try:
                self._api_server.stop()
            except Exception as e:
                log_print(f"[HostWindow] Error during server shutdown: {e}")
            self._shutdown_done.set()

    def _pick_files(self, file_types, allow_multiple=True):
        if not self._window:
            return []
        try:
            import webview
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=allow_multiple,
                file_types=file_types,
            )
        except Exception as e:
            log_print(f"[HostWindow] File dialog failed: {e}")
            return []
        if not result:
            return []
        if isinstance(result, str):
            return [result]
        return [p for p in result if p]

    def _add_in_background(self, paths, add_func, label):
        """追加はワーカースレッドで行う。

        JS 側を待たせない。長尺動画のプローブは数秒かかることがあり、同期で返すと
        その間ウィンドウが固まったように見える。追加結果は既存の /api/status
        ポーリングで画面に出るため、待つ必要そのものが無い。
        """
        def worker():
            added = 0
            for path in paths:
                try:
                    if add_func(path):
                        added += 1
                except Exception as e:
                    log_print(f"[HostWindow] Failed to add {label} {os.path.basename(str(path))}: {e}")
            log_print(f"[HostWindow] Added {added}/{len(paths)} {label}(s).")

        threading.Thread(target=worker, daemon=True).start()


def run_host_window(streamer_core, api_server):
    """モダンUIのホストウィンドウを開く。開けたら True、無理なら False。

    True を返した時点でウィンドウは既に閉じられている（`webview.start()` は
    ウィンドウが閉じるまで戻らない）。呼び出し側はそのまま終了処理へ進めばよい。
    """
    try:
        import webview
    except Exception as e:
        log_print(f"[HostWindow] pywebview is unavailable ({e}). Falling back to the classic UI.")
        return False

    port = streamer_core.config.get("port", 8000)
    # bind先が 0.0.0.0 でも、ホスト判定(is_local_request)を通すためループバックで開く。
    url = f"http://127.0.0.1:{port}/"

    bridge = HostBridge(streamer_core, api_server)
    # ★Webリモコンの「サーバー終了」(/api/shutdown) をここへ繋ぐ。
    #   繋がっていないと、コアとAPIだけ止まってウィンドウが残る
    #   （＝殻だけのゴーストプロセスになる）。exit_app はウィンドウも畳むので、
    #   webview.start() が戻り、主スレッドが正しく終了まで進む。
    api_server.on_shutdown = bridge.exit_app
    try:
        window = webview.create_window(
            "VRC_Media_Streamer",
            url,
            js_api=bridge,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            min_size=WINDOW_MIN_SIZE,
            background_color=WINDOW_BG,
        )
    except Exception as e:
        log_print(f"[HostWindow] Failed to create window ({e}). Falling back to the classic UI.")
        return False

    bridge._window = window

    # ×ボタンで閉じられた場合も配信を止める。これが無いと cloudflared / ffmpeg が
    # 孤児プロセスとして残る（従来画面の WM_DELETE_WINDOW と同じ理由）。
    try:
        window.events.closed += lambda: bridge._shutdown()
    except Exception:
        pass

    try:
        webview.start(debug=False)
    except Exception as e:
        log_print(f"[HostWindow] WebView failed to start ({e}). Falling back to the classic UI.")
        return False

    bridge._shutdown()
    return True
