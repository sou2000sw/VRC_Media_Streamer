import threading

import streamer_core
from streamer_core import StreamerCore


class FakeProcess:
    def __init__(self, return_code):
        self.return_code = return_code

    def wait(self):
        return self.return_code


def make_minimal_core():
    core = StreamerCore.__new__(StreamerCore)
    core.play_queue = []
    core.queue_lock = threading.Lock()
    core.process_lock = threading.Lock()
    core.video_done_event = threading.Event()
    core.reload_stream_event = threading.Event()
    core.reload_requested_at = 0.0
    core.reload_first_requested_at = 0.0
    core.send_proc = None
    return core


def test_single_youtube_enqueue_keeps_resolved_metadata(monkeypatch):
    core = make_minimal_core()
    expanded = [{"url": "https://youtu.be/abc123", "title": "Resolved title", "duration": 123}]
    monkeypatch.setattr(core, "expand_playlist", lambda _url: expanded)

    items = core.add_to_queue("https://www.youtube.com/watch?v=abc123")

    assert items == expanded
    assert items[0]["title"] == "Resolved title"
    assert items[0]["duration"] == 123
    assert core.play_queue == expanded


def test_youtube_playlist_is_still_expanded(monkeypatch):
    core = make_minimal_core()
    expanded = [{"url": "https://example.test/video", "title": "one", "duration": 10}]
    monkeypatch.setattr(core, "expand_playlist", lambda _url: expanded)

    items = core.add_to_queue("https://www.youtube.com/watch?v=abc123&list=PL123")

    assert items == expanded
    assert core.play_queue == expanded


def test_abnormal_sender_exit_does_not_mark_video_done():
    core = make_minimal_core()
    proc = FakeProcess(1)
    core.send_proc = proc

    core.watch_send_proc(proc, threading.Event())

    assert not core.video_done_event.is_set()
    assert core.reload_stream_event.is_set()


def test_stale_sender_exit_does_not_mark_current_video_done():
    core = make_minimal_core()
    stale_proc = FakeProcess(0)
    core.send_proc = FakeProcess(0)

    core.watch_send_proc(stale_proc, threading.Event())

    assert not core.video_done_event.is_set()


def test_current_sender_normal_exit_marks_video_done():
    core = make_minimal_core()
    proc = FakeProcess(0)
    core.send_proc = proc

    core.watch_send_proc(proc, threading.Event())

    assert core.video_done_event.is_set()


def test_reapplying_video_mode_does_not_save_or_reload():
    core = make_minimal_core()
    core.config = {"playback_mode": "video", "radio_mode": False}
    calls = []
    core.save_config = lambda: calls.append("save")
    core.request_stream_reload = lambda: calls.append("reload")

    assert core.set_playback_mode("video") == "video"
    assert calls == []


def test_changing_mode_still_saves_and_reloads():
    core = make_minimal_core()
    core.config = {"playback_mode": "radio", "radio_mode": True}
    calls = []
    core.save_config = lambda: calls.append("save")
    core.request_stream_reload = lambda: calls.append("reload")

    assert core.set_playback_mode("video") == "video"
    assert calls == ["save", "reload"]


def test_stale_relay_cannot_overwrite_active_stream_duration(monkeypatch):
    core = make_minimal_core()
    stale_proc = FakeProcess(0)
    stale_proc.stdout = type("Output", (), {"read": lambda self, _size: b""})()
    core.send_proc = FakeProcess(0)
    core.last_stream_duration = 42.0
    core.is_running = True
    core.get_active_output_mode = lambda: "hls"
    monkeypatch.setattr(streamer_core, "extract_pts_from_ts_chunk", lambda _data: None)

    core.relay_stream_data(stale_proc, None, threading.Event())

    assert core.last_stream_duration == 42.0
