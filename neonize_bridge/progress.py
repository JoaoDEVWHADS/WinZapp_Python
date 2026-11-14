"""Real progress of media upload and download: the pure logic (no neonize, no
network) that `transfers.py` wires to the DLL fork.

WinZapp listens to `media-upload-progress` ({uploadId, progress 0..1, session})
and `media-download-progress` ({progressId, progress 0..1, session}). The bridge
did not emit them: the bar stood still until the send finished. Here are the
calculations (percent -> fraction, file size -> fraction), the limiter (only
emits when the whole percent advances and at most every ~250 ms; 100% always
goes through) and the `Tracker`, which polls a reading on a thread of its own.

Tested in test_progress.py.
"""
import logging
import threading
import time

log = logging.getLogger("bridge")

#: seconds between two progress readings
READ_INTERVAL = 0.3
#: minimum seconds between two events (100% ignores it)
MIN_INTERVAL = 0.25
#: while the file grows, never goes past this: only the end of the transfer says 100%
IN_PROGRESS_CEILING = 0.99
_MAX_ID_SIZE = 200


def fraction_from_percent(percent):
    """0..100 (what TransferProgress returns) -> 0.0..1.0; None when there is no
    reading (-1 = unknown key, None, text, NaN)."""
    try:
        value = float(percent)
    except (TypeError, ValueError):
        return None
    if value != value or value < 0:
        return None
    return min(value, 100.0) / 100.0


def fraction_from_file(current, expected):
    """Bytes already written / expected bytes -> 0.0..IN_PROGRESS_CEILING, or None
    when it cannot be known (unknown expected size, file not there yet)."""
    try:
        current, expected = int(current), int(expected)
    except (TypeError, ValueError):
        return None
    if expected <= 0 or current < 0:
        return None
    return min(current / expected, IN_PROGRESS_CEILING)


def progress_id_of(body):
    """The `progressId` the client sends in the get-media body, or '' (no JSON
    body, another type, empty)."""
    if not isinstance(body, dict):
        return ""
    value = body.get("progressId")
    if not isinstance(value, str):
        return ""
    return value.strip()[:_MAX_ID_SIZE]


def upload_event(session, upload_id, fraction):
    return {"uploadId": upload_id, "progress": round(fraction, 4), "session": session}


def download_event(session, progress_id, fraction):
    return {"progressId": progress_id, "progress": round(fraction, 4), "session": session}


class Limiter:
    """Decides whether a reading becomes an event: the whole percent has to have
    advanced and, except for 100%, `minimum` seconds have to have passed since
    the last event. Never goes back."""

    def __init__(self, minimum=MIN_INTERVAL):
        self.minimum = minimum
        self.pct = -1
        self.when = None

    @property
    def finished(self):
        return self.pct >= 100

    def decide(self, fraction, now):
        if fraction is None:
            return False
        pct = int(round(min(max(fraction, 0.0), 1.0) * 100))
        if pct <= self.pct:
            return False
        if pct < 100 and self.when is not None and now - self.when < self.minimum:
            return False
        self.pct, self.when = pct, now
        return True


class Tracker:
    """Polls `read()` (returns a fraction 0..1 or None) every `interval` on a
    thread and calls `emit(fraction)` through the `Limiter`. Use as a context
    around the transfer; `finish()` (only on success) emits the 100%."""

    def __init__(self, read, emit, *, interval=READ_INTERVAL,
                 minimum=MIN_INTERVAL, clock=time.monotonic):
        self._read, self._emit = read, emit
        self._interval, self._clock = interval, clock
        self._limiter = Limiter(minimum)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None

    def _emit_if_fits(self, fraction):
        with self._lock:
            if not self._limiter.decide(fraction, self._clock()):
                return
            try:
                self._emit(fraction)
            except Exception:
                log.exception("progress: emit failed")

    def step(self):
        """One reading. Never raises: a bad reading just skips the event."""
        try:
            fraction = self._read()
        except Exception:
            return
        self._emit_if_fits(fraction)

    def _loop(self):
        while not self._stop_event.wait(self._interval):
            self.step()

    def begin(self):
        self._thread = threading.Thread(target=self._loop, name="progress", daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def finish(self):
        """The transfer ended well: stops the probe and makes sure of the 100%."""
        self.stop()
        self._emit_if_fits(1.0)

    def __enter__(self):
        return self.begin()

    def __exit__(self, *_):
        self.stop()
        return False
