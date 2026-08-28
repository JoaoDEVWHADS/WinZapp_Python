"""Tests for the wake-from-suspend connection-state reset
(connection_state.reset_state_for_resume) and its interplay with
classify_unlinked.

Locks in the fix for the hibernation account-wipe bug: a laptop hibernated
overnight, and on resume two of three paired accounts lost their WhatsApp
session and demanded a fresh QR scan — even though their WPPConnect Chrome
profiles were still valid and the local database was intact.

Root cause: across a suspend the ``_wa_connect_announced`` latch stayed True
from before the machine slept. After waking, WhatsApp Web inside Chrome is
briefly disconnected, so WPPConnect reports a transient QRCODE/notLogged.
classify_unlinked escalates to a *logout* — dropping the token and the paired
flag — only when we were connected THIS run (ever_connected). With the stale
latch True, the transient post-wake QRCODE was classified as a real logout
after _LOGOUT_CONFIRM_STRIKES.

reset_state_for_resume makes a resume behave like a fresh launch:
ever_connected=False, so a transient unlinked reading is RESUMING (never a
wipe), and only a genuinely dead session eventually surfaces the pairing dialog
via RESUME_FAILED (also no wipe).

Pure/wx-free — imports connection_state only, so it runs everywhere (no wx /
socketio / accessible_output2 needed, unlike tests that import main).
"""

import time
import types

import connection_state as cs

LOGOUT_CONFIRM = 4
RESUME_FAIL = 20


def _stale_stub():
    """A stub pre-loaded to look like an account that was online before the
    machine slept: connected latch set, and stale strike tallies as if the
    health checker had already seen some post-wake unlinked readings."""
    return types.SimpleNamespace(
        _wa_http_fail_strikes=3,
        _offline_probe_strikes=5,
        _logout_strikes=3,            # dangerously close to a confirmed logout
        _resume_fail_strikes=7,
        _still_linked_vetoes=4,       # one short of the veto limit, from before the sleep
        _logout_handled=True,
        _wa_connect_announced=True,   # THE stale latch that caused the wipe
        _wa_startup_time=time.time() - 100_000,  # long-expired grace window
    )


def test_reset_clears_the_connected_latch():
    stub = _stale_stub()
    cs.reset_state_for_resume(stub, time.time())
    # The core of the fix: after a resume we are NOT "connected this run".
    assert stub._wa_connect_announced is False


def test_reset_zeroes_all_strike_tallies_and_logout_latch():
    stub = _stale_stub()
    cs.reset_state_for_resume(stub, time.time())
    assert stub._wa_http_fail_strikes == 0
    assert stub._offline_probe_strikes == 0
    assert stub._logout_strikes == 0
    assert stub._resume_fail_strikes == 0
    assert stub._logout_handled is False
    # The host-device veto run counts CONSECUTIVE vetoes
    # (MainWindow._STILL_LINKED_VETO_LIMIT), and a hibernation is as much a
    # break in that run as a healthy reading is. Carried across, four stale
    # vetoes plus the first post-wake one hit the limit and park a session the
    # probe says is linked on the pairing dialog.
    assert stub._still_linked_vetoes == 0


def test_reset_reearms_startup_grace_window():
    stub = _stale_stub()
    now = time.time()
    cs.reset_state_for_resume(stub, now)
    assert stub._wa_startup_time == now


def test_after_reset_transient_qrcode_is_resuming_not_logout():
    """End-to-end intent: feed the post-reset state into the same classifier
    the health checker uses. A transient unlinked reading right after wake must
    classify as RESUMING (never LOGOUT), so the token is never wiped."""
    stub = _stale_stub()
    cs.reset_state_for_resume(stub, time.time())
    # The health checker increments the resume tally for one reading
    # (ever_connected is now False, so it counts as a resume strike).
    stub._resume_fail_strikes += 1
    decision = cs.classify_unlinked(
        "QRCODE",
        ever_connected=stub._wa_connect_announced,
        logout_strikes=stub._logout_strikes,
        resume_strikes=stub._resume_fail_strikes,
        logout_confirm_strikes=LOGOUT_CONFIRM,
        resume_fail_strikes=RESUME_FAIL,
    )
    assert decision == cs.RESUMING


