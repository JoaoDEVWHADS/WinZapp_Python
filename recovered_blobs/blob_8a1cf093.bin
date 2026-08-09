"""Pure, wx-free connection-state decision logic (client/connection_state.py).

Extracted from MainWindow.check_wa_connection_http so the "is this unlinked
status a real logout, a still-resuming session, or a resume that has failed for
too long" decision is unit-testable without the whole wx/requests stack.

Background (the bug this fixes): on launch WPPConnect restores a saved session
through INITIALIZING → (transient) QRCODE/notLogged → inChat. The client polls
status over HTTP and used to treat a transient QRCODE as a logout, wiping the
local database of a session the server was busy logging back in (confirmed in a
real log: node reported 'inChat' the same second the client wiped). The rule
below encodes: a logout is only real once we've actually been connected THIS run
and then go unlinked; before any connect this run, an unlinked status means the
session is still resuming — never wipe — and only after a long resume timeout do
we surface the pairing dialog WITHOUT wiping data.
"""

from __future__ import annotations

# Decision outcomes.
ONLINE = "online"                 # status is a connected/active-good state
RESUMING = "resuming"             # unlinked, never connected yet — keep waiting
RESUME_FAILED = "resume_failed"   # unlinked too long while resuming — pair, NO wipe
LOGOUT = "logout"                 # confirmed logout after being connected — wipe

UNLINKED_STATES = ("notLogged", "QRCODE")


def classify_unlinked(
    status: str,
    *,
    ever_connected: bool,
    logout_strikes: int,
    resume_strikes: int,
    logout_confirm_strikes: int,
    resume_fail_strikes: int,
) -> str:
    """Classify an unlinked status reading into an action.

    Args mirror MainWindow state at the time of the reading:
      status            — the WPPConnect status string just read.
      ever_connected    — have we announced a live connection THIS run?
      logout_strikes    — consecutive unlinked readings AFTER being connected.
      resume_strikes    — consecutive unlinked readings while never connected.
      *_strikes thresholds — the confirm limits.

    Returns one of ONLINE / RESUMING / RESUME_FAILED / LOGOUT. Callers pass the
    strike counts they will have AFTER incrementing for this reading, so the
    thresholds are simple >= comparisons.

    Only unlinked states are meaningful here; a non-unlinked status is ONLINE
    (the caller resets both strike counters).
    """
    if status not in UNLINKED_STATES:
        return ONLINE
    if not ever_connected:
        # Session still restoring from its saved profile — a failed resume is
        # NOT proof of an unlink, so we never wipe. Only after a long timeout do
        # we surface the pairing dialog (without wiping).
        if resume_strikes >= resume_fail_strikes:
            return RESUME_FAILED
        return RESUMING
    # We were connected this run and now read unlinked → a real logout, once
    # confirmed by enough consecutive readings.
    if logout_strikes >= logout_confirm_strikes:
        return LOGOUT
    return RESUMING  # connected before, brief blip — keep waiting (no wipe)
