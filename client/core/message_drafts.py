"""What was typed in a conversation and not sent: one draft per conversation.

The message field is one control shared by every conversation. Opening another
one used to leave the text typed in the first in the field, where the next
Enter sent it to the wrong person. Like WhatsApp Web, each conversation now
keeps its own: left behind when the conversation is left, put back when it is
opened again.

In memory only, for this run: a draft is message content, and nothing here
writes it to disk unencrypted.

Settings > Interface > Conversations chooses among three (`mode()`):

* KEEP_IN_FIELD — the field keeps its text across conversations, as it did
  before drafts existed;
* PER_CONVERSATION — the default: one draft per conversation;
* DISCARD — what was typed is thrown away when the conversation is left.

Pure, no wx, so it is tested directly.
"""

from dataclasses import dataclass, field

SECTION = "user_interface"
SETTING = "message_draft_mode"

KEEP_IN_FIELD = "keep_in_field"
PER_CONVERSATION = "per_conversation"
DISCARD = "discard"
#: In the order the Settings choice lists them.
MODES = (KEEP_IN_FIELD, PER_CONVERSATION, DISCARD)
DEFAULT = PER_CONVERSATION


def mode(settings) -> str:
    """The configured mode; DEFAULT for a missing or unknown one."""
    section = settings.get(SECTION) if isinstance(settings, dict) else None
    value = section.get(SETTING) if isinstance(section, dict) else None
    return value if value in MODES else DEFAULT


@dataclass
class Draft:
    text: str
    #: The mentions typed into it (ConversationsPanel._pending_mentions) and the
    #: names they were written with, so "@Ana" still mentions Ana when sent.
    mentions: list = field(default_factory=list)
    mention_names: dict = field(default_factory=dict)


class MessageDrafts:
    def __init__(self):
        self._drafts = {}

    def __len__(self):
        return len(self._drafts)

    def stash(self, jid, text, mentions=(), mention_names=None) -> None:
        """Keep *text* as *jid*'s draft; a blank one forgets it (it was sent or
        erased)."""
        if not jid:
            return
        if not isinstance(text, str) or not text.strip():
            self._drafts.pop(jid, None)
            return
        self._drafts[jid] = Draft(text, list(mentions or ()), dict(mention_names or {}))

    def take(self, jid, same_chat=None):
        """*jid*'s draft, handed back and forgotten (it is in the field again);
        None when there is none.

        *same_chat(stored, jid)* finds a draft kept under another spelling of
        the chat: an @lid chat re-keyed to its phone JID (whatever forms the
        caller's equivalence bridges)."""
        if not jid:
            return None
        if jid in self._drafts:
            return self._drafts.pop(jid)
        if same_chat is not None:
            for stored in list(self._drafts):
                try:
                    match = same_chat(stored, jid)
                except Exception:
                    match = False
                if match:
                    return self._drafts.pop(stored)
        return None

    def clear(self) -> None:
        self._drafts.clear()