def test_without_reset_stale_latch_would_have_logged_out():
    """Documents the pre-fix failure mode: with the stale connected latch and
    the accumulated logout strikes, the very next QRCODE reading escalated to a
    confirmed LOGOUT (which wiped the token)."""
    stub = _stale_stub()  # NO reset — as the buggy _on_power_resume left it
    stub._logout_strikes += 1  # one more post-wake unlinked reading -> 4
    decision = cs.classify_unlinked(
        "QRCODE",
        ever_connected=stub._wa_connect_announced,  # still True
        logout_strikes=stub._logout_strikes,
        resume_strikes=stub._resume_fail_strikes,
        logout_confirm_strikes=LOGOUT_CONFIRM,
        resume_fail_strikes=RESUME_FAIL,
    )
    assert decision == cs.LOGOUT


# ── strike rate-limiting (should_count_strike) ────────────────────────────────
# Regression guard for the "fast poll loop wipes a live session" bug: strike
# thresholds are tuned for real elapsed time, but tight loops (e.g. _run_sync's
# 0.2s cadence) counted every reading, racing to 20 strikes in ~6s and killing a
# session WhatsApp had just re-logged in. Strikes must count at most once per
# STRIKE_MIN_INTERVAL so N strikes means ~N intervals of wall-clock time.


def test_first_strike_always_counts():
    # No prior strike this run (ts 0) -> always count, whatever `now` is.
    assert cs.should_count_strike(1000.0, 0.0) is True


def test_rapid_readings_within_interval_do_not_count():
    last = 1000.0
    # A 0.2s-cadence poll loop: every reading lands inside the interval.
    assert cs.should_count_strike(last + 0.2, last) is False
    assert cs.should_count_strike(last + 2.9, last) is False


def test_reading_after_interval_counts():
    last = 1000.0
    assert cs.should_count_strike(last + cs.STRIKE_MIN_INTERVAL_SECONDS, last) is True
    assert cs.should_count_strike(last + 30.0, last) is True


def test_fast_loop_cannot_reach_resume_fail_before_real_time_elapses():
    """End-to-end: simulate _run_sync's 25 readings at 0.2s each (~5s total).
    With rate-limiting, far fewer than RESUME_FAIL strikes accrue, so a session
    that is mid-resume is never force-killed by a tight poll loop alone."""
    t = 1000.0
    last_ts = 0.0
    strikes = 0
    for _ in range(25):              # _run_sync: for _ in range(25)
        if cs.should_count_strike(t, last_ts):
            strikes += 1
            last_ts = t
        t += 0.2                     # time.sleep(0.2)
    # ~5s of readings -> at most ceil(5/3)+1 strikes, nowhere near RESUME_FAIL(20).
    assert strikes < RESUME_FAIL
    assert cs.classify_unlinked(
        "QRCODE", ever_connected=False,
        logout_strikes=0, resume_strikes=strikes,
        logout_confirm_strikes=LOGOUT_CONFIRM, resume_fail_strikes=RESUME_FAIL,
    ) == cs.RESUMING


# ── zombie-session detection after resume (is_zombie_session_after_resume) ────
# Regression guard for the "wakes up offline, must restart the app" bug: after
# hibernation WhatsApp Web loses its stream and never rebuilds it, but WPPConnect
# keeps a stale CONNECTED status, so the app sits offline forever. That specific
# state (not connected + stale CONNECTED + network up) must trigger an active
# session restart — while a genuine outage (network down) must NOT.


def test_zombie_when_stale_connected_but_stream_dead_and_network_up():
    # isConnected()==false, status still CONNECTED, WhatsApp host reachable.
    assert cs.is_zombie_session_after_resume(
        wa_connected=False, status="CONNECTED", host_reachable=True) is True
    # 'open' is the other live-session status string WPPConnect uses.
    assert cs.is_zombie_session_after_resume(
        wa_connected=False, status="open", host_reachable=True) is True


def test_not_zombie_when_actually_connected():
    assert cs.is_zombie_session_after_resume(
        wa_connected=True, status="CONNECTED", host_reachable=True) is False


def test_not_zombie_when_network_down_is_a_plain_outage():
    # Network unreachable -> real outage, leave it alone to recover naturally.
    assert cs.is_zombie_session_after_resume(
        wa_connected=False, status="CONNECTED", host_reachable=False) is False


def test_not_zombie_for_non_connected_statuses():
    # CLOSED auto-starts elsewhere; QRCODE/notLogged is a real pairing need.
    for status in ("CLOSED", "DESTROYED", "QRCODE", "notLogged", "INITIALIZING", ""):
        assert cs.is_zombie_session_after_resume(
            wa_connected=False, status=status, host_reachable=True) is False

