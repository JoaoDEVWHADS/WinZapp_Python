"""
WinZapp Message Queue
---------------------
Background queue for outgoing messages (text and voice).

Behaviour
---------
* Immediate first attempt: the worker wakes up as soon as a message is
  enqueued, so the first send attempt is nearly instantaneous.
* Retry every 3 seconds on failure.
* In offline mode the worker loop is suspended until connectivity is
  restored; call ``flush()`` to wake it immediately when going back online.
* On success the UI is notified via ``wx.CallAfter`` so status labels update.
"""

import threading
import time
import wx


class PendingMessage:
    """Data object for a queued outgoing message."""

    def __init__(self, local_id: str, jid: str,
                 text: str = None,
                 audio_path: str = None,
                 media_path: str = None,
                 media_type: str = None,
                 caption: str = None,
                 contact_info: dict = None,
                 quoted: dict = None):
        # local_id matches the "_local_id" field in the virtual message dict
        # that was already added to the UI.
        self.local_id     = local_id
        self.jid          = jid
        self.text         = text          # plain-text body
        self.audio_path   = audio_path    # path to recorded WAV
        self.media_path   = media_path    # path to attached file (image/video/doc/audio)
        self.media_type   = media_type    # "image"|"video"|"audio"|"document"
        self.caption      = caption or "" # optional caption for media
        self.contact_info = contact_info  # dict for contact attachment
        self.quoted       = quoted        # quoted/replied-to message dict
        self.fail_count   = 0            # consecutive send failures


class MessageQueue:
    """Thread-safe outgoing-message queue with automatic retry."""

    _RETRY_INTERVAL = 3   # seconds between retry cycles
    _MAX_RETRIES    = 20  # give up after this many consecutive failures per message

    def __init__(self, main_window):
        self.main_window = main_window
        self._pending: dict = {}          # local_id → PendingMessage
        self._lock   = threading.Lock()
        self._event  = threading.Event()  # pulsed to wake worker early
        self._stop   = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def enqueue(self, msg: PendingMessage):
        """Add *msg* to the queue and trigger an immediate send attempt."""
        with self._lock:
            self._pending[msg.local_id] = msg
        self._event.set()

    def flush(self):
        """
        Wake the worker immediately (call when going back online so queued
        messages are retried without waiting the full 3-second interval).
        """
        self._event.set()

    def stop(self):
        """Signal the worker to exit cleanly (call at app shutdown)."""
        self._stop.set()
        self._event.set()

    # ── Worker thread ─────────────────────────────────────────────────────────

    def _run(self):
        while not self._stop.is_set():
            # Wait up to RETRY_INTERVAL seconds, or until woken early.
            self._event.wait(timeout=self._RETRY_INTERVAL)
            self._event.clear()

            if self._stop.is_set():
                break

            # While offline or WhatsApp disconnected: skip this cycle.
            if self.main_window.offline_mode:
                continue
            if not getattr(self.main_window, "_wa_connected", True):
                continue

            with self._lock:
                items = list(self._pending.values())

            for msg in items:
                if self._stop.is_set():
                    break
                if self.main_window.offline_mode:
                    break
                if not getattr(self.main_window, "_wa_connected", True):
                    break
                try:
                    if msg.audio_path:
                        ok = self.main_window.send_audio_message(
                            msg.jid, msg.audio_path, quoted=msg.quoted
                        )
                    elif msg.media_path:
                        ok = self.main_window.send_media_attachment(
                            msg.jid, msg.media_path, msg.media_type, msg.caption,
                            quoted=msg.quoted,
                        )
                    elif msg.contact_info:
                        ok = self.main_window.send_contact_attachment(
                            msg.jid, msg.contact_info, quoted=msg.quoted
                        )
                    else:
                        ok = self.main_window.send_text_message(
                            msg.jid, msg.text, quoted=msg.quoted
                        )
                    if ok:
                        msg.fail_count = 0
                        with self._lock:
                            self._pending.pop(msg.local_id, None)
                        # Notify the UI on the main thread.
                        wx.CallAfter(
                            self.main_window._on_message_sent,
                            msg.local_id,
                            msg.audio_path,
                        )
                    else:
                        msg.fail_count += 1
                        print(f"[MessageQueue] send failed for {msg.local_id} (attempt {msg.fail_count}/{self._MAX_RETRIES})")
                        if msg.fail_count >= self._MAX_RETRIES:
                            print(f"[MessageQueue] giving up on {msg.local_id} after {self._MAX_RETRIES} attempts")
                            with self._lock:
                                self._pending.pop(msg.local_id, None)
                            wx.CallAfter(
                                self.main_window._on_message_failed,
                                msg.local_id,
                            )
                except Exception as exc:
                    msg.fail_count += 1
                    print(f"[MessageQueue] exception for {msg.local_id} (attempt {msg.fail_count}/{self._MAX_RETRIES}): {exc}")
                    if msg.fail_count >= self._MAX_RETRIES:
                        print(f"[MessageQueue] giving up on {msg.local_id} after {self._MAX_RETRIES} attempts")
                        with self._lock:
                            self._pending.pop(msg.local_id, None)
                        wx.CallAfter(
                            self.main_window._on_message_failed,
                            msg.local_id,
                        )
