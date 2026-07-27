"""Tests for the live-WebSocket-event gate, _live_events_ready().

The gate decides whether an event arriving over the socket is allowed to touch
self.chats.  It exists to close one specific window — between "window shown"
and "the sync thread actually started" — where letting events in would put
entries in the conversation list ahead of the sync that is about to fetch the
authoritative state anyway.

It used to express that as "_sync_completed or _initial_sync_running", which
silently also closed a second, much longer window nobody wanted closed: a sync
that runs to completion but marks itself incomplete (chat_list_settled False —
routine on a fresh pairing, see test_chat_list_settled.py) leaves _sync_completed
False, and start_sync()'s finally clears _initial_sync_running.  The app then
dropped every live message, reorder and LID mapping until the health checker's
next retry, up to 10 minutes later.

MainWindow is a wx.Frame and cannot be instantiated headlessly, so the method is
exercised as a plain function against a stub carrying only the state it reads.
"""

import threading

from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for _live_events_ready()."""

    def __init__(self, ui_ready=True, **kwargs):
        self._ui_ready_event = threading.Event()
        if ui_ready:
            self._ui_ready_event.set()
        self._sync_ever_started = False
        self._sync_completed = False
        self._initial_sync_running = False
        for key, value in kwargs.items():
            setattr(self, key, value)

    ready = MainWindow._live_events_ready


def test_dropped_before_ui_exists():
    """The original crash guard: events can arrive via a reused pairing socket
    before __init__ has created self.db/self.chats."""
    assert _Stub(ui_ready=False, _sync_ever_started=True).ready() is False


def test_dropped_before_any_sync_has_started():
    """The window a07dec7 set out to close, and which must stay closed: UI is up
    but no sync has begun, so the list shows only what was on disk."""
    assert _Stub().ready() is False


def test_accepted_while_sync_is_running():
    assert _Stub(_sync_ever_started=True, _initial_sync_running=True).ready() is True


def test_accepted_after_an_incomplete_sync():
    """The regression this gate caused.

    A sync that ran to the end and still marked itself incomplete leaves both
    _sync_completed and _initial_sync_running False.  There is no pending fetch
    guaranteed to re-deliver anything at that point, so dropping events loses
    them outright — this is the state the app spent most of its time in.
    """
    stub = _Stub(_sync_ever_started=True)
    assert stub._sync_completed is False
    assert stub._initial_sync_running is False
    assert stub.ready() is True


def test_accepted_after_a_completed_sync():
    assert _Stub(_sync_ever_started=True, _sync_completed=True).ready() is True


def test_latch_is_not_cleared_by_a_later_failed_sync():
    """_sync_ever_started is monotonic: a sync that later fails or is retried
    must not put the app back into "drop everything" mode."""
    stub = _Stub(_sync_ever_started=True, _sync_completed=True)
    # A dropped connection resets both of the old flags; the latch survives.
    stub._sync_completed = False
    stub._initial_sync_running = False
    assert stub.ready() is True


def test_missing_attribute_is_treated_as_not_started():
    """Defensive: the gate is read from socket.io threads that can, in principle,
    run against a half-built MainWindow."""
    stub = _Stub()
    del stub._sync_ever_started
    assert stub.ready() is False
