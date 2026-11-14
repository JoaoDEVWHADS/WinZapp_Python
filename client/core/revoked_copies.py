"""A "delete for everyone" reaches every stored copy of the message.

A chat's records can hold the same message twice: the initial sync and a later
messages.upsert both store it, and the conversation de-duplicates on the way to
the screen, keeping the **last** copy (ConversationsPanel._sorted_deduped_records).
MainWindow._apply_remote_revoke() turned that copy into the tombstone. The chat
list's preview, though, reads the records itself and takes the newest by
timestamp with max(), which answers the **first** of two equal ones: the
untouched copy. Reported: deleting the last message of a conversation left its
text in the chat list until another conversation was opened.

Pure function, no wx, so it is tested directly.
"""


def mark_copies_revoked(records, msg_id, message, drop_keys=()) -> int:
    """Turn every record of *msg_id* in *records* that is not already a
    tombstone into one carrying *message* (the protocolMessage of the revoke),
    and drop *drop_keys* from it (the withdrawn content in another form).
    Answers how many were changed."""
    if not msg_id or not isinstance(records, list):
        return 0
    changed = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        if (record.get("key") or {}).get("id") != msg_id:
            continue
        if record.get("messageType") == "protocolMessage":
            continue
        record["message"] = message
        record["messageType"] = "protocolMessage"
        record.pop("_edited", None)
        for key in drop_keys:
            record.pop(key, None)
        changed += 1
    return changed
