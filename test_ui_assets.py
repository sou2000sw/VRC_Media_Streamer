# -*- coding: utf-8 -*-
"""Webリモコンの同梱アセット (ui/vendor/) の検証。

v2.9.4 まで Tailwind / RemixIcon / hls.js は CDN 直リンクだった。ホストPCがオフライン、
あるいは CDN が塞がれた回線では UI が素のHTMLになり操作不能になるため同梱へ切り替えた。
「同梱したつもりでファイルが無い」「参照だけ古い」を検知できないと、症状が出るのは
配布後のオフライン環境（＝こちらから再現できない場所）なので、ここで固定する。
"""

import io
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import pytest

import api_server
from api_server import APIServer, read_vendor_asset
from streamer_core import StreamerCore
from version import APP_VERSION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_HTML = os.path.join(BASE_DIR, "ui", "index.html")
VENDOR_DIR = os.path.join(BASE_DIR, "ui", "vendor")
TEST_PORT = 8997


def _read_ui_html():
    with io.open(UI_HTML, encoding="utf-8") as f:
        return f.read()


def test_vendor_files_exist():
    """index.html が参照する ./vendor/* が実在すること。"""
    html = _read_ui_html()
    refs = set(re.findall(r'\./vendor/([A-Za-z0-9_.-]+)', html))
    assert refs, "index.html が ./vendor/ を参照していない（CDN直リンクに戻っていないか）"
    for name in refs:
        path = os.path.join(VENDOR_DIR, name)
        assert os.path.isfile(path), f"同梱アセットが無い: ui/vendor/{name}"
        assert os.path.getsize(path) > 1024, f"同梱アセットが空/破損: ui/vendor/{name}"


def test_third_party_libs_are_local_first():
    """3ライブラリとも「ローカルが正・CDNはフォールバック」になっていること。

    CDN 直リンクへ戻すと、オフラインのホストPCでUIが崩れる回帰になる。
    """
    html = _read_ui_html()
    for name in ("tailwind.min.js", "remixicon.css", "hls.min.js"):
        assert f"./vendor/{name}" in html, f"{name} のローカル参照が無い"
    # CDN URL は残ってよいが、フォールバック経路（document.write / onerror）の中だけ。
    for cdn in ("https://cdn.tailwindcss.com", "cdn.jsdelivr.net/npm/hls.js"):
        for m in re.finditer(re.escape(cdn), html):
            line_start = html.rfind("\n", 0, m.start()) + 1
            line = html[line_start:html.find("\n", m.start())]
            assert ("document.write" in line) or ("onerror" in line) or ("<!--" in line), \
                f"CDN が主参照のまま残っている: {line.strip()[:120]}"


def test_app_icon_assets_exist():
    """配布用アイコンが同梱されていること。

    EXE のアイコン(.ico)と、UI のブランドマーク/favicon(.png)。
    ビルド時に `--icon` が参照するので、欠けるとビルドが失敗する。
    """
    ico = os.path.join(BASE_DIR, "assets", "app_icon.ico")
    png = os.path.join(BASE_DIR, "assets", "app_icon.png")
    mark = os.path.join(BASE_DIR, "assets", "app_mark.png")
    assert os.path.isfile(ico) and os.path.getsize(ico) > 1024, "assets/app_icon.ico が無い/壊れている"
    assert os.path.isfile(png) and os.path.getsize(png) > 512, "assets/app_icon.png が無い/壊れている"
    assert os.path.isfile(mark) and os.path.getsize(mark) > 512, "assets/app_mark.png が無い/壊れている"


def test_ui_uses_own_brand_mark_not_youtube():
    """UIのブランドマークが自前のアイコンであること（YouTubeロゴを使わない）。

    他社サービスのロゴを自作アプリの顔に使わない。本ツールは YouTube 専用でもない
    （X / Instagram 等も通る）ので、意匠としても実態に合っていなかった。
    """
    for path in (UI_HTML, os.path.join(BASE_DIR, "plugin", "ui", "index.html")):
        with io.open(path, encoding="utf-8") as f:
            html = f.read()
        assert "ri-youtube" not in html, f"{path}: YouTubeのロゴが残っている"
        assert 'src="/app-mark.png"' in html, f"{path}: ブランドマークが自前アイコンになっていない"
        assert 'rel="icon"' in html, f"{path}: favicon が設定されていない"


def test_preview_player_is_closed_by_default():
    """プレビューは既定で閉じていること（Webリモコン・ホスト画面の両方）。

    開いたまま起動すると、画面を見ていなくても HLS セグメントを取り続け、
    帯域とCPUを食う。ホスト画面は起動しっぱなしで使われるので影響が大きい。
    """
    for path in (UI_HTML, os.path.join(BASE_DIR, "plugin", "ui", "index.html")):
        with io.open(path, encoding="utf-8") as f:
            html = f.read()
        assert "let previewEnabled = false;" in html, f"{path}: 既定で有効になっている"
        idx = html.index('id="previewCard"')
        tag = html[html.rfind("<", 0, idx):html.index(">", idx)]
        assert "hidden" in tag, f"{path}: プレビューカードが最初から開いている: {tag[:120]}"
        assert "if (previewEnabled) initHlsPlayer();" in html,             f"{path}: 起動時に無条件でHLSを掴んでいる"


