"""A reaction to one of our statuses must survive opening the conversation.

Reported three times by different users, in nearly the same words: someone
replied to their status with an emoji, the message showed up, and it was gone
the moment they opened the chat — the reply existed only on the phone.

The cause is that a status reaction is a reaction like any other, and
on_new_message() deliberately never stores reactions as records: a reaction
decorates the message it points at, so it needs no row of its own. That is
right for every reaction except this one. The message a status reaction points
at is the status itself, which lives in _status_updates and the Status tab and
never in a conversation — so there was nothing to decorate, and nothing was
stored either. What the user saw was the notification and the chat-list
preview, both of which are side channels that do not survive a rebuild.

reaction_targets_status() is the discriminator: a reaction carries the key of
its target, and for a status that key's remoteJid is status@broadcast.
"""

import types

from core.utils import reaction_targets_status
from ui.conversations import ConversationsPanel


def _reaction(target_jid, emoji="❤️"):
    return {
        "key": {"id": "REACT1", "remoteJid": "5511@s.whatsapp.net", "fromMe": False},
        "messageType": "reactionMessage",
        "messageTimestamp": 1000,
        "message": {
            "reactionMessage": {
                "text": emoji,
                "key": {"id": "TARGET1", "remoteJid": target_jid, "fromMe": True},
            }
        },
    }


class TestTheDiscriminator:
    def test_a_reaction_to_a_status_is_recognised(self):
        assert reaction_targets_status(_reaction("status@broadcast"))

    def test_a_reaction_to_a_normal_message_is_not(self):
        assert not reaction_targets_status(_reaction("5511@s.whatsapp.net"))

    def test_a_reaction_to_a_group_message_is_not(self):
        assert not reaction_targets_status(_reaction("120363@g.us"))

    def test_a_plain_message_is_not(self):
        assert not reaction_targets_status({
            "messageType": "conversation",
            "message": {"conversation": "oi"},
        })

    def test_a_reaction_with_no_target_key_does_not_crash(self):
        assert not reaction_targets_status({
            "messageType": "reactionMessage",
            "message": {"reactionMessage": {"text": "❤️"}},
        })

    def test_a_malformed_reaction_does_not_crash(self):
        assert not reaction_targets_status({"messageType": "reactionMessage"})
        assert not reaction_targets_status(
            {"messageType": "reactionMessage", "message": None})

    def test_a_removed_reaction_to_a_status_still_counts_as_one(self):
        """An empty emoji means the reaction was taken back. It is still aimed
        at a status, and the caller — not this predicate — decides what a
        removal means."""
        assert reaction_targets_status(_reaction("status@broadcast", emoji=""))


class TestTheConversationShowsItAsItsOwnRow:
    """ConversationsPanel is a wx.Panel and cannot be instantiated without a
    running wx.App, so the two methods that decide whether a record is visible
    and what it reads as are bound onto a plain stub — same approach as
    tests/test_unread_reread_race.py."""

    class _I18n:
        def t(self, key):
            return {"status_reaction_received": "Reagiu ao seu status: {emoji}"}[key]

    class _Stub:
        _is_displayable_message = ConversationsPanel._is_displayable_message
        _get_message_content = ConversationsPanel._get_message_content

        def __init__(self, i18n):
            self.main_window = types.SimpleNamespace(i18n=i18n, app_name="WinZapp")

    def _stub(self):
        return self._Stub(self._I18n())

    def test_a_status_reaction_is_displayable(self):
        assert self._stub()._is_displayable_message(_reaction("status@broadcast"))

    def test_a_normal_reaction_is_still_not_displayable(self):
        """The whole point of keeping reactionMessage out of the whitelist:
        an ordinary reaction decorates the row it points at, and giving it a
        row of its own would duplicate it."""
        assert not self._stub()._is_displayable_message(
            _reaction("5511@s.whatsapp.net"))

    def test_it_reads_as_a_reaction_to_our_status(self):
        text = self._stub()._get_message_content(_reaction("status@broadcast"))

        assert text == "Reagiu ao seu status: ❤️"

    def test_the_emoji_that_was_sent_is_the_one_shown(self):
        text = self._stub()._get_message_content(
            _reaction("status@broadcast", emoji="😂"))

        assert "😂" in text
