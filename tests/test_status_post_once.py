"""Post sends a status once.

Reported: after writing the caption of a video status, Post could be pressed
again while the video was still uploading, and the status went out twice. A
flat 60 s timeout made it worse: a big video still uploading was reported as
failed, and the user posted it again. Post now holds one post at a time, the
timeout follows the file's size, and a post that timed out is "not
confirmed", never "failed".
"""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import wx

from status_tab import status_composer
from status_tab.status_composer import StatusComposerMixin
from status_tab.status_rules import STATUS_POST_UNCONFIRMED, status_upload_timeout


class _Panel:
    _begin_status_post = StatusComposerMixin._begin_status_post
    _end_status_post = StatusComposerMixin._end_status_post
    _on_send_media_status = StatusComposerMixin._on_send_media_status
    _on_send_text_status = StatusComposerMixin._on_send_text_status
    _send_all_media_statuses_bg = StatusComposerMixin._send_all_media_statuses_bg
    _send_media_status_bg = StatusComposerMixin._send_media_status_bg
    _send_text_status_bg = StatusComposerMixin._send_text_status_bg

    def __init__(self, paths=()):
        self.main_window = SimpleNamespace(
            i18n=SimpleNamespace(t=lambda key: key), output=Mock(), app_name="WinZapp",
            wpp_server="http://localhost", wpp_port=6300, token="token")
        self._selected_media_paths = list(paths)
        self._media_caption_field = SimpleNamespace(GetValue=lambda: "a caption")
        self._post_text_field = SimpleNamespace(GetValue=lambda: "text")
        self._caption_field = SimpleNamespace(GetValue=lambda: "")
        self._on_status_sent = Mock()
        self.unsent = []

    def _remember_unsent_status(self, post):
        """status_tab/unsent_status.py keeps it in the list (tests/test_unsent_status.py)."""
        self.unsent.append(post)


@pytest.fixture
def threads(monkeypatch):
    """Threads are collected, not started, so a test decides when one runs."""
    started = []

    class _Thread:
        def __init__(self, target, args=(), kwargs=None, daemon=True):
            self.run = lambda: target(*args, **(kwargs or {}))

        def start(self):
            started.append(self)

    monkeypatch.setattr(status_composer.threading, "Thread", _Thread)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args, **kw: fn(*args, **kw))
    return started


def _video(tmp_path, size=1024):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"\0" * size)
    return str(path)


class TestOnePostAtATime:
    def test_a_second_press_while_posting_sends_nothing(self, tmp_path, threads):
        panel = _Panel([_video(tmp_path)])
        panel._on_send_media_status(None)
        panel._on_send_media_status(None)
        assert len(threads) == 1
        said = [call.args[0] for call in panel.main_window.output.call_args_list]
        assert said == ["status_posting", "status_post_in_progress"]

    def test_post_is_free_again_once_the_post_ended(self, tmp_path, threads, monkeypatch):
        monkeypatch.setattr(status_composer, "api_post", Mock(return_value=SimpleNamespace(
            status_code=201, text="", json=lambda: {})))
        panel = _Panel([_video(tmp_path)])
        panel._on_send_media_status(None)
        threads.pop().run()
        panel._on_status_sent.assert_called_once()
        panel._on_send_media_status(None)
        assert len(threads) == 1

    def test_a_failure_frees_post_too(self, tmp_path, threads, monkeypatch):
        monkeypatch.setattr(status_composer, "api_post", Mock(side_effect=ConnectionError("down")))
        monkeypatch.setattr(wx, "MessageBox", Mock())
        panel = _Panel([_video(tmp_path)])
        panel._on_send_media_status(None)
        threads.pop().run()
        assert panel._status_post_in_flight is False

    def test_the_text_post_holds_the_same_guard(self, threads):
        panel = _Panel()
        panel._on_send_text_status(None)
        panel._on_send_text_status(None)
        assert len(threads) == 1


class TestATimeoutIsNotAFailure:
    def test_a_video_that_timed_out_is_unconfirmed_never_failed(self, tmp_path, threads, monkeypatch):
        post = Mock(side_effect=requests.exceptions.ReadTimeout("slow"))
        monkeypatch.setattr(status_composer, "api_post", post)
        box = Mock()
        monkeypatch.setattr(wx, "MessageBox", box)
        panel = _Panel([_video(tmp_path)])
        panel._on_send_media_status(None)
        threads.pop().run()
        post.assert_called_once()
        assert [call.args[0] for call in box.call_args_list] == ["status_post_unconfirmed"]
        panel._on_status_sent.assert_not_called()

    def test_nothing_sent_is_still_a_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(status_composer, "api_post",
                            Mock(side_effect=requests.exceptions.ConnectTimeout("no route")))
        panel = _Panel()
        assert panel._send_media_status_bg(_video(tmp_path), "", report_result=False) is False

    def test_the_text_post_that_timed_out_is_unconfirmed(self, threads, monkeypatch):
        monkeypatch.setattr(status_composer, "api_post",
                            Mock(side_effect=requests.exceptions.ReadTimeout("slow")))
        box = Mock()
        monkeypatch.setattr(wx, "MessageBox", box)
        panel = _Panel()
        panel._on_send_text_status(None)
        threads.pop().run()
        assert box.call_args.args[0] == "status_post_unconfirmed"

    def test_the_upload_timeout_follows_the_size(self, tmp_path, threads, monkeypatch):
        post = Mock(return_value=SimpleNamespace(status_code=201, text="", json=lambda: {}))
        monkeypatch.setattr(status_composer, "api_post", post)
        panel = _Panel()
        size = 30 * 1024 * 1024
        assert panel._send_media_status_bg(_video(tmp_path, size), "", report_result=False) is True
        assert post.call_args.kwargs["timeout"] == status_upload_timeout(size)


def test_the_upload_timeout_grows_with_the_file_and_stops_at_30_minutes():
    assert status_upload_timeout(None) == 60 and status_upload_timeout(0) == 60
    assert status_upload_timeout(1024) == 60
    assert status_upload_timeout(30 * 1024 * 1024) > 200
    assert status_upload_timeout(10 * 1024 ** 3) == 30 * 60
    assert STATUS_POST_UNCONFIRMED == "unconfirmed"
