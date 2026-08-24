"""Tests for the gap trigger_sync_if_needed() actually enforces between two
sync rounds.

The backoff was structurally dead for exactly the accounts it exists to
protect. start_sync() stamped _last_sync_attempt_ts on the way *in*, and
trigger_sync_if_needed() measures its cooldown from that stamp — so a round
lasting longer than the cooldown had already exhausted it before it finished,
and the health checker (every 30 s) could start the next round immediately.

Measured on a 937-chat session: four full sync rounds in 37 minutes, with 17
seconds between the end of one and the start of the next, against a nominal
120 s cooldown. Stamping again on the way out is what makes the cooldown mean
"since the last round ended".

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the methods under test are bound to a plain stub carrying only the
attributes they touch — the same pattern the other main.py tests use.
"""

import threading
import time
import types

import pytest

import main
from main import MainWindow


class _Stub:
    """Minimum surface start_sync()/trigger_sync_if_needed() actually read."""

    def __init__(self, run_duration=0.0):
        self._ui_ready_event = threading.Event()
        self._ui_ready_event.set()
        self._initial_sync_running = False
        self._sync_completed = False
        self._sync_ever_started = False
        self._sync_run_id = 0
        self._sync_retry_count = 0
        self._last_sync_attempt_ts = 0.0
        self._wa_connected = True
        self.sync_thread = None
        self._sync_start_lock = threading.Lock()
        self._run_duration = run_duration
        self.ran = 0
        self.status_calls = []

    def _set_status(self, text):
        self.status_calls.append(text)

    def _run_sync(self):
        self.ran += 1
        if self._run_duration:
            time.sleep(self._run_duration)


def _bind(stub, *names):
    for name in names:
        setattr(stub, name, types.MethodType(getattr(MainWindow, name), stub))
    for name in ("_SYNC_RETRY_COOLDOWN",):
        setattr(stub, name, getattr(MainWindow, name))


@pytest.fixture
def stub(monkeypatch):
    # wx.CallAfter is the only wx touched here, and only to clear the status
    # text; run it inline so no event loop is required.
    monkeypatch.setattr(main.wx, "CallAfter",
                        lambda fn, *a, **kw: fn(*a, **kw))
    s = _Stub()
    _bind(s, "start_sync", "trigger_sync_if_needed", "_try_start_sync_thread")
    return s


class TestTheStampIsMadeOnTheWayOut:
    def test_a_finished_round_stamps_the_time_it_ended(self, stub):
        stub._run_duration = 0.2
        before = time.time()
        stub.start_sync()
        # The entry stamp would be <= `before + epsilon`; the exit stamp
        # cannot be earlier than when _run_sync() returned.
        assert stub._last_sync_attempt_ts >= before + 0.2

    def test_a_round_that_raises_still_stamps(self, stub):
        """The stamp lives in the finally block for the same reason the
        running flag does: a round that dies mid-way must not leave the next
        one free to start instantly."""
        def _boom():
            stub.ran += 1
            raise RuntimeError("sync exploded")
        stub._run_sync = _boom
        before = time.time()
        stub.start_sync()
        assert stub.ran == 1
        assert stub._last_sync_attempt_ts >= before

    def test_the_entry_stamp_is_kept_as_well(self, stub):
        """A round that returns immediately (no connection, for instance) is
        still covered — the entry stamp is what stops it spinning."""
        stub._run_sync = lambda: None
        before = time.time()
        stub.start_sync()
        assert stub._last_sync_attempt_ts >= before


class TestTheCooldownIsHonouredAfterALongRound:
    def test_the_captured_failure_no_longer_reproduces(self, stub):
        """The measured shape, scaled down: a round that outlasts its own
        cooldown, then the health checker arriving the moment it ends.

        The round has to genuinely take longer than the cooldown for this to
        exercise anything — that is the whole bug. With the entry stamp alone,
        the cooldown measured from a moment already in the past and had
        expired before the round even finished. Real durations rather than a
        patched clock, because start_sync() stamps the entry itself and there
        is nothing to preset."""
        stub._SYNC_RETRY_COOLDOWN = 0.1
        stub._run_duration = 0.3        # 3 x the cooldown, like 4 min vs 120 s
        stub.start_sync()
        stub._sync_completed = False
        stub._sync_retry_count = 1

        stub.ran = 0
        stub.trigger_sync_if_needed()
        thread = stub.sync_thread
        if thread is not None:
            thread.join(timeout=5)
        assert stub.ran == 0, "a new round started right after the last one ended"

    def test_a_round_is_allowed_once_the_cooldown_has_really_elapsed(self, stub):
        stub.start_sync()
        stub._sync_completed = False
        stub._sync_retry_count = 1
        stub._last_sync_attempt_ts = (
            time.time() - MainWindow._SYNC_RETRY_COOLDOWN - 1
        )
        stub.ran = 0
        stub.trigger_sync_if_needed()
        # trigger_sync_if_needed() starts a thread; wait for it to run.
        thread = stub.sync_thread
        if thread is not None:
            thread.join(timeout=5)
        assert stub.ran == 1

    def test_a_completed_sync_is_never_restarted(self, stub):
        stub._sync_completed = True
        stub.ran = 0
        stub.trigger_sync_if_needed()
        assert stub.ran == 0

    def test_nothing_starts_while_disconnected(self, stub):
        stub._wa_connected = False
        stub._last_sync_attempt_ts = 0
        stub.ran = 0
        stub.trigger_sync_if_needed()
        assert stub.ran == 0
