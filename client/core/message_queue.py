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
                 ogg_bytes: bytes = None,
                 media_path: str = None,
                 media_type: str = None,
                 caption: str = None,
                 progress_callback=None,
                 contact_info: dict = None,
                 quoted: dict = None,
                 mentioned_jids: list = None):
        # local_id matches the "_local_id" field in the virtual message dict
        # that was already added to the UI.
        self.local_id      = local_id
        self.jid           = jid
        self.text          = text           # plain-text body
        self.audio_path    = audio_path     # path to recorded WAV
        self.ogg_bytes     = ogg_bytes      # pre-encoded OGG Opus (skips encoding on send)
        self.media_path    = media_path     # path to attached file (image/video/doc/audio)
        self.media_type    = media_type     # "image"|"video"|"audio"|"document"
        self.caption       = caption or ""  # optional caption for media
        self.progress_callback = progress_callback
        self.contact_info  = contact_info   # dict for contact attachment
        self.quoted        = quoted         # quoted/replied-to message dict
        self.mentioned_jids = mentioned_jids or []  # JIDs @mentioned in text
        self.fail_count    = 0             # consecutive send failures
        self.last_error    = ""            # last send error shown if retries exhaust


class MessageQueue:
    """Thread-safe outgoing-message queue with automatic retry."""

    _RETRY_INTERVAL = 3   # seconds between retry cycles
    # Give up after this many consecutive failures per message.  Kept small on
    # purpose: every retry of a send that WhatsApp Web may have silently
    # accepted is a potential duplicate delivered to the recipient, so only
    # genuinely-not-sent failures (explicit 5xx) are retried, and only a few
    # times.  Connection losses and timeouts never reach this counter — they
    # are handled as "queued" / "unknown outcome" above.
    _MAX_RETRIES    = 4

    def __init__(self, main_window):
        self.main_window = main_window
        self._pending: dict = {}          # local_id → PendingMessage
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._quick_event = threading.Event()
        self._media_event = threading.Event()
        self._workers = (
            threading.Thread(
                target=self._run, args=(False,), daemon=True,
                name="winzapp-message-quick",
            ),
            threading.Thread(
                target=self._run, args=(True,), daemon=True,
                name="winzapp-message-media",
            ),
        )
        for worker in self._workers:
            worker.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def enqueue(self, msg: PendingMessage):
        """Add *msg* to the queue and trigger an immediate send attempt."""
        with self._lock:
            self._pending[msg.local_id] = msg
        self._event_for(msg).set()

    def flush(self):
        """
        Wake the worker immediately (call when going back online so queued
        messages are retried without waiting the full 3-second interval).
        """
        self._quick_event.set()
        self._media_event.set()

    def stop(self):
        """Signal the worker to exit cleanly (call at app shutdown)."""
        self._stop.set()
        self.flush()

    # ── Worker thread ─────────────────────────────────────────────────────────

    @staticmethod
    def _is_media(msg: PendingMessage) -> bool:
        return bool(msg.media_path)

    def _event_for(self, msg: PendingMessage) -> threading.Event:
        return self._media_event if self._is_media(msg) else self._quick_event

    def _run(self, media_only: bool):
        wake_event = self._media_event if media_only else self._quick_event
        while not self._stop.is_set():
            # Wait up to RETRY_INTERVAL seconds, or until woken early.
            wake_event.wait(timeout=self._RETRY_INTERVAL)
            wake_event.clear()

            if self._stop.is_set():
                break

            # While offline or WhatsApp disconnected: skip this cycle.
            if self.main_window.offline_mode:
                continue
            if not getattr(self.main_window, "_wa_connected", True):
                continue

            with self._lock:
                items = [
                    msg for msg in self._pending.values()
                    if self._is_media(msg) == media_only
                ]

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
                            msg.jid, msg.audio_path, quoted=msg.quoted,
                            ogg_bytes=msg.ogg_bytes,
                        )
                    elif msg.media_path:
                        real_id = self.main_window.send_media_attachment(
                            msg.jid, msg.media_path, msg.media_type, msg.caption,
                            quoted=msg.quoted, upload_id=msg.local_id,
                            progress_callback=msg.progress_callback,
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
                    disconnected      = False
                    ambiguous         = False
                    quote_lost        = False
                    if isinstance(real_id, dict):
                        if real_id.get("ok"):
                            quote_lost = bool(real_id.get("quote_lost", False))
                            real_id = real_id.get("id") or True
                        else:
                            msg.last_error = real_id.get("error") or ""
                            retryable_failure = bool(real_id.get("retry", True))
                            disconnected      = bool(real_id.get("disconnected"))
                            ambiguous         = bool(real_id.get("ambiguous"))
                            real_id = False

                    if not real_id and disconnected:
                        # WhatsApp is down and told us so explicitly (HTTP 404
                        # "Disconnected"): the message was definitely not sent,
                        # so keep it queued — but stop the 3-second retry loop
                        # right here. main_window._wa_connected was just set to
                        # False by the send call, so the next loop iteration
                        # parks the whole queue until the connection is back.
                        logging.info(
                            "[MessageQueue] %s stays queued — WhatsApp disconnected", msg.local_id
                        )
                        break

                    if not real_id and ambiguous:
                        # Timeout / dropped connection: we do NOT know whether
                        # WhatsApp Web accepted the message into its outbox.
                        # Resending would duplicate it (and did: users saw 30+
                        # copies delivered at once when connectivity returned),
                        # so hand it off and let the WebSocket echo resolve the
                        # pending bubble if it does go out.
                        logging.warning(
                            "[MessageQueue] send outcome unknown for %s jid=%s (%s) — "
                            "not retrying to avoid duplicate delivery",
                            msg.local_id, msg.jid, msg.last_error,
                        )
                        with self._lock:
                            self._pending.pop(msg.local_id, None)
                        wx.CallAfter(self.main_window._on_message_unconfirmed, msg.local_id)
                        continue

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
                        wx.CallAfter(
                            self.main_window._on_message_sent,
                            msg.local_id,
                            msg.audio_path,
                            real_id if isinstance(real_id, str) else None,
                            msg.jid,
                            quote_lost,
                        )
                    else:
                        msg.fail_count += 1
                        if not msg.last_error:
                            msg.last_error = getattr(self.main_window, "_last_send_error", "") or ""
                        logging.warning("[MessageQueue] send failed for %s jid=%s attempt=%s/%s",
                                        msg.local_id, msg.jid, msg.fail_count, self._MAX_RETRIES)
                        if (not retryable_failure) or msg.fail_count >= self._MAX_RETRIES:
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
                    # Only unexpected programming errors reach here — transport
                    # failures are classified inside the send_* methods.
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
