"""macOS Focus for WinZapp's quiet-hours gate (INFocusStatusCenter).

core/quiet_hours.is_quiet_hours_active() tells WinZapp when to keep quiet —
on Windows it reads Do Not Disturb / Focus Assist. On the Mac the answer is
the Focus Status API (macOS 12+): whether any Focus is on. It needs the app
signed with the Communication Notifications entitlement (a Developer ID
build with its provisioning profile, see macos/build_app.py) and the user's
one-time permission; without either it answers "not focused", so an
unsigned build behaves exactly as before.

What changes while a Focus is on is decided in notify_mac: WinZapp's own
sound and spoken announcement stay silent, but the notification is still
posted, so macOS files it in Notification Center or lets it through when
the Focus allows WinZapp or that person.
"""

import logging

_AUTHORIZED = 3  # INFocusStatusAuthorizationStatusAuthorized
_asked = False


def _center():
    from Intents import INFocusStatusCenter
    return INFocusStatusCenter.defaultCenter()


def request_permission():
    """Ask once (macOS shows its "share Focus status" prompt the first time)."""
    global _asked
    if _asked:
        return
    _asked = True
    try:
        center = _center()
        if center.authorizationStatus() == 0:  # not determined
            center.requestAuthorizationWithCompletionHandler_(
                lambda status: logging.info("[focus_mac] Focus status permission: %s", status))
    except Exception:
        logging.debug("[focus_mac] Focus status unavailable", exc_info=True)


def focus_active():
    try:
        center = _center()
        if center.authorizationStatus() != _AUTHORIZED:
            return False
        status = center.focusStatus()
        focused = status.isFocused() if status is not None else None
        return bool(focused)
    except Exception:
        return False


def _compute_quiet_hours_active():
    active = focus_active()
    if active:
        logging.info("[quiet_hours] Suppressed: a macOS Focus is on")
    return active


def install():
    from core import quiet_hours
    quiet_hours._compute_quiet_hours_active = _compute_quiet_hours_active
