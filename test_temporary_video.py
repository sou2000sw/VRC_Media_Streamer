import io
import json
import os
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import api_server
import streamer_core as sc
from temporary_video import TemporaryVideoDownloads, SafeVideoRedirect, VideoDownloadError


@pytest.fixture
def core(tmp_path, monkeypatch):
    hls = tmp_path / "hls"
    monkeypatch.setattr(sc, "HLS_DIR", str(hls))
    monkeypatch.setattr(sc, "VIDEO_STORAGE_DIR", str(hls / "videos"))
    monkeypatch.setattr(sc, "IMAGE_CACHE_DIR", str(hls / "images"))
    monkeypatch.setattr(sc, "STANDBY_IMAGE_PATH", str(hls / "standby.png"))
    monkeypatch.setattr(sc, "is_safe_url", lambda url: (url.startswith("https://public.example/"), ""))
    c = sc.StreamerCore(override_enable_tunnel=False)
    c.play_queue.clear()
    yield c
    c.shutdown()


class Response(io.BytesIO):
    def __init__(self, data=b"video", length=True):
        super().__init__(data)
        self.headers = {"Content-Type": "video/mp4"}
        if length:
            self.headers["Content-Length"] = str(len(data))


def network(monkeypatch, factory=lambda: Response()):
    opener = MagicMock()
    opener.open.side_effect = lambda *a, **kw: factory()
    monkeypatch.setattr("temporary_video.urllib.request.build_opener", lambda *a: opener)
    return opener


def probe(monkeypatch, core):
    monkeypatch.setattr(core.video_downloads, "run_local", lambda *a: json.dumps(
        {"streams": [{"codec_type": "video"}], "format": {"duration": "12.5"}}).encode())


def test_download_is_local_and_survives_queue_removal(core, monkeypatch):
    network(monkeypatch)
    probe(monkeypatch, core)
    item = core.download_video_to_queue("https://public.example/movie.mp4")[0]
    assert item["is_local"] and item["is_downloaded"] and not item["is_uploaded"]
    assert item["source_url"] == "https://public.example/movie.mp4"
    assert item["duration"] == 12.5
    assert Path(item["path"]).read_bytes() == b"video"
    core.delete_queue_item(0)
    assert os.path.exists(item["path"])
    core.clean_hls_dir(all_files=True, preserve_images=True)
    assert os.path.exists(item["path"])
    core.shutdown()
    assert not os.path.exists(item["path"])


@pytest.mark.parametrize("length", [True, False])
def test_size_limit_removes_partial(core, monkeypatch, length):
    core.config["max_video_download_mb"] = 3 / (1024 * 1024)
    network(monkeypatch, lambda: Response(b"four", length))
    with pytest.raises(VideoDownloadError, match="容量上限"):
        core.download_video_to_queue("https://public.example/movie.mp4")
    assert not core.play_queue
    assert not list(Path(core.video_downloads.root).rglob("*"))


def test_failure_does_not_add_or_keep_files(core, monkeypatch):
    network(monkeypatch, lambda: Response(b""))
    with pytest.raises(VideoDownloadError):
        core.download_video_to_queue("https://public.example/movie.mp4")
    assert not core.play_queue
    assert not list(Path(core.video_downloads.root).rglob("*"))


@pytest.mark.parametrize("metadata", [
    {"is_live": True, "url": "https://public.example/video"},
    {"_type": "playlist", "entries": []},
    {"url": "https://public.example/index.m3u8", "protocol": "m3u8_native"},
    {"url": "http://127.0.0.1/private"},
])
def test_unsupported_metadata_rejected_before_fetch(core, monkeypatch, metadata):
    ydl = MagicMock()
    ydl.__enter__.return_value.extract_info.return_value = metadata
    monkeypatch.setattr(sc.yt_dlp, "YoutubeDL", lambda *a: ydl)
    opener = network(monkeypatch)
    with pytest.raises(VideoDownloadError):
        core.download_video_to_queue("https://public.example/watch")
    opener.open.assert_not_called()
    assert not core.play_queue


