"""Who received and who read a message, as WhatsApp itself reports it.

WPP.chat.getMessageACK() answers, for one of OUR OWN sent messages, a list of
participants each with ``deliveredAt`` / ``readAt`` / ``playedAt`` (epoch
seconds or milliseconds; absent when that stage was not reached). That is the
phone-synced state: it includes receipts that arrived while WinZapp was closed,
which the MessageUpdate events WinZapp records locally never see.

No wx here, so all of it is tested without opening a window. The server call
lives in main_window/message_ack.py and the window in
ui/conversation_panel/message_data.py.
"""

#: Most advanced first. A participant is counted only at the furthest stage they
#: reached (played implies read implies delivered), so nobody appears twice.
STAGES = ("played", "read", "delivered")

_FIELD_FOR_STAGE = {
    "played": "playedAt",
    "read": "readAt",
    "delivered": "deliveredAt",
}


def participant_id(participant) -> str:
    """The participant's JID, from either shape WPPConnect answers with."""
    if not isinstance(participant, dict):
        return ""
    raw = participant.get("id")
    if isinstance(raw, str) and raw:
        return raw
    wid = participant.get("wid")
    if isinstance(wid, dict):
        serialized = wid.get("_serialized")
        if isinstance(serialized, str):
            return serialized
    return ""


def participants_of(ack_info) -> list:
    """The usable participant records of an ack answer ([] for anything else)."""
    if not isinstance(ack_info, dict):
        return []
    found = ack_info.get("participants")
    if not isinstance(found, list):
        return []
    return [p for p in found if isinstance(p, dict)]


def total_recipients(ack_info) -> int:
    """Everyone the message went to: those WhatsApp lists (they reached at least
    "delivered") plus the ones it says have not received it yet. Without the
    second part "Read (2/3)" would say two of three when six more are waiting."""
    pending = 0
    if isinstance(ack_info, dict):
        raw = ack_info.get("deliveryRemaining")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw > 0:
            pending = raw
    return len(participants_of(ack_info)) + pending


def furthest_stage(participant: dict):
    """"played", "read", "delivered", or None when the participant has no stage."""
    for stage in STAGES:
        if participant.get(_FIELD_FOR_STAGE[stage]):
            return stage
    return None


def direct_timeline(ack_info) -> list:
    """(stage, timestamp) pairs for a one-to-one chat, in the order they happen.

    A direct chat has a single recipient, so only the first participant matters.
    Stages the recipient has not reached are left out.
    """
    participants = participants_of(ack_info)
    if not participants:
        return []
    first = participants[0]
    pairs = []
    for stage in ("delivered", "read", "played"):
        ts = first.get(_FIELD_FOR_STAGE[stage])
        if ts:
            pairs.append((stage, ts))
    return pairs


def group_by_stage(ack_info, name_for) -> dict:
    """{stage: [names]} for a group message, each person at their furthest stage.

    *name_for* turns a participant's JID into the text to show; participants
    with no stage at all (WhatsApp lists them, nothing reached them yet) are not
    in any list.
    """
    groups = {stage: [] for stage in STAGES}
    for participant in participants_of(ack_info):
        stage = furthest_stage(participant)
        if stage is None:
            continue
        groups[stage].append(name_for(participant_id(participant)))
    return groups


def group_lines(ack_info, name_for, label_for, more_for, max_names: int = 40) -> list:
    """The lines of a group message's breakdown: one per stage, furthest first.

    Each reads ``<label> (<n>/<total>): name, name, ...``. *total* is everyone the
    message went to (see total_recipients), so "Read (2/9)" means two of nine. A long list
    is cut at *max_names* and the rest summarised by ``more_for(n)``, instead of
    one unreadable wall of names in a window a screen reader walks through.
    """
    total = total_recipients(ack_info)
    groups = group_by_stage(ack_info, name_for)
    lines = []
    for stage in STAGES:
        names = groups[stage]
        if not names:
            continue
        shown = names[:max_names]
        text = ", ".join(shown)
        extra = len(names) - len(shown)
        if extra > 0:
            text += " " + more_for(extra)
        lines.append(f"{label_for(stage)} ({len(names)}/{total}): {text}")
    return lines


def display_name(raw_jid: str, saved_name: str, phone_for_lid, format_number) -> str:
    """What to show for one participant.

    The saved name when there is one; otherwise the phone number, going through
    *phone_for_lid* for an @lid JID (a bare LID is not a number anyone knows);
    otherwise the number part of whatever JID it is.
    """
    if saved_name:
        return saved_name
    jid = raw_jid or ""
    if jid.endswith("@lid"):
        phone = phone_for_lid(jid)
        if phone:
            jid = phone
    shown = format_number(jid)
    return shown or jid.split("@", 1)[0]
