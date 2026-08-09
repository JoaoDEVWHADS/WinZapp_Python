"""Tests for the wake-from-suspend recovery single-flight guard
(connection_state.try_begin_resume_recovery / end_resume_recovery).

Locks in the fix for the multi-account hibernation race: after an ~8h
hibernation, the two INDEPENDENT wake triggers both fired for the same wake a
few seconds apart —

  1. EVT_POWER_RESUME (its own daemon thread), and
  2. the health-check clock-gap detector ("[wake-detect] sleep overran ...").

Both call MainWindow._recover_from_suspend, which runs close-session →
kill-orphan-Chrome → start-session. Overlapping runs interleaved: the second
run's kill-orphan sweep (chrome_cmdline_owns_session matches by session NAME
only) killed the fresh Chrome the first run's start-session had just spawned.
Observed live: the same Chrome PIDs killed twice, "start-session sent" logged
twice, and only 1 of 3 accounts recovered cleanly (the other two hung in
INITIALIZING / bounced to QRCODE-unpaired).

The fix makes recovery single-flight via a compare-and-set on a plain flag
guarded by a lock. While one recovery holds the flag, any further wake trigger
is dropped rather than piling a second interleaved pass on top.

Pure/wx-free — imports connection_state only, so it runs everywhere (no wx /
socketio / accessible_output2 needed, unlike tests that import main).
"""

import threading
import time
import types

import connection_state as cs


def _stub():
    return types.SimpleNamespace(_resume_recovery_active=False)


def test_first_caller_acquires_the_slot():
    stub = _stub()
    lock = threading.Lock()
    assert cs.try_begin_resume_recovery(stub, lock) is True
    assert stub._resume_recovery_active is True


def test_second_caller_is_dropped_while_active():
    """The core of the fix: a second trigger while a recovery is in flight must
    be refused, so only one close/kill/start pass runs per wake."""
    stub = _stub()
    lock = threading.Lock()
    assert cs.try_begin_resume_recovery(stub, lock) is True
    assert cs.try_begin_resume_recovery(stub, lock) is False


def test_end_releases_the_slot_for_a_later_wake():
    """Per-wake, not permanent: once a recovery finishes the flag is cleared, so
    the NEXT hibernation still triggers a fresh recovery."""
    stub = _stub()
    lock = threading.Lock()
    assert cs.try_begin_resume_recovery(stub, lock) is True
    cs.end_resume_recovery(stub, lock)
    assert stub._resume_recovery_active is False
    # A later, separate wake acquires again.
    assert cs.try_begin_resume_recovery(stub, lock) is True


def test_missing_flag_attribute_is_treated_as_not_active():
    """Defensive: an object that never had the flag set yet (getattr default)
    must still be acquirable, not crash."""
    stub = types.SimpleNamespace()  # no _resume_recovery_active at all
    lock = threading.Lock()
    assert cs.try_begin_resume_recovery(stub, lock) is True
    assert stub._resume_recovery_active is True


def test_concurrent_triggers_grant_exactly_one_slot():
    """Real-thread race: fire the two wake triggers from two threads at the same
    instant (both crossing the barrier together). Exactly one must win the slot
    — proving the compare-and-set is atomic under the lock, not check-then-set
    racy. This is the actual failure the live logs showed."""
    stub = _stub()
    lock = threading.Lock()
    results = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def trigger():
        barrier.wait()  # release both threads simultaneously
        got = cs.try_begin_resume_recovery(stub, lock)
        with results_lock:
            results.append(got)

    threads = [threading.Thread(target=trigger) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
        assert not t.is_alive()

    assert results.count(True) == 1, "more than one recovery slot granted"
    assert results.count(False) == 1
    assert stub._resume_recovery_active is True


def test_stress_many_concurrent_triggers_grant_exactly_one():
    """Same idea, scaled up: N simultaneous triggers must yield exactly one
    winner regardless of how many overlap."""
    stub = _stub()
    lock = threading.Lock()
    n = 50
    barrier = threading.Barrier(n)
    results = []
    results_lock = threading.Lock()

    def trigger():
        barrier.wait()
        got = cs.try_begin_resume_recovery(stub, lock)
        with results_lock:
            results.append(got)

    threads = [threading.Thread(target=trigger) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert results.count(True) == 1
    assert results.count(False) == n - 1


# ── shutdown flush gate (session_closed_after_flush) ──────────────────────────
# Regression guard for the "close one window, another account demands re-pair"
# bug: shutdown used a fixed sleep(2) before taskkill /F, too short for a large
# profile to flush WhatsApp Web's auth to leveldb -> the kill corrupted it ->
# "Session Unpaired" on next launch. The fix polls the real CLOSED signal
# instead of guessing a duration.


def test_closed_and_destroyed_and_empty_count_as_flushed():
    for status in ("CLOSED", "DESTROYED", ""):
        assert cs.session_closed_after_flush(status) is True


def test_none_status_counts_as_flushed():
    # A missing/None status (server no longer knows the session) is closed too.
    assert cs.session_closed_after_flush(None) is True


def test_live_statuses_are_not_yet_flushed():
    # While any of these hold, the browser is still up — killing now would cut
    # the flush. Must keep waiting.
    for status in ("CONNECTED", "open", "INITIALIZING", "QRCODE", "notLogged"):
        assert cs.session_closed_after_flush(status) is False
