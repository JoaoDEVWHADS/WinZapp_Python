"""Serialize UI cancellation with the updater's irreversible installer spawn.

The worker never queries wx. Only the UI may grant the handoff while its modal
loop is running. Closing the modal before that grant permanently cancels it.
After the grant, even an unexpected modal return must await the worker's verdict.
"""

import threading


class InstallHandoff:
    def __init__(self):
        self._lock = threading.Lock()
        self.cancelled = threading.Event()
        self.decided = threading.Event()
        self.settled = threading.Event()
        self._committing = False

    def cancel(self) -> bool:
        """True if cancellation won; False once spawning has been committed."""
        with self._lock:
            if self._committing:
                return False
            self.cancelled.set()
            self.decided.set()
            return True

    def begin(self, modal_running: bool) -> bool:
        """UI thread only. Exactly one grant, and never after cancellation."""
        with self._lock:
            if self._committing:
                return False
            if not modal_running:
                self.cancelled.set()
            granted = not (self.cancelled.is_set() or self._committing
                           or self.settled.is_set())
            if granted:
                self._committing = True
            self.decided.set()
            return granted

    def may_spawn(self) -> bool:
        with self._lock:
            return self._committing and not self.cancelled.is_set()
