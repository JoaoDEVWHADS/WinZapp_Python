"""Regression tests for independent quick-message and attachment workers."""

import pathlib
import sys
import threading
import time

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

import core.message_queue as message_queue
from core.message_queue import MessageQueue, PendingMessage


@pytest.fixture(autouse=True)
def direct_call_after(monkeypatch):
    """Dispatch wx.CallAfter straight to its callback — there is no wx.App here.

    Patched on the module rather than installed as a fake `wx` in sys.modules:
    the old `sys.modules.setdefault("wx", ...)` only won when this file happened
    to be the first to import wx, so any test importing main/wx before it left
    the workers calling the real CallAfter, which asserts "No wx.App created
    yet" on a background thread.
    """
    monkeypatch.setattr(
        message_queue.wx, "CallAfter",
        lambda callback, *args: callback(*args), raising=False,
    )


class _MainWindow:
    offline_mode = False
    _wa_connected = True

    def __init__(self):
        self.media_started = threading.Event()
        self.release_media = threading.Event()
        self.text_sent = threading.Event()
        self._own_sent_ids_lock = threading.Lock()
        self._own_sent_ids = set()

    def send_media_attachment(self, *_args, **_kwargs):
        self.media_started.set()
        assert self.release_media.wait(timeout=3)
        return "media-id"

    def send_text_message(self, *_args, **_kwargs):
        self.text_sent.set()
        return "text-id"

    def _on_message_sent(self, *_args):
        pass

    def _on_message_failed(self, *_args):
        pass

    def _on_message_unconfirmed(self, *_args):
        pass

    def _on_cancelled_message_dropped(self, *_args):
        pass


def test_text_sends_while_attachment_is_still_uploading():
    main_window = _MainWindow()
    queue = MessageQueue(main_window)
    try:
        queue.enqueue(PendingMessage(
            "media", "chat-a", media_path="large.bin", media_type="document"
        ))
        assert main_window.media_started.wait(timeout=1)

        queue.enqueue(PendingMessage("text", "chat-b", text="hello"))

        assert main_window.text_sent.wait(timeout=1)
        assert not main_window.release_media.is_set()
    finally:
        main_window.release_media.set()
        queue.stop()


def test_attachment_progress_callback_reaches_send_media_attachment():
    """The queue must not drop the progress callback supplied by the UI.

    Dropping it left MainWindow.send_media_attachment() reading the file through
    a plain handle instead of _UploadProgressFile, so the gauge got no HTTP
    upload updates and appeared to flash briefly before completion.
    """
    seen = {}
    done = threading.Event()

    class _ProgressMainWindow(_MainWindow):
        def send_media_attachment(self, *_args, **kwargs):
            seen["callback"] = kwargs.get("progress_callback")
            done.set()
            return "media-id"

    main_window = _ProgressMainWindow()
    queue = MessageQueue(main_window)
    callback = lambda value: None
    try:
        queue.enqueue(PendingMessage(
            "media-progress", "chat-a", media_path="large.bin",
            media_type="document", progress_callback=callback,
        ))
        assert done.wait(timeout=1)
        assert callable(seen["callback"])
        seen["callback"](0.5)
    finally:
        queue.stop()


def test_cancel_interrupts_an_inflight_attachment_without_failure_callback():
    cancelled = threading.Event()
    failed = threading.Event()
    sent = threading.Event()

    class _CancelableMainWindow(_MainWindow):
        def send_media_attachment(self, *_args, **kwargs):
            self.media_started.set()
            callback = kwargs["progress_callback"]
            while True:
                callback(0.25)
                time.sleep(0.01)

        def _on_message_sent(self, *_args):
            sent.set()

        def _on_message_failed(self, *_args):
            failed.set()

        def _on_cancelled_message_dropped(self, *_args):
            cancelled.set()

    main_window = _CancelableMainWindow()
    queue = MessageQueue(main_window)
    try:
        queue.enqueue(PendingMessage(
            "cancel-me", "chat-a", media_path="large.bin",
            media_type="document", progress_callback=lambda _value: None,
        ))
        assert main_window.media_started.wait(timeout=1)
        # False: the upload is already running, so cancel() cannot promise it was
        # stopped — the worker owns it and reports the outcome (see
        # tests/test_message_cancel_race.py). The flag is set either way, which
        # is what the progress callback below raises MessageCancelled on.
        assert queue.cancel("cancel-me") is False
        # Waiting for the report, not just for the queue to drop it: the report
        # is the worker's last act on this message, so this is also what keeps a
        # straggling wx.CallAfter from outliving the test.
        assert cancelled.wait(timeout=2)
        with queue._lock:
            assert "cancel-me" not in queue._pending
        assert not sent.is_set()
        assert not failed.is_set()
    finally:
        queue.stop()
