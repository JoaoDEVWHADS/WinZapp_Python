"""WhatsApp's own Chat Lock, as set on the phone.

WhatsApp has a feature of its own that hides a conversation behind the phone's
secret code, and the chat record WPPConnect returns says so in its ``isLocked``
field. It is not WinZapp's locked-chats vault (core/chat_lock_vault.py): the
vault is a local PIN, this is a decision made on the phone, and only the phone
can undo it.

No wx here, so all of it is tested without opening a window. The state and the
hooks into the main window live in main_window/phone_chat_lock.py.
"""

from collections.abc import Iterable

from core.utils import parse_bool_flag


def stated_flag(chat):
    """The chat record's own ``isLocked``: True, False, or None when the record
    states nothing (not a dict, a list answer without the field, junk)."""
    if not isinstance(chat, dict):
        return None
    return parse_bool_flag(chat.get("isLocked"))


def apply_flag(members: set, jids: Iterable[str], flag) -> bool:
    """Bring *members* in line with a chat record's stated *flag*.

    True adds every JID (the chat under both its phone and LID names), False
    removes them, None leaves the set alone. Returns True when the set changed,
    so the caller persists only then.
    """
    changed = False
    for jid in jids:
        if not jid:
            continue
        if flag is True and jid not in members:
            members.add(jid)
            changed = True
        elif flag is False and jid in members:
            members.discard(jid)
            changed = True
    return changed
