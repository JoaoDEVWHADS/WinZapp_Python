"""Which conversations the automatic transcription and description may act on.

The automatic options (local transcription, core/transcription/auto_queue.py,
and the online transcription and description, core/ai_media/auto.py) are
install-wide switches; this is the per-conversation layer on top of them,
set in the conversation's data window. Two boxes per conversation:

* ``transcribe``: voice messages and audio, and the sound track of videos;
* ``describe``: pictures, stickers and videos described by an AI provider.

What a box shows before the user touches it is decided by the **scope**
(Settings > Transcriptions & Descriptions, ``conversation_auto_ai_scope``):

* ``all`` (default): every conversation, except the ones the user turned off;
* ``selected``: no conversation, except the ones the user turned on — the
  way to have the options on for a handful of chats without visiting the
  rest to clear them.

``conversation_auto_ai`` maps a normalized JID to the boxes the user set
explicitly: ``{"<jid>": {"transcribe": False}}``. A box equal to the scope's
default is not stored, so the map stays as small as the exceptions.
"""

SETTING = "conversation_auto_ai"
SCOPE_SETTING = "conversation_auto_ai_scope"
SCOPE_ALL = "all"
SCOPE_SELECTED = "selected"
TRANSCRIBE = "transcribe"
DESCRIBE = "describe"


def scope(settings) -> str:
    """The stored scope; anything unknown reads as "all"."""
    value = settings.get(SCOPE_SETTING) if isinstance(settings, dict) else None
    return SCOPE_SELECTED if value == SCOPE_SELECTED else SCOPE_ALL


def default_allowed(settings) -> bool:
    """What a conversation nobody touched allows."""
    return scope(settings) == SCOPE_ALL


def allowed(settings, jid, which) -> bool:
    """Whether the automatic option `which` may act on conversation `jid`."""
    section = settings.get(SETTING) if isinstance(settings, dict) else None
    entry = section.get(jid) if isinstance(section, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get(which), bool):
        return entry[which]
    return default_allowed(settings)


def set_allowed(settings, jid, which, value) -> None:
    """Record the box for `jid`; one equal to the scope's default is dropped."""
    section = settings.get(SETTING)
    if not isinstance(section, dict):
        section = settings[SETTING] = {}
    entry = section.get(jid)
    entry = dict(entry) if isinstance(entry, dict) else {}
    if bool(value) == default_allowed(settings):
        entry.pop(which, None)
    else:
        entry[which] = bool(value)
    if entry:
        section[jid] = entry
    else:
        section.pop(jid, None)


# ── Automatic transcription: one box per kind, inherited until chosen ────────
#
# Asked for: in a conversation's data window, a box for the automatic local
# transcription (Whisper) and one for the automatic online one (AI provider),
# each showing — until the user sets it for that conversation — what the
# install-wide option says right now, and each able to turn the automatic
# transcription ON for the conversation even while that option is off.
# Unlike `allowed()`, a choice is therefore always stored, even when it equals
# what the conversation would inherit: "chosen once" is the whole difference.
#
# The shared "transcribe" key above is the box both used to be, and it only
# ever *restricted*: True meant "may act here while the install-wide option is
# on" (all the "selected" scope stored), False "not here". It keeps exactly
# that meaning for each new box until that box is set: False turns the box off,
# True follows the install-wide option whatever the scope. It never becomes an
# explicit "on": read as one, an old True ran local Whisper with the option off
# and, moved to the other box, sent voice notes to an online provider whose
# option was off too.

TRANSCRIBE_LOCAL = "transcribe_local"
TRANSCRIBE_ONLINE = "transcribe_online"
_TRANSCRIPTION_BOXES = (TRANSCRIBE_LOCAL, TRANSCRIBE_ONLINE)


def _entry(settings, jid):
    section = settings.get(SETTING) if isinstance(settings, dict) else None
    entry = section.get(jid) if isinstance(section, dict) else None
    return entry if isinstance(entry, dict) else {}


def transcription_choice(settings, jid, which):
    """What the user chose for `jid` in box `which` (True/False), or None when
    the box was never set. The old shared box is not a choice (see above)."""
    value = _entry(settings, jid).get(which)
    return value if isinstance(value, bool) else None


def transcription_wanted(settings, jid, which, globally_on) -> bool:
    """Whether the automatic transcription `which` runs on `jid`: the
    conversation's own choice; else the old shared box as the restriction it
    was; else the install-wide option `globally_on` within the scope."""
    choice = transcription_choice(settings, jid, which)
    if choice is not None:
        return choice
    legacy = _entry(settings, jid).get(TRANSCRIBE)
    if legacy is False:
        return False
    if legacy is True:
        return bool(globally_on)
    return bool(globally_on) and default_allowed(settings)


def set_transcription(settings, jid, which, value) -> None:
    """Record `which` for `jid` as an explicit choice. The old shared box stays
    for the other box, which it still restricts until that one is set."""
    if which not in _TRANSCRIPTION_BOXES:
        raise ValueError(which)
    section = settings.get(SETTING)
    if not isinstance(section, dict):
        section = settings[SETTING] = {}
    entry = section.get(jid)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry[which] = bool(value)
    if all(isinstance(entry.get(box), bool) for box in _TRANSCRIPTION_BOXES):
        # Both boxes chosen: the old one speaks for neither any more.
        entry.pop(TRANSCRIBE, None)
    section[jid] = entry


# ── One choice for the data window: none, online or local ────────────────────
#
# Asked for: the two boxes became one group of three options, since both ticked
# made the local and the online transcription compete for the same message.
# The group shows what the boxes mean together (the local one wins, as it does
# when the messages arrive) and a choice sets both boxes at once.

TRANSCRIPTION_NONE = "none"
TRANSCRIPTION_ONLINE = "online"
TRANSCRIPTION_LOCAL = "local"
#: In the order the options are offered.
TRANSCRIPTION_MODES = (TRANSCRIPTION_NONE, TRANSCRIPTION_ONLINE, TRANSCRIPTION_LOCAL)


def transcription_mode(settings, jid, local_on, online_on) -> str:
    """Which automatic transcription runs on `jid`, from the conversation's
    boxes or, until they are set, the install-wide options `local_on` and
    `online_on`."""
    if transcription_wanted(settings, jid, TRANSCRIBE_LOCAL, local_on):
        return TRANSCRIPTION_LOCAL
    if transcription_wanted(settings, jid, TRANSCRIBE_ONLINE, online_on):
        return TRANSCRIPTION_ONLINE
    return TRANSCRIPTION_NONE


def set_transcription_mode(settings, jid, mode) -> None:
    """Record `mode` for `jid` as the choice of both boxes."""
    if mode not in TRANSCRIPTION_MODES:
        raise ValueError(mode)
    set_transcription(settings, jid, TRANSCRIBE_LOCAL, mode == TRANSCRIPTION_LOCAL)
    set_transcription(settings, jid, TRANSCRIBE_ONLINE, mode == TRANSCRIPTION_ONLINE)
