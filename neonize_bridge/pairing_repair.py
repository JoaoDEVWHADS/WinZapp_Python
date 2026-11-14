"""Repairs a pairing that WhatsApp refused after the QR was scanned.

whatsmeow only writes the refusal in its log. Two lines matter:

- `Failed to pair device: invalid device identity HMAC`: the QR on screen no
  longer matches the keys the client holds (the server rotated the ADV key, or
  a pairing code was asked for in the same connection). Scanning it can never
  work; the connection has to start again with new keys to get a QR that does.
- `Failed to handle code pair notification`: the same for a pairing code.

TeleZapp lives with the same whatsmeow and fixed it by listening to that log,
wiping the session keys and starting over, at most 3 times (its CHANGELOG,
2026.10.21). Here the QR failure restarts the pairing and the code failure only
tells the client: a new code would be minted for a number nobody asked about,
and the per-number quota outlives the process (docs/traps/pairing-flow.md).
Pure functions and a log handler; the restart itself is `Session`'s.
"""
import logging
import os
import threading

import session_lifecycle

MAX_REPAIRS = 3
QR, CODE = "qr", "code"

# The database goes last: a failure half way must never leave a -wal that SQLite would
# replay into the next fresh session.db.
_FILES = ("session.db-wal", "session.db-shm", "session.db-journal", "session.db")


def failure_kind(text):
    """QR or CODE when the whatsmeow log line says pairing was refused, else None."""
    if "Failed to handle code pair notification" in text:
        return CODE
    if "Failed to pair device" in text:
        return QR
    return None


class Budget:
    """How many times in a row a pairing may be restarted. A connected session
    gives it back: the limit is per pairing attempt, not per process."""

    def __init__(self, limit=MAX_REPAIRS):
        self.limit = limit
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.limit:
            return False
        self.used += 1
        return True

    def reset(self):
        self.used = 0


class FailureHandler(logging.Handler):
    """Calls `on_failure(kind)` for each refusal that whatsmeow logs."""

    def __init__(self, on_failure):
        super().__init__(logging.ERROR)
        self.on_failure = on_failure

    def emit(self, record):
        try:
            kind = failure_kind(record.getMessage())
            if kind:
                self.on_failure(kind)
        except Exception:
            self.handleError(record)


def give_up_notice(name, message="WhatsApp refused the pairing") -> dict:
    """The `phoneCodeError` the client says out loud while its pairing dialog is
    up (`LinkCodeRefreshFailed`: the code or QR on screen is dead). Any other
    name is only read by the 90 s wait for a code, long over by then."""
    return {"session": name, "name": "LinkCodeRefreshFailed",
            "message": f"LinkCodeRefreshFailed: {message}", "rateLimited": False}


class Watch:
    """One handler on whatsmeow's log for every session of the bridge. Go's log
    lines carry no session name, so each refusal goes to the only session that
    is waiting for a scan; with two at once it is ambiguous and nobody is
    repaired (wiping the wrong account's keys is worse than a QR that stays
    dead until the user asks again)."""

    LOGGER = "whatsmeow.Client"

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}          # id(session) -> (session, generation, phone_number)
        self._handler = None

    def add(self, session, generation, phone_number):
        with self._lock:
            self._entries[id(session)] = (session, generation, phone_number)
            if self._handler is None:
                self._handler = FailureHandler(self._dispatch)
                logging.getLogger(self.LOGGER).addHandler(self._handler)

    def remove(self, session, generation):
        """Only the generation that added the entry can take it away."""
        with self._lock:
            entry = self._entries.get(id(session))
            if entry is not None and entry[1] == generation:
                del self._entries[id(session)]
            if not self._entries and self._handler is not None:
                logging.getLogger(self.LOGGER).removeHandler(self._handler)
                self._handler = None

    def _dispatch(self, kind):
        with self._lock:
            waiting = [e for e in self._entries.values()
                       if e[0].status == session_lifecycle.QRCODE
                       and e[0].lifecycle.current(e[1])]
        if len(waiting) == 1:
            session, generation, phone_number = waiting[0]
            session._on_pairing_failure(generation, kind, phone_number)
        elif waiting:
            logging.getLogger("bridge").warning(
                "WhatsApp refused a pairing while %d sessions wait for a scan; not repairing any",
                len(waiting))


WATCH = Watch()


def wipe_session_keys(folder) -> bool:
    """Deletes the WhatsApp keys of a session (never the message store). True
    when none of the files is left."""
    for name in _FILES:
        path = os.path.join(folder, name)
        try:
            if os.path.lexists(path):
                os.remove(path)
        except OSError:
            return False
    return not any(os.path.lexists(os.path.join(folder, n)) for n in _FILES)
