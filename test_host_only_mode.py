# -*- coding: utf-8 -*-
"""ホスト専用モード（enable_web_remote: false）の回帰テスト。タスク21。

固定したいのは4点:

1. **既定は「開いている」**。既存ユーザーの config.json にこのキーは無く、
   fail-closed にすると更新しただけで全員のリモコンが黙って死ぬ。
2. **ホスト判定は厳格なループバックのみ**。cloudflared はこのPCの 127.0.0.1 へ
   繋いでくるので、接続元IPだけを見るとトンネル経由の全員がホスト扱いになり、
   ゲートが丸ごと無意味になる（この機能で一番危ない失敗）。
   trust_lan_clients も見ない。「ホスト専用」なら同一LANの別端末も他人。
3. **配信は止めない**。VRChatのプレイヤーは認証ヘッダを付けられないので、
   stream.m3u8 / *.ts は閉じたあとも通す。逆に写真プール (/images/*) は通さない。
4. **QRは焼かない**。誰も開けないURLをオーバーレイや待機画面に出さない。
"""

import io
import json
import os

import pytest

import api_server
import streamer_core

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_HTML = os.path.join(BASE_DIR, "ui", "index.html")


def _ui():
    with io.open(UI_HTML, encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------------------------
# 1. 既定値
# --------------------------------------------------------------------------

def test_web_remote_is_enabled_by_default():
    """既定は True。ここを False にすると更新した全員のリモコンが消える。"""
    assert streamer_core.DEFAULT_CONFIG["enable_web_remote"] is True


def test_missing_key_is_treated_as_enabled():
    """キーが無い古い設定ファイルは「有効」として扱うこと。"""
    core = streamer_core.StreamerCore()
    core.config.pop("enable_web_remote", None)
    assert core.is_web_remote_enabled() is True


def test_status_reports_the_flag():
    core = streamer_core.StreamerCore()
    assert core.get_status_data()["enable_web_remote"] is True
    core.config["enable_web_remote"] = False
    data = core.get_status_data()
    assert data["enable_web_remote"] is False
    assert data["permissions"]["enable_web_remote"] is False


# --------------------------------------------------------------------------
# 2. ゲート判定（ソケットを張らずにメソッドだけ試す最小の器）
# --------------------------------------------------------------------------

class _FakeCore:
    def __init__(self, enabled=True, trust_lan=False):
        self.config = {"enable_web_remote": enabled, "trust_lan_clients": trust_lan}


class _FakeHeaders(dict):
    """email.message.Message と同じく大文字小文字を区別しないヘッダ袋。"""

    def __init__(self, mapping=None):
        super().__init__({k.lower(): v for k, v in (mapping or {}).items()})

    def __contains__(self, key):
        return super().__contains__(str(key).lower())

    def get(self, key, default=None):
        return super().get(str(key).lower(), default)


def _handler(client_ip="127.0.0.1", headers=None, enabled=True, trust_lan=False):
    h = object.__new__(api_server.APIAndHLSHandler)
    h.streamer_core = _FakeCore(enabled, trust_lan)
    h.client_address = (client_ip, 12345)
    h.headers = _FakeHeaders(headers)
    # Origin / Host の妥当性は既存テスト（test_web_remote_visibility）の担当。
    # ここでは「誰から来たか」の判定だけを見る。
    h._origin_is_self = lambda: True
    h._host_header_is_safe = lambda: True
    return h


@pytest.mark.parametrize("client_ip,headers,expected", [
    ("127.0.0.1", None, True),
    ("::1", None, True),
    # トンネル経由。cloudflared が 127.0.0.1 から繋いでくるため IP だけでは見分けられない
    ("127.0.0.1", {"CF-Connecting-IP": "203.0.113.9"}, False),
    ("127.0.0.1", {"X-Forwarded-For": "203.0.113.9"}, False),
    # 同一LANの別端末
    ("192.168.1.50", None, False),
    ("10.0.0.8", None, False),
])
def test_strict_loopback_detection(client_ip, headers, expected):
    assert _handler(client_ip, headers)._client_is_strict_loopback() is expected


def test_trust_lan_clients_does_not_open_the_host_only_gate():
    """trust_lan_clients を立てても、ホスト専用モードではLANは他人のまま。"""
    h = _handler("192.168.1.50", trust_lan=True)
    assert h._client_is_strict_loopback() is False


@pytest.mark.parametrize("path,is_media", [
    ("/stream.m3u8", True),
    ("/stream0.ts", True),
    ("/segment.M3U8", True),
    ("/images/photo_1.jpg", False),
    ("/standby.png", False),
    ("/qr_overlay.png", False),
    ("/api/status", False),
    ("/", False),
])
def test_media_allow_list(path, is_media):
    """許可リスト方式であること。HLS_DIR には写真プールが同居している。"""
    assert _handler()._is_media_path(path) is is_media


class _Recorder:
    """send_response / send_json_response を捕まえるだけの記録係。"""

    def __init__(self):
        self.status = None
        self.json = None
        self.headers = []
        self.body = b""


def _gated(path, accept="", client_ip="203.0.113.9", headers=None, enabled=False):
    h = _handler(client_ip, headers, enabled=enabled)
    rec = _Recorder()
    h.send_json_response = lambda code, data: (setattr(rec, "status", code), setattr(rec, "json", data))
    h.send_response = lambda code: setattr(rec, "status", code)
    h.send_header = lambda k, v: rec.headers.append((k, v))
    h.end_headers = lambda: None
    h.wfile = io.BytesIO()
    blocked = h.reject_if_web_remote_disabled(path, accept)
    rec.body = h.wfile.getvalue()
    return blocked, rec


def test_gate_is_transparent_while_enabled():
    """有効なうちは何も塞がない（既存挙動を1バイトも変えない）。"""
    blocked, rec = _gated("/api/status", enabled=True)
    assert blocked is False
    assert rec.status is None


def test_gate_lets_the_host_through():
    blocked, _ = _gated("/api/config", client_ip="127.0.0.1")
    assert blocked is False


def test_gate_blocks_guest_api_with_403_json():
    blocked, rec = _gated("/api/status")
    assert blocked is True
    assert rec.status == 403
    assert rec.json["enable_web_remote"] is False


def test_gate_blocks_guest_ui_with_403_page():
    blocked, rec = _gated("/", accept="text/html")
    assert blocked is True
    assert rec.status == 403
    text = rec.body.decode("utf-8")
    assert "<!DOCTYPE html>" in text
    # 外部に晒す画面なので、素性の分かる情報を載せない
    assert "VRC_Media_Streamer" not in text
    assert streamer_core.APP_VERSION not in text


def test_gate_keeps_the_stream_playable():
    """VRChat のプレイヤーが取りに来るものは閉じたあとも通すこと。"""
    for path in ("/stream.m3u8", "/stream3.ts"):
        blocked, _ = _gated(path, accept="*/*")
        assert blocked is False, "{} を塞ぐと配信自体が止まる".format(path)


def test_gate_still_shows_the_notice_for_a_browser_visiting_the_manifest():
    """アドレスバーに /stream.m3u8 を直打ちしたブラウザには案内を返す。"""
    blocked, rec = _gated(
        "/stream.m3u8",
        accept="text/html,application/xhtml+xml",
        headers={"Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate"},
    )
    assert blocked is True
    assert rec.status == 403


def test_gate_blocks_the_photo_pool():
    """写真プールは再生に不要。トンネル越しに過去の共有写真を出さない。"""
    blocked, rec = _gated("/images/photo_1.jpg")
    assert blocked is True
    assert rec.status == 403


def test_gate_runs_before_authentication():
    """関門は認証・権限判定より前に置くこと（閉じているなら問う必要がない）。"""
    with io.open(os.path.join(BASE_DIR, "api_server.py"), encoding="utf-8") as f:
        src = f.read()
    for entry in ("def do_GET(self):", "def do_POST(self):"):
        _, _, tail = src.partition(entry)
        assert tail
        gate = tail.index("reject_if_web_remote_disabled")
        auth = tail.index("check_web_password_auth")
        assert gate < auth, "{} で認証より後にゲートを置いている".format(entry)


# --------------------------------------------------------------------------
# 3. QR の連動
# --------------------------------------------------------------------------

def test_qr_overlay_is_not_generated_when_disabled():
    core = streamer_core.StreamerCore()
    core.config["enable_web_remote"] = False
    assert core.generate_qr_overlay_image() is None


def test_status_reports_qr_as_off_without_touching_the_setting():
    """設定値は保持したまま、状態としては消灯を返すこと（再有効化で元に戻る）。"""
    core = streamer_core.StreamerCore()
    core.config["overlay_qr_enabled"] = True
    core.config["enable_web_remote"] = False
    data = core.get_status_data()
    assert data["overlay_qr_enabled"] is False
    assert core.config["overlay_qr_enabled"] is True, "設定値まで書き換えている"


def test_remote_url_is_not_published_when_disabled():
    core = streamer_core.StreamerCore()
    core.tunnel_raw_url = "https://example.trycloudflare.com"
    core.config["enable_web_remote"] = False
    data = core.get_status_data()
    assert data["remote_url"] == ""
    # 配信URLは生かす（ワールドに貼るURLはリモコンとは別物）
    assert data["stream_url"].endswith("/stream.m3u8")


def test_standby_qr_screen_falls_back_to_image(monkeypatch):
    """誰も開けないURLの案内画面を配信し続けないこと。"""
    core = streamer_core.StreamerCore()
    core.config["standby_mode"] = "qr"
    core.config["enable_web_remote"] = False
    seen = {}

    def _spy():
        seen["qr"] = True
        return None

    monkeypatch.setattr(core, "generate_qr_overlay_image", _spy)
    core.generate_standby_image()
    assert "qr" not in seen, "QR案内画面のままになっている"


# --------------------------------------------------------------------------
# 4. 切り替える手段（フラグだけ足して機能が消えたように見えるのを防ぐ）
# --------------------------------------------------------------------------

def test_both_settings_screens_expose_the_toggle():
    html = _ui()
    assert 'id="hostEnableWebRemote"' in html, "ホスト設定画面にトグルが無い"
    assert "set('hostEnableWebRemote', cfg.enable_web_remote !== false);" in html, \
        "読み込みが無い（未設定を無効扱いにしている）"
    assert "enable_web_remote: bool('hostEnableWebRemote')," in html, "保存が無い"

    with io.open(os.path.join(BASE_DIR, "gui_streamer.py"), encoding="utf-8") as gui_f:
        gui = gui_f.read()
    assert "switch_web_remote" in gui, "従来設定画面にトグルが無い"
    assert '"enable_web_remote": bool(self.switch_web_remote.get()),' in gui, \
        "従来設定画面が保存していない"


def test_cli_can_close_and_open_the_remote():
    """--host-only / --web-remote が config へ効くこと（dest 名の取り違え検出）。"""
    import argparse

    from config_overrides import add_config_arguments, build_overrides

    parser = argparse.ArgumentParser()
    add_config_arguments(parser)

    def over(argv):
        return build_overrides(parser.parse_args(argv), environ={})

    assert "enable_web_remote" not in over([])
    assert over(["--host-only"])["enable_web_remote"] == (False, "cli")
    assert over(["--web-remote"])["enable_web_remote"] == (True, "cli")
    # 両方指定は安全側（閉じる）を採る
    assert over(["--web-remote", "--host-only"])["enable_web_remote"] == (False, "cli")


def test_plugin_ui_is_in_sync():
    """plugin/ui/index.html は ui/index.html と同一であること（配布物のズレ防止）。"""
    with io.open(os.path.join(BASE_DIR, "plugin", "ui", "index.html"), encoding="utf-8") as f:
        assert f.read() == _ui()


def test_dist_config_ships_the_key():
    with io.open(os.path.join(BASE_DIR, "config.dist.json"), encoding="utf-8") as f:
        assert json.load(f)["enable_web_remote"] is True
