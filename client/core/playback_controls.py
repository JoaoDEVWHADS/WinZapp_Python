"""Which playback controls appear after the message list while media plays.

Playing a voice note or video shows a speed button and a duration bar after
the message list, and Tab stops on each. Settings > Audio > Audio playback has
a box for each to leave it out (off by default: both show, as they always
did). Hidden, the speed and seeking shortcuts keep working: they act on the
stream, not on the controls.
"""

SECTION = "audio_playback"
HIDE_PROGRESS_BAR = "hide_progress_bar"
HIDE_SPEED_BUTTON = "hide_speed_button"


def shown(settings) -> tuple[bool, bool]:
    """(speed button shown, duration bar shown). Only an explicit True hides."""
    section = settings.get(SECTION) if isinstance(settings, dict) else None
    section = section if isinstance(section, dict) else {}
    return (section.get(HIDE_SPEED_BUTTON) is not True,
            section.get(HIDE_PROGRESS_BAR) is not True)