def test_script_tags_are_balanced():
    """開始タグと終了タグの個数が一致すること。

    リリース検証(build_exe.py)は配信HTMLのこの個数一致で破損を見ている。
    CDNフォールバックを document.write で書くと、文字列リテラル中の生タグが
    数に混じって**ビルドの最後の最後で**落ちる（実際に一度落とした）。
    5分かかるビルドではなく、ここで即座に気付けるようにする。
    """
    for path in (UI_HTML, os.path.join(BASE_DIR, "plugin", "ui", "index.html")):
        with io.open(path, encoding="utf-8") as f:
            html = f.read()
        opens, closes = html.count("<script"), html.count("</script>")
        assert opens == closes, f"{path}: {opens} '<script' vs {closes} closing tags"


def test_live_audio_mixer_batches_changes_until_apply():
    html = _read_ui_html()
    assert 'id="liveAudioMixerApplyBtn"' in html
    assert "action: 'set_live_audio_mixer'" in html
    assert 'onchange="applyLiveAudioSettings()"' not in html
    assert 'onchange="applyLiveAudioAppSettings()"' not in html


def test_remixicon_css_only_references_bundled_fonts():
    """CSS が同梱していない eot/ttf/svg を参照していないこと（404を撃ち続けるため）。"""
    with io.open(os.path.join(VENDOR_DIR, "remixicon.css"), encoding="utf-8") as f:
        css = f.read()
    for ext in (".eot", ".ttf", ".svg"):
        assert ext not in css, f"同梱していないフォント形式を参照している: {ext}"
    for name in re.findall(r'url\(["\']?([A-Za-z0-9_.-]+)["\']?\)', css):
        assert os.path.isfile(os.path.join(VENDOR_DIR, name)), f"参照フォントが無い: {name}"


@pytest.mark.parametrize("rel_name", [
    "../index.html",
    ".." + chr(92) + "index.html",  # Windows 区切りでの遡上
    "sub/dir.js",
    "index.html",
    "config.json",
    ".env",
    "",
])
def test_vendor_path_traversal_and_extension_are_rejected(rel_name):
    """vendor 配下・許可拡張子のみに限定されていること。"""
    assert read_vendor_asset(rel_name) is None


def test_vendor_asset_gzip_is_smaller():
    """テキスト資産は gzip で返せること（トンネル経由のゲストの初回転送量を抑える）。"""
    raw = read_vendor_asset("tailwind.min.js", accept_gzip=False)
    gz = read_vendor_asset("tailwind.min.js", accept_gzip=True)
    assert raw and gz
    assert raw[2] is None and gz[2] == "gzip"
    assert len(gz[0]) < len(raw[0]) / 2

    # woff2 は圧縮済み。掛け直しても増えるだけなので素で返す。
    font = read_vendor_asset("remixicon.woff2", accept_gzip=True)
    assert font and font[2] is None


