"""Bounded, app-owned video downloads; streaming remains a separate path."""
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid


class VideoDownloadError(Exception):
    """A message safe to show in the host UI."""


class SafeVideoRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, validate):
        self.validate = validate

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validate(newurl)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        old_origin = urllib.parse.urlsplit(req.full_url)
        new_origin = urllib.parse.urlsplit(newurl)
        if redirected and (old_origin.scheme, old_origin.netloc) != (new_origin.scheme, new_origin.netloc):
            for name in list(redirected.headers):
                if name.lower() in ("authorization", "cookie", "proxy-authorization"):
                    redirected.remove_header(name)
        return redirected


class TemporaryVideoDownloads:
    def __init__(self, root, validator):
        self.root = root
        self.validator = validator
        self.lock = threading.Lock()
        self.cancelled = threading.Event()

    def close(self):
        # Workers check cancellation before creating files, writing and enqueueing.
        # A resolver still finishing has no files yet; an active read times out.
        self.cancelled.set()
        if self.lock.acquire(timeout=12):
            self.lock.release()

    def validate(self, url):
        safe, _ = self.validator(url)
        if not safe:
            raise VideoDownloadError("安全でない動画URLまたは転送先です。")

    def checkpoint(self, deadline):
        if self.cancelled.is_set():
            raise VideoDownloadError("終了処理のためダウンロードを中止しました。")
        if time.monotonic() > deadline:
            raise VideoDownloadError("動画のダウンロードが制限時間を超えました。")

    def fetch(self, url, target, headers, remaining, deadline):
        self.validate(url)
        self.checkpoint(deadline)
        opener = urllib.request.build_opener(SafeVideoRedirect(self.validate))
        req = urllib.request.Request(url, headers=headers or {})
        total = 0
        with opener.open(req, timeout=10) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > remaining:
                raise VideoDownloadError("動画がダウンロード容量上限を超えています。")
            content_type = response.headers.get("Content-Type", "").lower()
            if "text/html" in content_type or "mpegurl" in content_type or "dash+xml" in content_type:
                raise VideoDownloadError("直接取得できる動画ファイルではありません。通常の追加をお使いください。")
            self.checkpoint(deadline)
            with open(target, "wb") as output:
                while True:
                    self.checkpoint(deadline)
                    # read1 returns available bytes, so a slow trickle cannot
                    # postpone cancellation until an entire buffer is filled.
                    chunk = response.read1(256 * 1024)
                    self.checkpoint(deadline)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > remaining:
                        raise VideoDownloadError("動画がダウンロード容量上限を超えています。")
                    output.write(chunk)
        if not total or (length and total != int(length)):
            raise VideoDownloadError("動画ファイルを最後まで取得できませんでした。")
        return total

    def run_local(self, command, deadline):
        self.checkpoint(deadline)
        flags = 0x08000000 if os.name == "nt" else 0
        # No remote inputs, stdin prompts or unbounded subprocess output.
        with subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, creationflags=flags) as process:
            try:
                while True:
                    self.checkpoint(deadline)
                    try:
                        out, _ = process.communicate(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        continue
                if process.returncode:
                    raise VideoDownloadError("動画の結合または検証に失敗しました。")
                return out
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=5)

    def prepare(self, url, resolver, max_mb, ffmpeg, ffprobe, enqueue):
        """Resolve, acquire and enqueue under one lock; failures own their cleanup."""
        if not self.lock.acquire(blocking=False):
            raise VideoDownloadError("別の動画をダウンロード中です。完了後に追加してください。")
        workdir = None
        committed = False
        deadline = time.monotonic() + 30 * 60
        try:
            self.checkpoint(deadline)
            self.validate(url)
            try:
                if isinstance(max_mb, bool) or float(max_mb) <= 0:
                    raise ValueError()
                limit = int(float(max_mb) * 1024 * 1024)
                if limit <= 0:
                    raise ValueError()
            except (TypeError, ValueError, OverflowError):
                raise VideoDownloadError("max_video_download_mb に正の容量上限を設定してください。") from None

            parsed = urllib.parse.urlsplit(url)
            direct = parsed.path.lower().endswith((".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".ts", ".flv"))
            if parsed.hostname in ("www.dropbox.com", "dropbox.com"):
                query = dict(urllib.parse.parse_qsl(parsed.query))
                query.pop("dl", None)
                query["raw"] = "1"
                url = urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))
                direct = True
            info = {"url": url, "title": urllib.parse.unquote(os.path.basename(parsed.path)) or "ダウンロード動画",
                    "protocol": urllib.parse.urlsplit(url).scheme,
                    "ext": os.path.splitext(parsed.path)[1].lstrip(".").lower()} if direct else resolver(url)
            self.checkpoint(deadline)
            if not isinstance(info, dict) or info.get("entries") is not None or info.get("_type") in ("playlist", "multi_video"):
                raise VideoDownloadError("ダウンロードは単独の動画URLに対応しています。")
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
                raise VideoDownloadError("ライブ配信はダウンロード対象外です。通常の追加をお使いください。")
            formats = info.get("requested_formats") or [info]
            if not 1 <= len(formats) <= 2:
                raise VideoDownloadError("この動画形式のダウンロードには対応していません。")
            formats = sorted(formats, key=lambda fmt: fmt.get("vcodec") == "none")
            for fmt in formats:
                media_url = fmt.get("url", "")
                self.validate(media_url)
                protocol = fmt.get("protocol", urllib.parse.urlsplit(media_url).scheme)
                if protocol not in ("http", "https") or fmt.get("fragments") or urllib.parse.urlsplit(media_url).path.lower().endswith((".m3u8", ".mpd")):
                    raise VideoDownloadError("この配信形式は通常の追加で再生してください（ダウンロード対象外）。")

            self.checkpoint(deadline)
            workdir = os.path.join(self.root, uuid.uuid4().hex)
            os.makedirs(workdir)
            remaining = limit
            paths = []
            for index, fmt in enumerate(formats):
                path = os.path.join(workdir, f"track{index}.part")
                headers = dict(info.get("http_headers") or {})
                headers.update(fmt.get("http_headers") or {})
                remaining -= self.fetch(fmt["url"], path, headers, remaining, deadline)
                paths.append(path)
            ext = info.get("ext", "mkv")
            if len(paths) == 2 or ext not in ("mp4", "mov", "webm", "mkv", "avi", "m4v", "ts", "flv"):
                ext = "mkv"
            output = os.path.join(workdir, f"video.{ext}")
            if len(paths) == 2:
                command = [ffmpeg, "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe", "-i", paths[0],
                           "-protocol_whitelist", "file,pipe", "-i", paths[1], "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-y", output]
                self.run_local(command, min(deadline, time.monotonic() + 120))
                for path in paths:
                    os.remove(path)
            else:
                # Probe determines the format; use a fixed, app-owned filename.
                os.replace(paths[0], output)
            probe = self.run_local([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries",
                                    "stream=codec_type:format=duration", "-of", "json", output],
                                   min(deadline, time.monotonic() + 20))
            metadata = json.loads(probe)
            if not any(s.get("codec_type") == "video" for s in metadata.get("streams", [])):
                raise VideoDownloadError("取得したファイルに動画が含まれていません。")
            duration = float(metadata.get("format", {}).get("duration", 0))
            self.checkpoint(deadline)
            item = enqueue(output, info.get("title") or "ダウンロード動画", duration)
            if not item:
                raise VideoDownloadError("キューが満杯、またはソフトが終了処理中です。")
            committed = True
            return [item]
        except VideoDownloadError:
            raise
        except Exception:
            raise VideoDownloadError("動画を取得できませんでした。URL・接続・空き容量を確認してください。") from None
        finally:
            if workdir and not committed:
                shutil.rmtree(workdir, ignore_errors=True)
            self.lock.release()
