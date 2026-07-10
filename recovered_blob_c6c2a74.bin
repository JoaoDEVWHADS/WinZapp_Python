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

import logging
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
                 quoted: dict = None,
                 mentioned_jids: list = None):
        # local_id matches the "_local_id" field in the virtual message dict
        # that was already added to the UI.
        self.local_id      = local_id
        self.jid           = jid
        self.text          = text           # plain-text body
        self.audio_path    = audio_path     # path to recorded WAV
        self.media_path    = media_path     # path to attached file (image/video/doc/audio)
        self.media_type    = media_type     # "image"|"video"|"audio"|"document"
        self.caption       = caption or ""  # optional caption for media
        self.contact_info  = contact_info   # dict for contact attachment
        self.quoted        = quoted         # quoted/replied-to message dict
        self.mentioned_jids = mentioned_jids or []  # JIDs @mentioned in text
        self.fail_count    = 0             # consecutive send failures
        self.last_error    = ""            # last send error shown if retries exhaust


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
                        real_id = self.main_window.send_audio_message(
                            msg.jid, msg.audio_path, quoted=msg.quoted
                        )
                    elif msg.media_path:
                        real_id = self.main_window.send_media_attachment(
                            msg.jid, msg.media_path, msg.media_type, msg.caption,
                            quoted=msg.quoted,
                        )
                    elif msg.contact_info:
                        real_id = self.main_window.send_contact_attachment(
                            msg.jid, msg.contact_info, quoted=msg.quoted
                        )
                    else:
                        real_id = self.main_window.send_text_message(
                            msg.jid, msg.text, quoted=msg.quoted,
                            mentioned_jids=msg.mentioned_jids or None,
                        )
                    retryable_failure = False
                    if isinstance(real_id, dict):
                        if real_id.get("ok"):
                            real_id = real_id.get("id") or True
                        else:
                            msg.last_error = real_id.get("error") or ""
                            retryable_failure = bool(real_id.get("retry", True))
                            real_id = False

                    if real_id:
                        msg.fail_count = 0
                        with self._lock:
                            self._pending.pop(msg.local_id, None)
                        # Register the real ID immediately so the WebSocket echo
                        # (messages.upsert with fromMe=True) is recognised as
                        # "sent by this instance" and not shown as a new message.
                        if isinstance(real_id, str):
                            with self.main_window._own_sent_ids_lock:
                                self.main_window._own_sent_ids.add(real_id)
                                # Prevent unbounded growth — keep at most 500 IDs.
                                if len(self.main_window._own_sent_ids) > 500:
                                    self.main_window._own_sent_ids.discard(
                                        next(iter(self.main_window._own_sent_ids))
                                    )
                        # Pass the real WhatsApp message ID so _mark_message_sent
                        # can update the virtual message's key.id for playback.
                        wx.CallAfter(
                            self.main_window._on_message_sent,
                            msg.local_id,
                            msg.audio_path,
                            real_id if isinstance(real_id, str) else None,
                        )
                    else:
                        msg.fail_count += 1
                        if not msg.last_error:
                            msg.last_error = getattr(self.main_window, "_last_send_error", "") or ""
                        logging.warning("[MessageQueue] send failed for %s jid=%s attempt=%s/%s",
                                        msg.local_id, msg.jid, msg.fail_count, self._MAX_RETRIES)
                        if msg.fail_count >= self._MAX_RETRIES:
                            logging.error("[MessageQueue] giving up on %s jid=%s after %s attempt(s). last_error=%s",
                                          msg.local_id, msg.jid, msg.fail_count, msg.last_error)
                            with self._lock:
                                self._pending.pop(msg.local_id, None)
                            wx.CallAfter(
                                self.main_window._on_message_failed,
                                msg.local_id,
                                msg.last_error,
                                bool(msg.media_path),  # show dialog for media failures
                            )
                except Exception as exc:
                    msg.fail_count += 1
                    logging.error("[MessageQueue] exception for %s jid=%s attempt=%s/%s: %s",
                                  msg.local_id, msg.jid, msg.fail_count, self._MAX_RETRIES, exc)
                    if msg.fail_count >= self._MAX_RETRIES:
                        logging.error("[MessageQueue] giving up on %s jid=%s after %s attempt(s)",
                                      msg.local_id, msg.jid, msg.fail_count)
                        with self._lock:
                            self._pending.pop(msg.local_id, None)
                        wx.CallAfter(
                            self.main_window._on_message_failed,
                            msg.local_id,
                            str(exc),
                            bool(msg.media_path),
                        )
