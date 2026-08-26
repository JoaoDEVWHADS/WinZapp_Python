"""Regression test: cancelling a message did not stop it from actually
being sent.

MessageQueue only ever checked PendingMessage.cancel_event *before* the
network call started — never during or after it, since none of
send_text_message()/send_audio_message()/send_contact_attachment() (or a
media upload finishing between progress-callback checks) can be interrupted
mid-flight. So a message could reach WhatsApp after the user cancelled it
(conversations.py's delete-while-pending path removes the row and calls
queue.cancel() the moment the user confirms), and the worker still ran the
normal success path regardless: register the real id in _own_sent_ids (which
suppresses the WebSocket echo — see main.py's on_new_message/
on_messages_upsert) and call _on_message_sent(). The message was genuinely
delivered, but nothing about that was ever visible again: the row was
already gone, and the one signal that would normally reintroduce it (the
echo) was actively suppressed.

The fix checks cancel_event right when the send returns, before doing either
of those two things, and lets the (real, honest) WebSocket echo insert the
message normally instead of hiding that it went out.

Same stub approach as tests/test_message_queue_concurrency.py: a fake `wx`
module (MessageQueue calls wx.CallAfter) is installed before importing
core.message_queue.
"""

import os
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

from core.message_queue import MessageQueue, PendingMessage  # noqa: E402


class _MainWindow:
    offline_mode = False
    _wa_connected = True

    def __init__(self):
        self._own_sent_ids_lock = threading.Lock()
        self._own_sent_ids = set()
        self.sent_calls = []
        self.failed_calls = []

    def _on_message_sent(self, *args):
        self.sent_calls.append(args)

    def _on_message_failed(self, *args):
        self.failed_calls.append(args)

    def _on_message_unconfirmed(self, *args):
        pass


class TestASendThatCompletesAfterCancelIsNotShownAsSent:
    def test_own_sent_ids_does_not_get_the_id(self):
        """This is the concrete mechanism of the bug: registering the id
        here is what suppresses the WebSocket echo for a message that
        genuinely went out."""
        release = threading.Event()
        started = threading.Event()

        class _MW(_MainWindow):
            def send_text_message(self, *_a, **_kw):
                started.set()
                assert release.wait(timeout=3)
                return "REAL_ID"

        mw = _MW()
        queue = MessageQueue(mw)
        try:
            queue.enqueue(PendingMessage("loc-1", "chat-a", text="oi"))
            assert started.wait(timeout=1)

            # The UI's delete-while-pending path: cancel while the HTTP call
            # is still in flight, same as conversations.py's cancelled_pending
            # branch does the moment the user confirms deletion.
            assert queue.cancel("loc-1") is True
            release.set()

            deadline = time.time() + 2
            while time.time() < deadline and "loc-1" in queue._pending:
                time.sleep(0.01)

            time.sleep(0.1)  # let the worker finish processing this cycle
            assert "REAL_ID" not in mw._own_sent_ids
        finally:
            queue.stop()

    def test_on_message_sent_is_not_called(self):
        release = threading.Event()
        started = threading.Event()

        class _MW(_MainWindow):
            def send_text_message(self, *_a, **_kw):
                started.set()
                assert release.wait(timeout=3)
                return "REAL_ID"

        mw = _MW()
        queue = MessageQueue(mw)
        try:
            queue.enqueue(PendingMessage("loc-1", "chat-a", text="oi"))
            assert started.wait(timeout=1)
            assert queue.cancel("loc-1") is True
            release.set()
            time.sleep(0.2)

            assert mw.sent_calls == []
            assert mw.failed_calls == []
        finally:
            queue.stop()

    def test_a_cancelled_audio_send_still_cleans_up_its_temp_file(self, tmp_path):
        release = threading.Event()
        started = threading.Event()
        audio_path = str(tmp_path / "recording.wav")
        with open(audio_path, "wb") as f:
            f.write(b"fake wav data")

        class _MW(_MainWindow):
            def send_audio_message(self, *_a, **_kw):
                started.set()
                assert release.wait(timeout=3)
                return "REAL_AUDIO_ID"

        mw = _MW()
        queue = MessageQueue(mw)
        try:
            queue.enqueue(PendingMessage("loc-audio", "chat-a", audio_path=audio_path))
            assert started.wait(timeout=1)
            assert queue.cancel("loc-audio") is True
            release.set()

            deadline = time.time() + 2
            while time.time() < deadline and os.path.isfile(audio_path):
                time.sleep(0.01)

            assert not os.path.isfile(audio_path)
        finally:
            queue.stop()


class TestAnNonCancelledSendIsUnaffected:
    def test_normal_success_still_registers_and_notifies(self):
        mw = _MainWindow()
        queue = MessageQueue(mw)
        try:
            def _send(*_a, **_kw):
                return "REAL_ID"
            mw.send_text_message = _send

            queue.enqueue(PendingMessage("loc-2", "chat-a", text="oi"))

            deadline = time.time() + 2
            while time.time() < deadline and not mw.sent_calls:
                time.sleep(0.01)

            assert "REAL_ID" in mw._own_sent_ids
            assert len(mw.sent_calls) == 1
            assert mw.sent_calls[0][0] == "loc-2"
        finally:
            queue.stop()