def test_vendor_assets_served_over_http():
    core = StreamerCore(override_port=TEST_PORT, override_enable_tunnel=False)
    server = APIServer(core)
    server.start()
    time.sleep(1)
    base = f"http://127.0.0.1:{TEST_PORT}"
    try:
        # 1. 同梱アセットが配信される
        req = urllib.request.Request(f"{base}/vendor/tailwind.min.js?v={APP_VERSION}",
                                     headers={"Accept-Encoding": "gzip"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            assert "javascript" in resp.headers.get("Content-Type", "")
            assert resp.headers.get("Content-Encoding") == "gzip"
            assert "max-age" in resp.headers.get("Cache-Control", "")
            assert len(resp.read()) > 1024

        # 2. フォントは gzip せず素で返す
        with urllib.request.urlopen(f"{base}/vendor/remixicon.woff2") as resp:
            assert resp.status == 200
            assert resp.headers.get("Content-Type") == "font/woff2"

        # 3. 許可外・存在しないものは 404（ui/ 配下を丸ごと露出させない）
        for bad in ("/vendor/nope.js", "/vendor/%2e%2e%2fconfig.json", "/vendor/index.html"):
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(f"{base}{bad}")
            assert e.value.code == 404, bad

        # 4. ルートHTMLでは ?v= がアプリバージョンへ置換済み
        with urllib.request.urlopen(f"{base}/") as resp:
            html = resp.read().decode("utf-8")
        assert "__APP_VERSION__" not in html
        assert f"./vendor/tailwind.min.js?v={APP_VERSION}" in html
    finally:
        server.stop()
        core.shutdown()
        time.sleep(0.5)


def test_plugin_manifest_version_matches_app_version():
    """plugin/plugin.json の version が version.py と一致すること。

    VRCBeacon はこの値でプラグインの版数を表示・更新判定する。ここだけ手書きで、
    ZIP名が v2.9.7 でも中身は 2.7.0 のまま3リリース放置されていた。ビルド時は
    build_exe.py の sync_plugin_manifest_version() が追随させるが、ビルドを
    通さずに配る事故もあるので、テストでも止める。
    """
    path = os.path.join(BASE_DIR, "plugin", "plugin.json")
    with io.open(path, encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["version"] == APP_VERSION, \
        f"plugin.json の version が {manifest['version']}（version.py は {APP_VERSION}）"


def test_plugin_icon_is_current_brand():
    """プラグインのタイルアイコンが現行意匠であること。

    アプリの意匠を app_icon.ico / app_icon.png へ差し替えたとき、plugin/icon.svg
    だけ旧絵（YouTube風の赤いタイル）が残った。この絵は VRCBeacon のプラグイン
    一覧でしか出ないため、こちらの画面をいくら見ても気付けない。旧絵の目印
    だった赤(#FF0033)の不在と、現行の地色(#1F2531)の存在で検知する。
    """
    plugin_dir = os.path.join(BASE_DIR, "plugin")
    with io.open(os.path.join(plugin_dir, "plugin.json"), encoding="utf-8") as f:
        icon_name = json.load(f)["icon"]
    icon_path = os.path.join(plugin_dir, icon_name)
    assert os.path.isfile(icon_path), f"plugin.json の icon({icon_name}) が実在しない"
    with io.open(icon_path, encoding="utf-8") as f:
        svg = f.read().upper()
    assert "#FF0033" not in svg, "plugin/icon.svg が旧意匠（YouTube風の赤）のまま"
    assert "#1F2531" in svg, "plugin/icon.svg の地色が assets/app_icon.png と揃っていない"


# ---------------------------------------------------------------------------
# VRCBeacon 埋め込み時の資材（plugin/ 直下）
#
# Beacon の中では UI のオリジンが beacon-plugin://<プラグインid> になるため、
# ルート絶対パス（/app-mark.png）は api_server のルーティングを通らず、
# **プラグインフォルダの直下**を見に行く。写しが無いと Beacon の中だけ 404 になり、
# しかも Web リモコンでは出るので、こちらから再現しないと気付けない。
# ---------------------------------------------------------------------------

PLUGIN_DIR = os.path.join(BASE_DIR, "plugin")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")

# 既知のルート絶対参照。新しく増えたらここで落ちるので、そのとき
# 「plugin/ にも置く」か「置かない理由」かを決めることになる。
KNOWN_ROOT_ABSOLUTE_REFS = {"/app-mark.png", "/app-icon.png"}

# plugin/ 直下へ写す資材（配布名 -> 正本）。build_exe.py の PLUGIN_ROOT_ASSETS と同じ内容。
PLUGIN_ROOT_ASSETS = {"app-mark.png": os.path.join(ASSETS_DIR, "app_mark.png")}

# 写さないと決めたもの。favicon は iframe では使われないので、404 が 1 行出るだけ。
ROOT_ABSOLUTE_REFS_NOT_SHIPPED = {"/app-icon.png"}


def _root_absolute_refs():
    html = _read_ui_html()
    refs = re.findall(r"""(?:src|href)\s*=\s*["'](/[^"'?#]+)""", html)
    return {ref for ref in refs if not ref.startswith("//")}


def test_root_absolute_refs_are_known():
    """ルート絶対パスの参照が増えたら気付けること。"""
    refs = _root_absolute_refs()
    unknown = refs - KNOWN_ROOT_ABSOLUTE_REFS
    assert not unknown, (
        f"ルート絶対パスの参照が増えている: {sorted(unknown)}。"
        "Beacon の中ではオリジンが beacon-plugin:// になるので、plugin/ 直下へ写すか、"
        "写さない理由を決めて ROOT_ABSOLUTE_REFS_NOT_SHIPPED へ入れること"
    )


def test_plugin_root_assets_match_source():
    """plugin/ 直下の写しが正本と一致すること（更新漏れの検出）。"""
    for dist_name, source in PLUGIN_ROOT_ASSETS.items():
        dist_path = os.path.join(PLUGIN_DIR, dist_name)
        assert os.path.isfile(source), f"正本が無い: {source}"
        assert os.path.isfile(dist_path), (
            f"plugin/{dist_name} が無い。Beacon の中でだけ 404 になる"
            "（build_exe.py の sync_plugin_root_assets で写される）"
        )
        with open(source, "rb") as f:
            expected = f.read()
        with open(dist_path, "rb") as f:
            actual = f.read()
        assert actual == expected, (
            f"plugin/{dist_name} が正本と食い違っている。"
            f"{os.path.relpath(source, BASE_DIR)} を変えたら写しも更新すること"
        )


def test_not_shipped_refs_are_intentional():
    """写さないと決めた参照が、既知の一覧に含まれていること。"""
    assert ROOT_ABSOLUTE_REFS_NOT_SHIPPED <= KNOWN_ROOT_ABSOLUTE_REFS
    for ref in ROOT_ABSOLUTE_REFS_NOT_SHIPPED:
        assert ref.lstrip("/") not in PLUGIN_ROOT_ASSETS
