"""Reusable MSAA helper for suppressing one programmatic focus event.

This helper briefly removes ``STATE_SYSTEM_FOCUSED`` from a wx control's MSAA
state. NVDA's IAccessible path can then discard the corresponding focus event
before speech is queued. It is useful when a focus move is unavoidable.

It is intentionally **not** the voice-recording start mechanism anymore. NVDA
can receive focus through UIA as well as MSAA, and cancelling speech after
``SetFocus()`` is racy (the user-visible symptom was the clipped ``"env..."``
from the Send button). Voice recording now avoids the synthetic Send/Discard
focus move entirely whenever recording-focus suppression is requested.

Outside the short armed interval the accessible object answers
``wx.ACC_NOT_IMPLEMENTED``, so wx/Windows supplies the normal accessibility
state. The object is installed once per window and reused because
``SetAccessible()`` transfers ownership to C++.
"""

import logging

import wx

# Where the cloak object is parked on its window. Keeping our own reference
# also guarantees the Python wrapper outlives the C++ object's use.
_CLOAK_ATTR = "_winzapp_focus_cloak"

# Long enough for NVDA to have pumped and processed the focus event even on a
# loaded machine (its event pump runs every few tens of milliseconds), short
# enough that a Tab the user presses immediately afterwards is still announced.
DEFAULT_CLOAK_MS = 500


class FocusCloakAccessible(wx.Accessible):
    """MSAA shim that can hide ``STATE_SYSTEM_FOCUSED`` on demand.

    While ``cloaked`` is False every query answers ``wx.ACC_NOT_IMPLEMENTED``,
    which makes wxWidgets fall back to the standard system implementation — the
    control behaves exactly as if this object were not installed.
    """

    def __init__(self, window):
        super().__init__(window)
        self.cloaked = False

    def GetState(self, childId):
        # childId 0 is CHILDID_SELF. A wx.Button has no MSAA children of its
        # own, but answering for them would be wrong regardless: the cloak is
        # about the control that just took focus, nothing else.
        if not self.cloaked or childId != 0:
            return (wx.ACC_NOT_IMPLEMENTED, 0)
        # Focusable, but explicitly not focused. Reporting the control as
        # unavailable or invisible instead would also drop the announcement,
        # but it lies about the control to every other consumer; "not the
        # focus" is the single fact we are actually suppressing.
        return (wx.ACC_OK, wx.ACC_STATE_SYSTEM_FOCUSABLE)


def _get_or_install_cloak(window):
    """Return the window's cloak, installing it the first time."""
    cloak = getattr(window, _CLOAK_ATTR, None)
    if cloak is not None:
        return cloak
    cloak = FocusCloakAccessible(window)
    window.SetAccessible(cloak)
    setattr(window, _CLOAK_ATTR, cloak)
    return cloak


def cloak_focus_announcement(window, duration_ms=DEFAULT_CLOAK_MS):
    """Arm the cloak on ``window`` so the next focus event on it is dropped.

    Must be called *before* ``window.SetFocus()`` — the state has to already be
    hiding FOCUSED by the time the screen reader reads it back.

    Returns True if the cloak was armed. Every failure path is non-fatal and
    returns False: the caller's ``silence()`` fallback still runs, and a focus
    move that gets announced is a far better outcome than a crash on the way to
    recording a voice message.
    """
    try:
        cloak = _get_or_install_cloak(window)
        cloak.cloaked = True
    except Exception:
        logging.debug("[focus_cloak] could not arm the cloak", exc_info=True)
        return False

    def _uncloak():
        try:
            cloak.cloaked = False
        except Exception:
            pass

    try:
        wx.CallLater(max(0, int(duration_ms)), _uncloak)
    except Exception:
        # No timer means no automatic disarm, which would leave the control
        # permanently unannounceable. Undo rather than leave it armed.
        _uncloak()
        return False
    return True


def uncloak_focus_announcement(window):
    """Disarm the cloak on ``window`` immediately, if it has one."""
    try:
        cloak = getattr(window, _CLOAK_ATTR, None)
    except Exception:
        return
    if cloak is not None:
        try:
            cloak.cloaked = False
        except Exception:
            pass
