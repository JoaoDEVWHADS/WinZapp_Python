"""Regression tests for independent quick-message and attachment workers."""

import pathlib
import sys
import threading
import time
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))

wx = types.ModuleType("wx")
wx.CallAfter = lambda callback, *args: callback(*args)
sys.modules.setdefault("wx", wx)

from core.message_queue import MessageQueue, PendingMessage


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

    main_window = _CancelableMainWindow()
    queue = MessageQueue(main_window)
    try:
        queue.enqueue(PendingMessage(
            "cancel-me", "chat-a", media_path="large.bin",
            media_type="document", progress_callback=lambda _value: None,
        ))
        assert main_window.media_started.wait(timeout=1)
        assert queue.cancel("cancel-me") is True
        deadline = time.time() + 1
        while time.time() < deadline:
            with queue._lock:
                if "cancel-me" not in queue._pending:
                    cancelled.set()
                    break
            time.sleep(0.01)
        assert cancelled.is_set()
        assert not sent.is_set()
        assert not failed.is_set()
    finally:
        queue.stop()
