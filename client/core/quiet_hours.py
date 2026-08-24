"""Windows Focus Assist ("Não incomodar") detection.

SHQueryUserNotificationState (shell32) is the one documented Win32 API that
reflects Focus Assist state without requiring the app to be a packaged UWP
app — it's also what Windows itself effectively consults to decide whether
one of ITS OWN toast notifications gets a sound/banner. WinZapp's
background-notification sound (MainWindow.play_background_notification_sound)
is a raw audio file played directly through BASS/sound_lib, entirely outside
that toast pipeline, so it never got the same treatment — reported live as
still playing with Focus Assist on Priority Only / Alarms Only.

Deliberately NOT applied to message_current_sound (a message arriving in the
conversation the user already has open and focused) or to incoming-call
alerts — Focus Assist is about notifications competing for attention while
the user is doing something else, neither of which applies there.
"""

import sys

# QUERY_USER_NOTIFICATION_STATE values (shellapi.h)
_QUNS_NOT_PRESENT = 1
_QUNS_BUSY = 2
_QUNS_RUNNING_D3D_FULL_SCREEN = 3
_QUNS_PRESENTATION_MODE = 4
_QUNS_ACCEPTS_NOTIFICATIONS = 5
_QUNS_QUIET_TIME = 6
_QUNS_APP = 7

# States in which Windows would itself suppress a toast's sound/banner: a
# fullscreen app/game, a presentation, or Focus Assist (both "Priority only"
# and "Alarms only" surface here as QUNS_QUIET_TIME — Windows doesn't expose
# a finer-grained value through this API).
_SUPPRESSED_STATES = {
    _QUNS_BUSY, _QUNS_RUNNING_D3D_FULL_SCREEN,
    _QUNS_PRESENTATION_MODE, _QUNS_QUIET_TIME,
}


def should_suppress_notification_sound(state: int) -> bool:
    """Pure mapping from a QUERY_USER_NOTIFICATION_STATE value to whether the
    background-notification sound should be skipped. Split out from
    is_quiet_hours_active() so the decision table is testable without
    touching the real Win32 API."""
    return state in _SUPPRESSED_STATES


def _query_notification_state():
    """Raw SHQueryUserNotificationState call, isolated in its own function so
    tests can stub it without reaching into ctypes.windll. Returns None on
    any failure (off-Windows, API error, missing DLL, ...)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        state = ctypes.c_int()
        result = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if result != 0:  # S_OK == 0
            return None
        return state.value
    except Exception:
        return None


def is_quiet_hours_active() -> bool:
    """True if Windows is currently in a state where it would itself
    suppress a toast notification's sound (Focus Assist on, a fullscreen
    app/game, presentation mode, ...).

    Fails open (False) off-Windows or on any API failure — an API failure is
    a reason to fall back to the pre-existing behavior (always play), not to
    go silent for a reason nobody can see.
    """
    state = _query_notification_state()
    if state is None:
        return False
    return should_suppress_notification_sound(state)
