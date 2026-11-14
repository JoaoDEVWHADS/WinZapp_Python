"""How a management action's outcome is said, for whoever has to say it.

The settings tab says it when the user is watching; the main window says it
when a download ran in the background and the tab may not exist any more
(see core/transcription/background.py). Both need the same sentence, so the
wording is here rather than in either. No wx.
"""

from core.transcription import (
    management,
    management_whisper_cpp,
    model_names,
)


def build_name(i18n, build_id) -> str:
    """A whisper.cpp build as it is said ("the processor version"), or ""."""
    key = management_whisper_cpp.WHISPER_CPP_BUILD_I18N_KEYS.get(build_id)
    return i18n.t(key) if key else ""


def announcement_text(i18n, announcement) -> str:
    """The sentence of a finished action, with its values said as names.

    A management Announcement carries ids — a model id, a whisper.cpp build's
    i18n key — because it is built where no translation is at hand; this is
    where they become what the picker calls them ("small, 5 bits"), so the
    sentence and the list the user just read agree.
    """
    values = dict(announcement.values)
    if values.get("model"):
        values["model"] = model_names.display_name(i18n, values["model"]) or values["model"]
    # A move's lists of ids, said one name at a time.
    for key in ("models", "moved", "remaining"):
        if values.get(key):
            values[key] = model_names.display_list(
                i18n, values[key].split(management.LIST_SEPARATOR)
            )
    if "build" in values:
        values["build"] = i18n.t(values["build"]) if values["build"] else ""
    return i18n.t(announcement.i18n_key).format(**values)
