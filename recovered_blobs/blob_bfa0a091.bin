"""Tests for the pure connection-state classifier (client/connection_state.py).

These lock in the fix for the account-wiping bug: a paired session restoring
from its saved profile briefly reports QRCODE/notLogged, and the client used to
treat that as a logout and wipe the local database — even though the server was
logging back in (a real log showed 'inChat' the same second the client wiped).
"""

import connection_state as cs

LOGOUT_CONFIRM = 4
RESUME_FAIL = 20


def _classify(status, ever, logout_strikes, resume_strikes):
    return cs.classify_unlinked(
        status,
        ever_connected=ever,
        logout_strikes=logout_strikes,
        resume_strikes=resume_strikes,
        logout_confirm_strikes=LOGOUT_CONFIRM,
        resume_fail_strikes=RESUME_FAIL,
    )


def test_good_status_is_online():
    assert _classify("inChat", True, 0, 0) == cs.ONLINE
    assert _classify("CONNECTED", False, 5, 5) == cs.ONLINE


def test_resume_never_wipes_before_connect_this_run():
    # THE bug: unlinked while never connected this run → resuming, NEVER logout,
    # no matter how the logout strike count looks.
    assert _classify("QRCODE", False, 99, 1) == cs.RESUMING
    assert _classify("notLogged", False, 0, 1) == cs.RESUMING


def test_resume_failed_only_after_long_timeout():
    # Still resuming just under the timeout...
    assert _classify("QRCODE", False, 0, RESUME_FAIL - 1) == cs.RESUMING
    # ...and only once the resume has dragged on past the threshold do we offer
    # the pairing dialog (the caller passes wipe=False for this outcome).
    assert _classify("QRCODE", False, 0, RESUME_FAIL) == cs.RESUME_FAILED


def test_logout_only_after_connected_then_unlinked_confirmed():
    # Connected this run, now unlinked, but not enough strikes yet → keep waiting.
    assert _classify("QRCODE", True, LOGOUT_CONFIRM - 1, 0) == cs.RESUMING
    # Enough consecutive unlinked readings after being connected → real logout.
    assert _classify("QRCODE", True, LOGOUT_CONFIRM, 0) == cs.LOGOUT


def test_logout_needs_connection_first():
    # Even with a huge logout-strike count, without ever connecting this run it
    # must never be classified as a logout (that was the destructive bug).
    assert _classify("QRCODE", False, 1000, 0) == cs.RESUMING
