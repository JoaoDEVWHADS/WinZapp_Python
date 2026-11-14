"""Coordinate HTTP session recovery and the bounded post-update UI grace."""

from functools import wraps
import logging
import threading
import time


def serialized_connection_probe(method):
    """Only one caller may inspect/start this account's session at a time."""
    @wraps(method)
    def probe(window, *args, **kwargs):
        lock = window.__dict__.setdefault("_connection_probe_lock", threading.Lock())
        if not lock.acquire(blocking=False):
            return
        try:
            if getattr(window, "_wpp_updating", False) or getattr(window, "_shutting_down", False):
                return
            return method(window, *args, **kwargs)
        finally:
            lock.release()
    return probe


def begin_update_reconnection(window):
    # API readiness does not mean that WhatsApp has finished logging in.
    window._wpp_reconnect_grace_until = time.monotonic() + 90.0
    window._wpp_pending_start_until = 0.0
    window._wpp_reconnect_started = time.monotonic()
    logging.info("[api-timing] step=whatsapp_reconnect event=start")


def finish_update_reconnection(window):
    started = getattr(window, "_wpp_reconnect_started", None)
    if started is not None:
        logging.info("[api-timing] step=whatsapp_reconnect event=end elapsed_s=%.3f outcome=connected",
                     time.monotonic() - started)
        window._wpp_reconnect_started = None
    window._wpp_reconnect_grace_until = 0.0
    window._wpp_pending_start_until = 0.0


def update_reconnection_pending(window):
    return time.monotonic() < getattr(window, "_wpp_reconnect_grace_until", 0.0)


def session_start_pending(window):
    return (getattr(window, "_wpp_pending_start_token", None) == window.token
            and time.monotonic() < getattr(window, "_wpp_pending_start_until", 0.0))


def note_session_start(window):
    # create() may still report CLOSED while waiting for login. A successful
    # POST (or an unanswered one) must not let the next probe launch another
    # browser immediately. A definite HTTP rejection clears this deadline.
    window._wpp_pending_start_token = window.token
    window._wpp_pending_start_until = time.monotonic() + 60.0