def test_redirect_validator_blocks_private_target(core):
    import urllib.request
    handler = SafeVideoRedirect(core.video_downloads.validate)
    with pytest.raises(VideoDownloadError):
        handler.redirect_request(urllib.request.Request("https://public.example/video"), None,
                                 302, "Found", {}, "http://127.0.0.1/private")


def test_shutdown_mid_read_cleans_and_does_not_enqueue(core, monkeypatch):
    class CancellingResponse(Response):
        def read1(self, size):
            core.shutdown()
            return super().read1(size)

    # Avoid waiting on the same synchronous worker in this deterministic test.
    monkeypatch.setattr(core.video_downloads, "close", lambda: core.video_downloads.cancelled.set())
    network(monkeypatch, CancellingResponse)
    with pytest.raises(VideoDownloadError, match="中止"):
        core.download_video_to_queue("https://public.example/movie.mp4")
    assert not core.play_queue
    assert not list(Path(core.video_downloads.root).rglob("*.part"))


def test_original_video_preserved_on_shutdown(core, tmp_path, monkeypatch):
    original = tmp_path / "original.mp4"
    original.write_bytes(b"original")
    monkeypatch.setattr(sc, "get_video_file_duration", lambda *a: 1)
    core.add_video_file(str(original))
    core.clear_queue()
    core.shutdown()
    assert original.read_bytes() == b"original"


def test_stale_files_removed_on_startup(core):
    stale = os.path.join(core.video_downloads.root, "stale", "track.part")
    os.makedirs(os.path.dirname(stale))
    with open(stale, "wb") as output:
        output.write(b"stale")
    next_core = sc.StreamerCore(override_enable_tunnel=False)
    assert not os.path.exists(stale)
    next_core.shutdown()


def test_queue_capacity_rechecked_after_download(core, monkeypatch):
    network(monkeypatch)
    def fill_queue(*args):
        core.play_queue.extend({"title": "existing"} for _ in range(sc.MAX_QUEUE_CAPACITY))
        return b'{"streams":[{"codec_type":"video"}],"format":{"duration":"1"}}'
    monkeypatch.setattr(core.video_downloads, "run_local", fill_queue)
    with pytest.raises(VideoDownloadError, match="満杯"):
        core.download_video_to_queue("https://public.example/movie.mp4")
    assert len(core.play_queue) == sc.MAX_QUEUE_CAPACITY
    assert not list(Path(core.video_downloads.root).rglob("*"))


def queue_request(core, body, local=True):
    handler = object.__new__(api_server.APIAndHLSHandler)
    encoded = json.dumps(body).encode()
    handler.path = "/api/queue"
    handler.headers = {"Content-Length": str(len(encoded))}
    handler.rfile = io.BytesIO(encoded)
    handler.streamer_core = core
    handler.reject_if_auth_blocked = lambda *a: False
    handler.reject_if_web_remote_disabled = lambda *a: False
    handler.check_web_password_auth = lambda *a, **kw: True
    handler.check_rate_limit = lambda: True
    handler.is_local_request = lambda: local
    recorded = []
    handler.send_json_response = lambda code, data: recorded.append((code, data))
    handler.do_POST()
    return recorded[0]


@pytest.mark.parametrize("body", [{"url": "https://public.example/watch"}, {"url": "https://public.example/watch", "download": False}])
def test_api_default_preserves_streaming(core, monkeypatch, body):
    legacy = MagicMock(return_value=[{"title": "legacy"}])
    monkeypatch.setattr(core, "add_to_queue", legacy)
    downloader = MagicMock()
    monkeypatch.setattr(core, "download_video_to_queue", downloader)
    assert queue_request(core, body)[0] == 200
    legacy.assert_called_once_with(body["url"])
    downloader.assert_not_called()


