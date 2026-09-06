import os
import sys
import io
import json
import re
import time
import argparse
import subprocess
import shutil
import zipfile

if sys.platform == "win32" and sys.stdout is not None:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from version import APP_VERSION  # バージョンの正本は version.py（UI表記もここから配る）

# 配布物に含めてはいけない実行時生成物・作業ファイル。
# hls_output/ には利用者がアップロードした写真が溜まるため、同梱するとプライバシー漏洩になる。
EXCLUDED_DIRS = {"hls_output", "__pycache__", ".pytest_cache", ".git", "build"}
EXCLUDED_FILE_SUFFIXES = (".log", ".pyc", ".pyo", ".tmp")


def iter_packagable_files(root_dir):
    """配布ZIPに含めてよいファイルだけを列挙する。"""
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for file in files:
            if file.lower().endswith(EXCLUDED_FILE_SUFFIXES):
                continue
            yield os.path.join(root, file)


def sync_plugin_manifest_version(manifest_path, version=APP_VERSION):
    """plugin/plugin.json の version を version.py に合わせる。

    VRCBeacon はこの値でプラグインの版数を表示・更新判定する。ここだけ手書きだったため、
    ZIP名が v2.9.7 でも中身は 2.7.0 のまま、という乖離が3リリース続いた。
    json.load -> dump で書き戻すとキー順や整形が崩れて差分が読めなくなるので、
    version の値だけを置換する。
    """
    if not os.path.exists(manifest_path):
        print(f"[WARN] plugin.json not found: {manifest_path}", flush=True)
        return False
    with io.open(manifest_path, encoding="utf-8") as f:
        text = f.read()
    updated, hit = re.subn(r'("version"\s*:\s*")[^"]*(")',
                           lambda m: m.group(1) + version + m.group(2), text, count=1)
    if not hit:
        print("[WARN] plugin.json に version フィールドが無い（同期をスキップ）", flush=True)
        return False
    if updated == text:
        return False
    with io.open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(updated)
    print(f"[OK] Synced plugin.json version -> {version}", flush=True)
    return True


# VRCBeacon の中では UI のオリジンが beacon-plugin://<プラグインid> になる。
# ui/index.html がルート絶対パスで引く資材（/app-mark.png など）は api_server の
# ルーティングを通らず、**プラグインフォルダの直下**を見に行く。
# ここで写しておかないと、Web リモコンでは出るロゴが Beacon の中だけ 404 になる。
# 鍵が配布名、値が正本の場所。
PLUGIN_ROOT_ASSETS = {
    "app-mark.png": os.path.join("assets", "app_mark.png"),
}


def sync_plugin_root_assets(plugin_root):
    """ルート絶対パスで引かれる資材を plugin/ 直下へ写す。

    favicon（/app-icon.png）は写さない。iframe の中では favicon が使われないので、
    コンソールに 404 が 1 行出るだけで見た目に影響せず、18KB の重複が増えるだけになる。
    """
    copied = 0
    for dist_name, source_rel in PLUGIN_ROOT_ASSETS.items():
        source = os.path.abspath(source_rel)
        if not os.path.exists(source):
            print(f"[WARN] plugin root asset not found: {source_rel}", flush=True)
            continue
        shutil.copy2(source, os.path.join(plugin_root, dist_name))
        print(f"[OK] Copied {source_rel} -> plugin/{dist_name}", flush=True)
        copied += 1
    return copied


