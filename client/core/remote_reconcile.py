"""What a get-messages answer may and may not say about local messages.

MainWindow._reconcile_active_conversation_with_remote() mirrors phone-side
deletions by diffing the open conversation against WhatsApp Web's own
get-messages. That answer is only ever the messages WhatsApp Web has LOADED
for the chat right now — never the phone's history — and the loaded window
moves on its own: WhatsApp Web unloads older messages of a chat (measured on a
live page: 1225 messages held across 545 chats), and a restored browser
profile comes back holding only what it knew when its snapshot was taken.

So "the server did not return this message" means one of two things, and only
one of them is a deletion:

- the message is INSIDE the period the answer covers and still absent: it
  really is gone (deleted on the phone);
- the message is OLDER than anything the answer returned: the answer says
  nothing about it — it may simply not be loaded.

Treating the second case like the first, from a single read, is what deleted
199 messages at once from an open group (2026-09-15): the answer held one or two
messages for the chat, and every stored message older than them was mirrored as
a phone-side deletion on the spot.

What no answer can do is tell a deletion apart from a message WhatsApp Web's
own database has lost: both say "not here". Mirroring what was done on the phone
comes first — nothing v1.1.1.0 mirrored may stop being mirrored — so older
messages are asked about again with an anchored query, anything it cannot
account for counts as missing, and every large or inferred batch has to be seen
on consecutive polls before it is mirrored.
"""


def _seconds(value) -> int:
    try:
        ts = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return ts // 1000 if ts > 1_000_000_000_000 else ts


def _message_seconds(message) -> int:
    if not isinstance(message, dict):
        return 0
    return _seconds(message.get("messageTimestamp") or message.get("timestamp") or message.get("t"))


def _message_id(message) -> str:
    if not isinstance(message, dict):
        return ""
    return str((message.get("key") or {}).get("id") or "")


def remote_window_oldest(messages) -> int:
    """The oldest timestamp (seconds) among the messages a get-messages answer
    returned, or 0 when none of them carries one."""
    stamps = [s for s in (_message_seconds(m) for m in (messages or [])) if s]
    return min(stamps) if stamps else 0


#: More apparent phone-side deletions than this in one poll are not mirrored at
#: once: they must be confirmed on consecutive polls (see observe_deletions()).
#: A deletion made on the phone is almost always one message or a handful; a
#: big batch is likelier to be the loaded window misread (a stray old message in
#: the answer pulls remote_oldest_ts back, and everything between it and the
#: recent ones looks deleted), which a single read cannot rule out. It is not
#: refused outright, because a real bulk deletion — a chat cleared on the phone
#: while WinZapp was closed, with new messages since — has exactly this shape
#: and must still reach WinZapp.
MAX_MIRRORED_DELETIONS = 10


def deletions_within_remote_window(local_records, remote_ids, remote_oldest_ts) -> set:
    """Ids of local messages the answer proves were deleted.

    Only a message strictly AFTER *remote_oldest_ts* can be judged. The answer
    is a slice of the chat cut by count, and that cut can fall in the middle of
    messages sharing one second (an album, a burst of forwards): the siblings
    left out carry exactly the oldest timestamp and are merely not loaded. So a
    message in that same second is not judged either — missing a real deletion
    of it is cosmetic. Anything older is outside what the answer says anything
    about. An answer with no messages, or with no timestamps, proves nothing
    here — an empty answer is the separate "cleared on the phone" question,
    which the caller handles with its own confirmation strikes.
    """
    remote_ids = set(remote_ids or ())
    if not remote_ids or not remote_oldest_ts:
        return set()
    missing = set()
    for record in local_records or []:
        mid = _message_id(record)
        ts = _message_seconds(record)
        if mid and ts and ts > remote_oldest_ts and mid not in remote_ids:
            missing.add(mid)
    return missing


def older_than_window(local_records, window_ids, window_oldest_ts) -> list:
    """Local records the newest-window answer says nothing about: at or before
    its oldest timestamp and not among its ids. These are what a second,
    anchored "messages before" query has to settle."""
    window_ids = set(window_ids or ())
    if not window_oldest_ts:
        return []
    out = []
    for record in local_records or []:
        mid = _message_id(record)
        ts = _message_seconds(record)
        if mid and ts and ts <= window_oldest_ts and mid not in window_ids:
            out.append(record)
    return out


def serialized_id(raw) -> str:
    """The full WhatsApp id of a RAW get-messages item (`id._serialized`).

    The normalised key.id is only the last part of it, and the anchored
    "messages before" query needs the whole thing to find the message."""
    value = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(value, dict):
        value = value.get("_serialized")
    return value if isinstance(value, str) else ""


def oldest_anchor(pairs) -> str:
    """Serialized id of the oldest message of a page given as (normalised, raw)
    pairs — the anchor to ask what comes before it. '' when no message carries
    both a timestamp and an id."""
    best_ts, best_id = 0, ""
    for normalized, raw in pairs or ():
        ts = _message_seconds(normalized)
        sid = serialized_id(raw)
        if ts and sid and (not best_ts or ts < best_ts):
            best_ts, best_id = ts, sid
    return best_id


def split_deletions(direct, inferred):
    """(mirror now, confirm first) for one poll's apparent deletions.

    *direct* are messages absent from inside the newest window the server
    returned: up to MAX_MIRRORED_DELETIONS of them mirror at once, a bigger
    batch waits for confirmation. *inferred* come from the anchored walk into
    older history and always wait, because that answer is built by a fallback
    chain on the server side — an anchor it cannot find is silently swapped for
    another one — so a single read of it is never enough to delete anything.
    """
    direct = set(direct or ())
    inferred = set(inferred or ())
    if len(direct) > MAX_MIRRORED_DELETIONS:
        return set(), direct | inferred
    return direct, inferred


def observe_deletions(state: dict, key, missing, threshold: int):
    """Record one poll's apparent deletions; return the ids now confirmed.

    Confirmation is a running intersection: only ids missing on EVERY one of
    *threshold* polls of that chat are returned, so a set that wobbles between
    reads (a window that loads differently each time) never confirms the ids
    that came and went. A poll with nothing in common with the previous run
    starts a new run. Returns an empty set until the run reaches *threshold*;
    on confirmation the state for *key* is cleared.

    Deliberately no expiry by time: the polls only happen while the chat is
    open, and a run that restarted after a gap would never confirm for someone
    who only ever opens a chat briefly — a deletion made on the phone that
    v1.1.1.0 mirrored on the first read and this would never mirror at all.
    """
    current = set(missing or ())
    previous = state.get(key)
    if previous and current:
        common = set(previous[0]) & current
        run = (common, previous[1] + 1) if common else (current, 1)
    else:
        run = (current, 1)
    if not run[0]:
        state.pop(key, None)
        return set()
    if run[1] >= threshold:
        state.pop(key, None)
        return set(run[0])
    state[key] = run
    return set()
