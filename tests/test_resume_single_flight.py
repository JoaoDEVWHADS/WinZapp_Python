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

import os
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


# ── wake-recovery retry gate (recovery_settled) ───────────────────────────────
# Regression guard for the "one account never comes back after hibernation" bug:
# a hibernation-resumed Chrome hands puppeteer a detached frame, start-session
# throws in waitForLogin, and the session hangs in INITIALIZING forever. The
# recovery loop retries a full close/start cycle until the status leaves
# INITIALIZING for a resolved state.


def test_still_initializing_is_not_settled():
    # The exact hang state — must keep retrying.
    assert cs.recovery_settled("INITIALIZING") is False


def test_empty_status_is_not_settled():
    # Unreadable status (probe failed) — treat as not settled, keep trying.
    assert cs.recovery_settled("") is False
    assert cs.recovery_settled(None) is False


def test_resolved_statuses_are_settled():
    # CONNECTED/open = recovered; QRCODE/notLogged = a real pairing need handled
    # elsewhere. All stop the retry loop.
    for status in ("CONNECTED", "open", "QRCODE", "notLogged", "CLOSED"):
        assert cs.recovery_settled(status) is True


# ── narrowed recovery decisions (GPT r2): success vs user-action vs keep-going ──
# The old `settled = status != INITIALIZING` was too broad — it treated QRCODE
# and even CLOSED as "done". The rebuilt recovery distinguishes a genuine
# CONNECTED success from a user-action (pairing) stop and from transient churn.


def test_recovery_connected_only_true_when_really_connected():
    assert cs.recovery_connected("CONNECTED") is True
    assert cs.recovery_connected("open") is True
    for status in ("QRCODE", "UNPAIRED", "notLogged", "INITIALIZING", "CLOSED", "", None):
        assert cs.recovery_connected(status) is False


def test_recovery_needs_user_action_for_pairing_states():
    for status in ("QRCODE", "UNPAIRED", "UNPAIRED_IDLE", "notLogged", "PHONECODE"):
        assert cs.recovery_needs_user_action(status) is True
    for status in ("CONNECTED", "INITIALIZING", "CLOSED", "", None):
        assert cs.recovery_needs_user_action(status) is False


def test_recovery_should_stop_on_connected_or_user_action_only():
    # Stop the restart loop on success OR pairing need...
    for status in ("CONNECTED", "open", "QRCODE", "UNPAIRED", "notLogged"):
        assert cs.recovery_should_stop(status) is True
    # ...but keep going while still churning / unreadable / merely closed.
    for status in ("INITIALIZING", "", None, "CLOSED"):
        assert cs.recovery_should_stop(status) is False


def test_initializing_restart_due_is_time_based_not_count_based():
    grace = 90.0
    # Just entered INITIALIZING: not due yet.
    assert cs.initializing_restart_due(1000.0, 1000.0, grace) is False
    # Halfway through the grace window: still not due.
    assert cs.initializing_restart_due(1000.0, 1044.0, grace) is False
    # One second short of the grace: not due.
    assert cs.initializing_restart_due(1000.0, 1089.0, grace) is False
    # At/after the grace with no progress: due for one restart.
    assert cs.initializing_restart_due(1000.0, 1090.0, grace) is True
    assert cs.initializing_restart_due(1000.0, 1200.0, grace) is True


def test_empty_status_is_not_progress():
    # A failed REST probe ('') must NOT reset the no-progress clock, or flaky
    # probes would mask a genuine INITIALIZING hang forever (GPT r3 #8).
    assert cs.is_progress_status("") is False
    assert cs.is_progress_status(None) is False
    # INITIALIZING is the hang state itself — not progress.
    assert cs.is_progress_status("INITIALIZING") is False
    # Any other readable state is real progress.
    for status in ("CONNECTED", "open", "QRCODE", "CLOSED", "notLogged", "PAIRING"):
        assert cs.is_progress_status(status) is True


# ── abandoned-session cleanup path safety (safe_session_dir_to_delete) ─────────
# Guards the destructive rmtree of superseded WPPConnect userDataDirs: a session
# name must resolve to a direct child of the userDataDir root, or we refuse.


def _expected_dir(root: str, name: str) -> str:
    """What safe_session_dir_to_delete() returns for an accepted name.

    Built the same way the function builds it (abspath of the join) instead of
    hardcoding f"{root}/{name}": on Windows abspath adds the drive and uses
    backslashes, so the literal form only ever matched on POSIX and these
    assertions failed on the very platform WinZapp ships to.
    """
    return os.path.abspath(os.path.join(root, name))


def test_safe_session_dir_accepts_plain_session_name():
    root = "/data/api/userDataDir"
    name = "a" * 32
    assert cs.safe_session_dir_to_delete(root, name) == _expected_dir(root, name)


def test_safe_session_dir_rejects_traversal_and_absolute():
    root = "/data/api/userDataDir"
    # '..' escaping the root, path separators, and absolute paths must all be
    # refused so a bad session name can never delete outside userDataDir.
    for bad in ("../secret", "..", ".", "a/b", "/etc", "sub/../../x", "",
                "a\\b", "C:evil", "name:stream", "name.with.dots", "a b"):
        assert cs.safe_session_dir_to_delete(root, bad) is None


def test_safe_session_dir_accepts_only_allowlisted_names():
    root = "/data/api/userDataDir"
    # Real WPPConnect session names: hex tokens, dashes, underscores.
    for good in ("a" * 32, "63d3fd5cf2aecaffb807a9ecb17af07d",
                 "sess_123-abc", "A1b2C3"):
        assert cs.safe_session_dir_to_delete(root, good) == _expected_dir(root, good)


def test_safe_session_dir_rejects_empty_root():
    assert cs.safe_session_dir_to_delete("", "a" * 32) is None