def write_dist_config(dest_path, overrides=None):
    """配布用テンプレート config.dist.json から設定ファイルを生成する。

    開発中の作業用 config.json をそのまま同梱すると、開発者のローカル設定
    (ポート・トンネル無効・ラジオ背景など) が配布物の既定値になってしまうため、
    配布用テンプレートを正本として分離している。
    """
    template = os.path.abspath("config.dist.json")
    if not os.path.exists(template):
        print("[WARN] config.dist.json not found; skipping config generation.", flush=True)
        return False
    with open(template, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    if overrides:
        cfg.update(overrides)
    with open(dest_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return True

def generate_startup_shortcuts(target_dir):
    """指定ディレクトリに各種起動用バッチファイルを作成"""
    os.makedirs(target_dir, exist_ok=True)
    
    # 1. ローカルテスト起動バッチ (トンネルなし)
    bat_local = os.path.join(target_dir, "VRC_Media_Streamer (Local Test).bat")
    with open(bat_local, "w", encoding="cp932", errors="replace") as f:
        f.write('@echo off\r\n'
                'echo ======================================================\r\n'
                'echo Starting VRC_Media_Streamer in Local Test Mode\r\n'
                'echo (Cloudflare Tunnel: DISABLED / LAN access: ENABLED)\r\n'
                'echo Local URL: http://localhost:8000/  (or the "port" in config.json)\r\n'
                'echo Phone/QR sharing works over the same Wi-Fi.\r\n'
                'echo ======================================================\r\n'
                'start "" "%~dp0VRC_Media_Streamer.exe" --no-tunnel --host 0.0.0.0\r\n')
    print(f"Created startup shortcut: {bat_local}", flush=True)

    # 2. 通常起動バッチ (トンネルあり)
    bat_normal = os.path.join(target_dir, "VRC_Media_Streamer (Normal).bat")
    with open(bat_normal, "w", encoding="cp932", errors="replace") as f:
        f.write('@echo off\r\n'
                'echo ======================================================\r\n'
                'echo Starting VRC_Media_Streamer in Normal Mode\r\n'
                'echo (Cloudflare Tunnel: ENABLED)\r\n'
                'echo ======================================================\r\n'
                'start "" "%~dp0VRC_Media_Streamer.exe" --tunnel\r\n')
    print(f"Created startup shortcut: {bat_normal}", flush=True)

    # 3. ヘッドレスローカル起動バッチ
    bat_headless = os.path.join(target_dir, "VRC_Media_Streamer (Headless Test).bat")
    with open(bat_headless, "w", encoding="cp932", errors="replace") as f:
        f.write('@echo off\r\n'
                'echo ======================================================\r\n'
                'echo Starting VRC_Media_Streamer in Headless Local Mode\r\n'
                'echo (Cloudflare Tunnel: DISABLED, GUI: DISABLED / LAN access: ENABLED)\r\n'
                'echo Local URL: http://localhost:8000/  (or the "port" in config.json)\r\n'
                'echo ======================================================\r\n'
                '"%~dp0VRC_Media_Streamer.exe" --headless --no-tunnel --host 0.0.0.0\r\n'
                'pause\r\n')
    print(f"Created startup shortcut: {bat_headless}", flush=True)

def generate_root_shortcuts():
    """プロジェクトルート用のPython直接起動ショートカット"""
    bat_root_local = os.path.abspath("Start_LocalTest.bat")
    with open(bat_root_local, "w", encoding="cp932", errors="replace") as f:
        f.write('@echo off\r\n'
                'cd /d "%~dp0"\r\n'
                'echo Starting VRC_Media_Streamer in Local Test Mode (No Tunnel)...\r\n'
                'python gui_streamer.py --no-tunnel\r\n'
                'pause\r\n')

    bat_root_normal = os.path.abspath("Start_Normal.bat")
    with open(bat_root_normal, "w", encoding="cp932", errors="replace") as f:
        f.write('@echo off\r\n'
                'cd /d "%~dp0"\r\n'
                'echo Starting VRC_Media_Streamer (Normal Mode - Tunnel Enabled)...\r\n'
                'python gui_streamer.py --tunnel\r\n'
                'pause\r\n')

def _find_bundled_tool(name):
    """ローカル / dist / PATH の順に <name>.exe を探す"""
    local = os.path.abspath(f"{name}.exe")
    if os.path.exists(local):
        return local
    dist_local = os.path.abspath(f"dist/{name}.exe")
    if os.path.exists(dist_local):
        return dist_local
    found = shutil.which(name)
    if found:
        if sys.platform == "win32" and not found.lower().endswith(".exe"):
            found_exe = found + ".exe"
            if os.path.exists(found_exe):
                return found_exe
        if os.path.exists(found):
            return found
    return None

def get_ffmpeg_source():
    """ローカルまたはPATH内のffmpeg.exeパスを取得"""
    return _find_bundled_tool("ffmpeg")

def get_ffprobe_source():
    """ローカルまたはPATH内のffprobe.exeパスを取得。

    ffprobe が同梱されていないと streamer_core は `ffmpeg -i` フォールバックに
    落ちる。実測でローカルSSDでも約3秒（ffprobe は約0.3秒）かかり、外付けHDDや
    USB上の長尺ファイルでは probe タイムアウトに達して尺が取れなくなるため、
    ffmpeg と必ず対で配布する。
    """
    return _find_bundled_tool("ffprobe")

def get_app_audio_capture_source():
    """アプリ単位の音声取り込み補助exe（タスク25）のパスを取得。

    .gitignore が *.exe を全除外しているためリポジトリには入らない。
    native/app_audio_capture/build.bat でビルドした成果物をここから拾う。
    無ければ同梱を省く（実行時に自動で従来のdshow経路へ落ちる）。
    """
    local = os.path.abspath(os.path.join(
        "native", "app_audio_capture", "build", "app_audio_capture.exe"))
    if os.path.exists(local):
        return local
    return _find_bundled_tool("app_audio_capture")

def get_window_capture_source():
    """ウィンドウ単位キャプチャ補助exe（タスク26）のパスを取得。

    無ければ同梱を省く（実行時に自動で従来のデスクトップ切り出しへ落ちる。
    ただし手前に重なったウィンドウが映るようになる）。
    """
    local = os.path.abspath(os.path.join(
        "native", "window_capture", "build", "window_capture.exe"))
    if os.path.exists(local):
        return local
    return _find_bundled_tool("window_capture")

def copy_media_tools(target_dir, label):
    """ffmpeg.exe / ffprobe.exe を配布先へコピーする"""
    for name, finder in (("ffmpeg", get_ffmpeg_source), ("ffprobe", get_ffprobe_source)):
        src_path = finder()
        if src_path and os.path.exists(src_path):
            shutil.copy2(src_path, os.path.join(target_dir, f"{name}.exe"))
            print(f"[OK] Copied {name}.exe -> {label}", flush=True)
        else:
            print(f"[WARN] {name}.exe was not found to package.", flush=True)

    # 補助exeは「無ければ機能が無効になるだけ」なので、欠けても配布は止めない。
    app_audio = get_app_audio_capture_source()
    if app_audio and os.path.exists(app_audio):
        shutil.copy2(app_audio, os.path.join(target_dir, "app_audio_capture.exe"))
        print(f"[OK] Copied app_audio_capture.exe -> {label}", flush=True)
    else:
        print("[WARN] app_audio_capture.exe was not found. "
              "アプリ単位の音声取り込みは無効のまま配布されます "
              "(native/app_audio_capture/build.bat でビルドしてください)。", flush=True)

    window_capture = get_window_capture_source()
    if window_capture and os.path.exists(window_capture):
        shutil.copy2(window_capture, os.path.join(target_dir, "window_capture.exe"))
        print(f"[OK] Copied window_capture.exe -> {label}", flush=True)
    else:
        print("[WARN] window_capture.exe was not found. "
              "ウィンドウ取り込みは従来のデスクトップ切り出しになり、"
              "手前に重なったウィンドウが映ります "
              "(native/window_capture/build.bat でビルドしてください)。", flush=True)

def package_plugin(version=APP_VERSION):
    """plugin/ フォルダの資材を整理し、VRCBeacon用プラグインZIPパッケージを生成"""
    plugin_root = os.path.abspath("plugin")
    plugin_bin = os.path.join(plugin_root, "bin")
    releases_root = os.path.abspath("releases")
    os.makedirs(plugin_bin, exist_ok=True)
    os.makedirs(releases_root, exist_ok=True)

    print(f"\n==================================================", flush=True)
    print(f"Packaging VRCBeacon Plugin for v{version}...", flush=True)
    print(f"==================================================", flush=True)

    # 1. UI 資材 (ui/index.html) を plugin/ui/ へ同期
    src_ui = os.path.abspath("ui/index.html")
    plugin_ui_dir = os.path.join(plugin_root, "ui")
    os.makedirs(plugin_ui_dir, exist_ok=True)
    if os.path.exists(src_ui):
        shutil.copy2(src_ui, os.path.join(plugin_ui_dir, "index.html"))
        print("[OK] Copied ui/index.html -> plugin/ui/index.html", flush=True)

    # index.html は Tailwind / RemixIcon / hls.js を ./vendor/ から読む。
    # ここを同期し忘れると、プラグイン配布側だけ CDN フォールバックに落ち、
    # オフライン環境で UI が素の HTML になる（症状が出るのは配布後）。
    src_vendor = os.path.abspath(os.path.join("ui", "vendor"))
    if os.path.isdir(src_vendor):
        dst_vendor = os.path.join(plugin_ui_dir, "vendor")
        if os.path.isdir(dst_vendor):
            shutil.rmtree(dst_vendor, ignore_errors=True)
        shutil.copytree(src_vendor, dst_vendor)
        print(f"[OK] Copied ui/vendor/ -> plugin/ui/vendor/ "
              f"({len(os.listdir(dst_vendor))} files)", flush=True)
    else:
        print("[WARN] ui/vendor/ not found; plugin UI will fall back to CDN.", flush=True)

    # ルート絶対パスで引かれる資材（/app-mark.png）を plugin/ 直下へ。
    # Beacon の中ではオリジンが変わり、api_server のルーティングを通らないため。
    sync_plugin_root_assets(plugin_root)

    # 2. dist/ から plugin/bin/ へバイナリを同期
    src_exe = os.path.abspath("dist/VRC_Media_Streamer.exe")
    if os.path.exists(src_exe):
        shutil.copy2(src_exe, os.path.join(plugin_bin, "VRC_Media_Streamer.exe"))
        print("[OK] Copied VRC_Media_Streamer.exe -> plugin/bin/", flush=True)

    copy_media_tools(plugin_bin, "plugin/bin/")

    # プラグインは VRCBeacon がローカルでプロセス起動するため、
    # plugin.json の --port 8000 に合わせつつトンネルは既定で無効にする。
    if write_dist_config(os.path.join(plugin_bin, "config.json"), {"enable_tunnel": False}):
        print("[OK] Generated config.json from config.dist.json -> plugin/bin/", flush=True)

    # 実行時に生成された写真・HLSセグメントを配布物へ混入させない
    stale_runtime = os.path.join(plugin_bin, "hls_output")
    if os.path.isdir(stale_runtime):
        shutil.rmtree(stale_runtime, ignore_errors=True)
        print("[OK] Removed runtime artifacts: plugin/bin/hls_output/", flush=True)

    # plugin.json の版数を version.py に追随させてから固める。
    # ui / bin / config.json は同期していたのにここだけ手書きで、更新漏れの常習箇所だった。
    sync_plugin_manifest_version(os.path.join(plugin_root, "plugin.json"), version)

    # 3. プラグインZIPアーカイブ作成
    zip_path = os.path.join(releases_root, f"vrcbeacon-plugin-vrc-media-streamer-v{version}.zip")
    print(f"Creating Plugin ZIP archive: {zip_path} ...", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in iter_packagable_files(plugin_root):
                arcname = os.path.relpath(file_path, plugin_root)
                zf.write(file_path, arcname)
        print(f"[OK] Successfully generated Plugin ZIP: {zip_path}", flush=True)
    except Exception as e:
        print(f"[WARN] Failed to create Plugin ZIP: {e}", flush=True)

def create_versioned_release(version=APP_VERSION):
    """releases/VRC_Media_Streamer_v{version}/ 配布用パッケージおよび ZIP を生成"""
    release_dir_name = f"VRC_Media_Streamer_v{version}"
    releases_root = os.path.abspath("releases")
    target_dir = os.path.join(releases_root, release_dir_name)
    os.makedirs(target_dir, exist_ok=True)

    print(f"\n==================================================", flush=True)
    print(f"Creating Release Package for v{version}...", flush=True)
    print(f"Target Directory: {target_dir}", flush=True)
    print(f"==================================================", flush=True)

    # 1. EXE のコピー
    src_exe = os.path.abspath("dist/VRC_Media_Streamer.exe")
    if os.path.exists(src_exe):
        shutil.copy2(src_exe, os.path.join(target_dir, "VRC_Media_Streamer.exe"))
        print("[OK] Copied VRC_Media_Streamer.exe", flush=True)
    else:
        print("[WARN] dist/VRC_Media_Streamer.exe not found!", flush=True)

    # 2. ffmpeg.exe のコピー
    copy_media_tools(target_dir, os.path.basename(target_dir) + "/")

    # 3. config.json の生成 (配布用テンプレート config.dist.json から)
    if write_dist_config(os.path.join(target_dir, "config.json")):
        print("[OK] Generated config.json from config.dist.json", flush=True)

    # 4. ドキュメント類のコピー
    #    正本はリポジトリ直下に置く。dist/ は .gitignore 対象のビルド成果物であり、
    #    そこにしか無いドキュメントはクリーンビルドで失われるため、直下 → dist の順で探す。
    doc_candidates = [
        ["README.txt", "dist/README.txt"],
        ["FFmpeg_LICENSE.txt", "dist/FFmpeg_LICENSE.txt"],
        # v2.1.0 以降このファイルが配布物から抜けていた。README の「内容物」には
        # 載ったままで、同梱ライブラリの帰属表示が配布物に無い状態だった。
        ["THIRD_PARTY_LICENSES.txt", "dist/THIRD_PARTY_LICENSES.txt"],
        # CHANGELOG.md / README.md は同梱しない。配布物の説明書は README.txt が正本で、
        # .md を入れると同じ内容が二重に載り、更新漏れでどちらが正しいのか分からなくなる。
        # 更新履歴は GitHub の CHANGELOG.md を参照してもらう（README.txt 末尾にリンクあり）。
    ]
    for candidates in doc_candidates:
        for doc in candidates:
            if os.path.exists(doc):
                dest_name = os.path.basename(doc)
                shutil.copy2(doc, os.path.join(target_dir, dest_name))
                print(f"[OK] Copied {dest_name} (from {doc})", flush=True)
                break
        else:
            print(f"[WARN] Document not found: {candidates[0]}", flush=True)

    # 5. 各種起動用バッチファイルの生成
    generate_startup_shortcuts(target_dir)

    # 6. ZIP アーカイブの生成
    zip_path = os.path.join(releases_root, f"{release_dir_name}.zip")
    print(f"Creating ZIP archive: {zip_path} ...", flush=True)
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in iter_packagable_files(target_dir):
                arcname = os.path.relpath(file_path, releases_root)
                zf.write(file_path, arcname)
        print(f"[OK] Successfully generated ZIP: {zip_path}", flush=True)
    except Exception as e:
        print(f"[WARN] Failed to create ZIP archive: {e}", flush=True)

    # 7. プラグインパッケージの作成
    package_plugin(version)

    # 8. 配布物のスモークテスト
    if not verify_release(target_dir):
        print("[FAIL] Release verification failed. See errors above.", flush=True)
        sys.exit(1)

    print(f"\n==================================================", flush=True)
    print(f"Release v{version} package created successfully!", flush=True)
    print(f"Folder: {target_dir}")
    print(f"Zip:    {zip_path}")
    print(f"==================================================\n", flush=True)

def verify_release(target_dir, port=8991, timeout=45):
    """ビルドした配布物を実際に起動し、Web リモコン UI が正しく配信されるか検証する。

    v2.6.0 では (1) ui/index.html が EXE に同梱されず (2) 代替の内蔵テンプレートが
    <body> ごと壊れていた、という2つの不具合が配布物にそのまま乗った。
    どちらも「起動して GET / の中身を見る」だけで検出できるため、ビルドの一部として常に実行する。
    """
    import urllib.request

    exe_path = os.path.join(target_dir, "VRC_Media_Streamer.exe")
    ui_path = os.path.abspath(os.path.join("ui", "index.html"))

    print(f"\n==================================================", flush=True)
    print(f"Verifying release package...", flush=True)
    print(f"==================================================", flush=True)

    if not os.path.exists(exe_path):
        print(f"[FAIL] {exe_path} not found.", flush=True)
        return False
    if not os.path.exists(ui_path):
        print(f"[FAIL] {ui_path} not found (UI source of truth is missing).", flush=True)
        return False

    with open(ui_path, "r", encoding="utf-8") as f:
        expected_ui = f.read()

    proc = subprocess.Popen(
        [exe_path, "--headless", "--no-tunnel", "--port", str(port), "--host", "127.0.0.1"],
        cwd=target_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        served = None
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=3) as r:
                    served = r.read().decode("utf-8")
                break
            except Exception:
                time.sleep(1)

        if served is None:
            print(f"[FAIL] Server did not respond on port {port} within {timeout}s.", flush=True)
            return False

        # 1. 配信された HTML が UI 正本と一致するか
        #    (api_server 側で __TUNNEL_STREAM_URL__ 等が置換されるため、その分だけ差異を許容)
        normalized = expected_ui
        for placeholder in ("__LIVE_SYNC_DURATION_COUNT__", "__TUNNEL_STREAM_URL__"):
            normalized = normalized.replace(placeholder, "")
        served_stripped = served
        if len(served_stripped) < len(normalized) * 0.9:
            print(f"[FAIL] Served UI is too small: {len(served)} chars "
                  f"(expected around {len(expected_ui)}). "
                  f"ui/index.html is probably not bundled into the EXE.", flush=True)
            return False

        # 2. HTML として壊れていないか (script タグの開閉が釣り合っているか)
        opens = served.count("<script")
        closes = served.count("</script>")
        if opens != closes:
            print(f"[FAIL] Malformed HTML: {opens} '<script' vs {closes} '</script>'.", flush=True)
            return False
        for tag in ("<body", "</body>", "</html>"):
            if tag not in served:
                print(f"[FAIL] Malformed HTML: '{tag}' is missing from the served page.", flush=True)
                return False

        # 3. CORS ヘッダが重複していないか (複数の ACAO はブラウザの CORS を失敗させる)
        #    ★/api/status は GET / より遅れて使えるようになる。ポートが開いた直後の
        #      約2秒間、この経路だけが RemoteDisconnected で切れる（実測: Listening の
        #      2秒後に出る `[Encoder] Probe ...` と窓が一致する。エンコーダープローブが
        #      起動経路で実エンコードを1回走らせるため）。
        #      GET / と同じようにここも待つ。1回だけ叩くと、ビルドが機嫌次第で落ちる。
        acao = None
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as r:
                    acao = r.headers.get_all("Access-Control-Allow-Origin") or []
                break
            except Exception as e:
                last_err = e
                time.sleep(1)
        if acao is None:
            print(f"[FAIL] /api/status did not respond within {timeout}s: {last_err}", flush=True)
            return False
        if len(acao) != 1:
            print(f"[FAIL] Access-Control-Allow-Origin appears {len(acao)} times (must be exactly 1).", flush=True)
            return False

        # 4. 同梱アセット (Tailwind / RemixIcon / hls.js) が EXE から配信できるか
        #    v2.6.0 の「UI が EXE に入っていなかった」と同じ事故が vendor/ でも起こり得る。
        #    こちらは CDN フォールバックがあるぶん online では気付けず、
        #    オフラインの利用者環境でだけ UI が崩れるので、ビルド時に必ず確かめる。
        vendor_refs = sorted(set(re.findall(r"\./vendor/([A-Za-z0-9_.-]+)", expected_ui)))
        if not vendor_refs:
            print("[FAIL] ui/index.html does not reference any ./vendor/ asset "
                  "(reverted to CDN links?).", flush=True)
            return False
        for name in vendor_refs:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/vendor/{name}", timeout=5) as r:
                    size = len(r.read())
                    if r.status != 200 or size < 1024:
                        print(f"[FAIL] Vendor asset /vendor/{name}: status={r.status}, {size} bytes.", flush=True)
                        return False
            except Exception as e:
                print(f"[FAIL] Vendor asset /vendor/{name} is not served: {e}", flush=True)
                return False

        print(f"[OK] Served UI: {len(served)} chars, script tags balanced ({opens}/{closes}).", flush=True)
        print(f"[OK] Bundled vendor assets served: {', '.join(vendor_refs)}", flush=True)
        print(f"[OK] CORS headers are not duplicated.", flush=True)
        print(f"[OK] Release package verified.", flush=True)
        return True
    finally:
        # まず /api/shutdown で正規終了させる。proc.terminate() だけでは
        # 子プロセスの ffmpeg が生き残り、hls_output/ を掴んだままになる。
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/shutdown",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5).read()
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        # 検証のために起動したことで生成された実行時ファイルを配布フォルダから除去する。
        # ffmpeg のファイルハンドル解放にわずかに遅れることがあるため数回リトライする。
        for artifact in ("hls_output",):
            stale = os.path.join(target_dir, artifact)
            for attempt in range(5):
                if not os.path.isdir(stale):
                    break
                shutil.rmtree(stale, ignore_errors=True)
                if os.path.isdir(stale):
                    time.sleep(1)
            if os.path.isdir(stale):
                print(f"[WARN] Could not remove runtime artifacts: {stale}", flush=True)

        # 検証起動によって config.json に実行時の値が書き戻されていないか確認し、
        # 差異があればテンプレートから生成し直す。
        write_dist_config(os.path.join(target_dir, "config.json"))


def build(version=APP_VERSION):
    print(f"Starting PyInstaller build process for v{version}...", flush=True)
    
    try:
        import PyInstaller
        print(f"PyInstaller is already installed (version: {PyInstaller.__version__})", flush=True)
    except ImportError:
        print("PyInstaller is not installed. Installing it via pip...", flush=True)
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("Successfully installed PyInstaller.", flush=True)
        except Exception as e:
            print(f"Failed to install PyInstaller: {e}", flush=True)
            sys.exit(1)

    # モダンUI（WebView2 ホスト画面）の依存。無いまま黙ってビルドすると、
    # 配布物だけが従来の CustomTkinter 画面に落ちる——しかも起動はするので
    # 気付けない。ここで止めるか入れるかを必ず決める。
    try:
        import webview  # noqa: F401
        print("pywebview is already installed (modern host UI enabled)", flush=True)
    except ImportError:
        print("pywebview is not installed. Installing it via pip...", flush=True)
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pywebview"], check=True)
            print("Successfully installed pywebview.", flush=True)
        except Exception as e:
            print(f"Failed to install pywebview: {e}", flush=True)
            print("      -> The build would silently fall back to the classic UI. Aborting.", flush=True)
            sys.exit(1)

    cmd = [
        "pyinstaller",
        "--onefile",
        "--noconsole",
        "--name", "VRC_Media_Streamer",
        # EXE / タスクバー / Alt+Tab のアイコン。WebViewホスト画面のウィンドウアイコンも
        # ここから来る（pywebview 側で個別指定する経路が無いため）。
        "--icon", os.path.abspath(os.path.join("assets", "app_icon.ico")),
        "--add-data", "cloudflared.exe;.",
        "--add-data", "ui;ui",
        "--add-data", "assets;assets",
        "--collect-all", "customtkinter",
        "--collect-all", "qrcode",
        "--collect-all", "PIL",
        # モダンUI（WebView2 ホスト画面）。pywebview は実行時に
        # webview.platforms.winforms と pythonnet(clr) を動的 import するため、
        # 明示しないと EXE に入らず、配布物だけ従来画面へ落ちる。
        "--collect-all", "webview",
        "--collect-all", "clr_loader",
        "--hidden-import", "clr",
        "--clean",
        "gui_streamer.py"
    ]
    
    print(f"Running command: {' '.join(cmd)}", flush=True)
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("pyinstaller command not found in PATH. Retrying with python -m PyInstaller...", flush=True)
        cmd[0:1] = [sys.executable, "-m", "PyInstaller"]
        print(f"Running command: {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True)

    # dist フォルダの更新
    generate_startup_shortcuts(os.path.abspath("dist"))
    generate_root_shortcuts()
    try:
        copy_media_tools(os.path.abspath("dist"), "dist/")
    except Exception:
        pass

    # バージョン別配布用パッケージ (releases/VRC_Media_Streamer_v<version>/) の生成
    create_versioned_release(version)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and Package VRC_Media_Streamer")
    parser.add_argument("--version", "-v", type=str, default=APP_VERSION, help=f"Release version string (default: {APP_VERSION})")
    parser.add_argument("--package-only", action="store_true", help="Skip PyInstaller build and only package existing dist/ files")
    parser.add_argument("--plugin-only", action="store_true", help="Package only the VRCBeacon plugin")
    args = parser.parse_args()

    if args.plugin_only:
        package_plugin(args.version)
    elif args.package_only:
        create_versioned_release(args.version)
    else:
        build(args.version)
