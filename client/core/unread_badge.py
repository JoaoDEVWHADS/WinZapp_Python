"""Which conversations count toward the unread tally of the window title and
the tray icon, and whether the tray tooltip shows that tally at all.

Two options of Settings > Notifications decide which conversations count:
archived and muted conversations can each be left out of that tally. Both
default to left out. A third option hides the unread count from the tray
tooltip entirely, so the tray shows only the app name.
"""

DISCOUNT_ARCHIVED_KEY = "discount_archived_from_unread_badge"
DISCOUNT_MUTED_KEY = "discount_muted_from_unread_badge"
HIDE_TRAY_UNREAD_KEY = "hide_tray_unread_count"


def tray_unread_hidden(settings) -> bool:
    """True when the tray tooltip must show only the app name, with no unread count."""
    general = (settings or {}).get("general", {}) or {}
    return bool(general.get(HIDE_TRAY_UNREAD_KEY, False))


def badge_discount_flags(settings) -> tuple[bool, bool]:
    """(discount_archived, discount_muted) from the settings, both True when unset."""
    general = (settings or {}).get("general", {}) or {}
    return (
        bool(general.get(DISCOUNT_ARCHIVED_KEY, True)),
        bool(general.get(DISCOUNT_MUTED_KEY, True)),
    )


def counts_toward_badge(settings, *, archived: bool, muted: bool) -> bool:
    """False when the conversation is archived/muted and that kind is discounted."""
    discount_archived, discount_muted = badge_discount_flags(settings)
    if archived and discount_archived:
        return False
    if muted and discount_muted:
        return False
    return True
