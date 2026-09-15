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
- the message is OLDER than anything the answer returned: nothing can be
  concluded about it at all — it simply is not loaded.

Treating the second case like the first is what deleted 199 messages at once
from an open group (2026-09-15): WhatsApp Web held one or two messages for the
chat, a new one arrived, and every stored message older than it was mirrored
as a phone-side deletion — from the only copy that still had them.
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


#: More apparent phone-side deletions than this in one answer are not mirrored.
#: A deletion made on the phone is almost always one message or a handful; a
#: big batch is far likelier to be the loaded window misread again (a stray old
#: message in the answer pulls remote_oldest_ts back, and everything between it
#: and the recent ones looks deleted). A real bulk deletion left unmirrored is
#: cosmetic; a wrong mirror is irreversible.
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
