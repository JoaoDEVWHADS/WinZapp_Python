"""Tests for the lock around MainWindow._act_on_unlink_decision().

check_wa_connection_http() and _handle_local_auth_rejected() call this from
several independent threads (the health-check loop, _run_sync's tight poll,
wx.CallAfter callbacks). Before this lock, a bare check-then-set on
_logout_handled was a real race: two callers could both read it False before
either set it True, and both would fire _on_disconnect() -- a real incident
this codebase hit once already (two wipes logged inside the same second,
from two callers observing the same confirmed-unlinked reading).

This drives many real threads into _act_on_unlink_decision() at once (a
Barrier makes them actually overlap, not just run one after another) and
asserts the destructive action only ever fires once -- deterministically,
not "usually", since the whole point of the lock is to make this no longer
depend on timing.
"""

import threading
import time

import connection_state as cs
from main import MainWindow


class _Recorder:
    def __init__(self):
        self.played = 0

    def play(self):
        self.played += 1


class _I18n:
    @staticmethod
    def t(key):
        return key


class _Stub:
    _act_on_unlink_decision = MainWindow._act_on_unlink_decision

    def __init__(self, *, still_linked=False):
        self._unlink_decision_lock = threading.Lock()
        self._still_linked = still_linked
        self.still_linked_probe_calls = 0
        self._probe_calls_lock = threading.Lock()
        self.error_sound = _Recorder()
        self.i18n = _I18n()
        self.app_name = "WinZapp"
        self.disconnect_calls = []
        self._disconnect_lock = threading.Lock()
        self._logout_strikes = 4
        self._resume_fail_strikes = 20

    def _still_linked_on_server(self):
        with self._probe_calls_lock:
            self.still_linked_probe_calls += 1
        # The real implementation makes a blocking HTTP call here, which
        # releases the GIL for the duration — exactly the window a second
        # thread can slip through a non-atomic check-then-set in. A trivial
        # in-memory stub would never actually exercise that race, so this
        # sleeps briefly to stand in for it.
        time.sleep(0.01)
        return self._still_linked

    def _on_disconnect(self, wipe=True):
        with self._disconnect_lock:
            self.disconnect_calls.append(wipe)


def _call_locked(stub, decision, log_label="test"):
    """What both real call sites do: hold the lock across the whole
    decision, not just the strike counting."""
    with stub._unlink_decision_lock:
        stub._act_on_unlink_decision(decision, log_label=log_label)


def _run_concurrently(target, n=25, timeout=10):
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        target()

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout)
        assert not t.is_alive(), "a worker thread hung — possible deadlock"


def _patch_wx(monkeypatch):
    # wx.CallAfter runs its callback inline and synchronously here, so the
    # logout dialog/_on_disconnect() call happens to the queued threads
    # still logically "inside" the decision — the same shape a real 10s
    # _still_linked_on_server() HTTP call blocking under the lock has.
    monkeypatch.setattr("main.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr("main.wx.MessageBox", lambda *a, **kw: None)
    monkeypatch.setattr("main.wx.OK", 0, raising=False)
    monkeypatch.setattr("main.wx.ICON_ERROR", 0, raising=False)


class TestConfirmedLogoutFiresExactlyOnce:
    def test_many_concurrent_confirmed_logouts_wipe_only_once(self, monkeypatch):
        _patch_wx(monkeypatch)
        stub = _Stub(still_linked=False)

        _run_concurrently(lambda: _call_locked(stub, cs.LOGOUT), n=25)

        assert stub.disconnect_calls == [True]

    def test_many_concurrent_resume_failed_readings_pair_only_once(self, monkeypatch):
        _patch_wx(monkeypatch)
        stub = _Stub()

        _run_concurrently(lambda: _call_locked(stub, cs.RESUME_FAILED), n=25)

        assert stub.disconnect_calls == [False]


class TestStillLinkedVetoUnderConcurrency:
    def test_a_still_linked_phone_never_wipes_even_under_contention(self, monkeypatch):
        _patch_wx(monkeypatch)
        stub = _Stub(still_linked=True)

        _run_concurrently(lambda: _call_locked(stub, cs.LOGOUT), n=25)

        assert stub.disconnect_calls == []
