"""Serialize account presence writes, keeping only the latest pending state."""
import logging
import threading
from collections.abc import Callable


class OnlinePresenceSender:
    def __init__(self, send: Callable[..., None]):
        self._send = send
        self._lock = threading.Lock()
        self._pending: str | None = None
        self._diagnostic = None
        self._running = False

    def submit(self, presence: str | None, *, diagnostic=None) -> None:
        """None drops queued work on disconnect/shutdown; no persistent worker."""
        with self._lock:
            self._pending = presence
            self._diagnostic = diagnostic
            if self._running or presence is None:
                return
            self._running = True
            try:
                threading.Thread(target=self._drain, daemon=True,
                                 name="online-presence").start()
            except Exception:
                self._running = False
                logging.exception("[presence] could not start sender")

    def _drain(self) -> None:
        while True:
            with self._lock:
                presence = self._pending
                diagnostic = self._diagnostic
                self._pending = None
                self._diagnostic = None
                if presence is None:
                    self._running = False
                    return
            try:
                if diagnostic is None:
                    self._send(presence)
                else:
                    self._send(presence, diagnostic=diagnostic)
            except Exception:
                # A failed request must not strand a newer offline update.
                logging.exception("[presence] sender failed")