def test_api_download_host_only_and_typed(core, monkeypatch):
    downloader = MagicMock(return_value=[{"title": "downloaded"}])
    monkeypatch.setattr(core, "download_video_to_queue", downloader)
    url = "https://public.example/watch"
    assert queue_request(core, {"url": url, "download": True}, local=False)[0] == 403
    assert queue_request(core, {"url": url, "download": "true"})[0] == 400
    downloader.assert_not_called()
    assert queue_request(core, {"url": url, "download": True})[0] == 200
    downloader.assert_called_once_with(url)


def test_busy_download_fails_fast(core):
    with core.video_downloads.lock:
        with pytest.raises(VideoDownloadError, match="別の動画"):
            core.download_video_to_queue("https://public.example/movie.mp4")


def test_split_tracks_merge_locally_in_video_audio_order(core, monkeypatch):
    ydl = MagicMock()
    ydl.__enter__.return_value.extract_info.return_value = {
        "title": "Split video", "requested_formats": [
            {"url": "https://public.example/audio", "protocol": "https", "vcodec": "none"},
            {"url": "https://public.example/video", "protocol": "https", "vcodec": "avc1"},
        ]}
    monkeypatch.setattr(sc.yt_dlp, "YoutubeDL", lambda *a: ydl)
    opener = network(monkeypatch)
    commands = []
    def local(command, deadline):
        commands.append(command)
        if "-map" in command:
            Path(command[-1]).write_bytes(b"merged")
            return b""
        return b'{"streams":[{"codec_type":"video"}],"format":{"duration":"8"}}'
    monkeypatch.setattr(core.video_downloads, "run_local", local)
    item = core.download_video_to_queue("https://public.example/watch")[0]
    assert Path(item["path"]).read_bytes() == b"merged"
    assert [call.args[0].full_url for call in opener.open.call_args_list] == [
        "https://public.example/video", "https://public.example/audio"]
    assert "0:v:0" in commands[0] and "1:a:0" in commands[0]
    assert all("https://" not in arg for arg in commands[0])
    assert not list(Path(item["path"]).parent.glob("*.part"))


def test_real_worker_cancelled_by_shutdown(core, monkeypatch):
    entered = threading.Event()
    class SlowResponse(Response):
        def read1(self, size):
            entered.set()
            assert core.video_downloads.cancelled.wait(3)
            return b"video"
    network(monkeypatch, SlowResponse)
    errors = []
    def worker():
        try:
            core.download_video_to_queue("https://public.example/movie.mp4")
        except VideoDownloadError as exc:
            errors.append(str(exc))
    thread = threading.Thread(target=worker)
    thread.start()
    assert entered.wait(3)
    core.shutdown()
    thread.join(3)
    assert not thread.is_alive() and errors
    assert not core.play_queue
    assert not list(Path(core.video_downloads.root).rglob("*"))


def test_nonvideo_response_not_queued(core, monkeypatch):
    network(monkeypatch)
    monkeypatch.setattr(core.video_downloads, "run_local", lambda *a:
                        b'{"streams":[{"codec_type":"audio"}],"format":{"duration":"8"}}')
    with pytest.raises(VideoDownloadError, match="動画が含まれていません"):
        core.download_video_to_queue("https://public.example/movie.mp4")
    assert not core.play_queue
    assert not list(Path(core.video_downloads.root).rglob("*"))


def test_cross_origin_redirect_strips_credentials():
    import urllib.request
    manager = TemporaryVideoDownloads("unused", lambda *a: (True, ""))
    req = urllib.request.Request("https://public.example/video", headers={
        "Authorization": "private", "Cookie": "private", "User-Agent": "video"})
    redirected = SafeVideoRedirect(manager.validate).redirect_request(
        req, None, 302, "Found", {}, "https://cdn.example/video")
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Cookie") is None
    assert redirected.get_header("User-agent") == "video"
