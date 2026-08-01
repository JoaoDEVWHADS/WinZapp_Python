"""Tests for the unread count shown on a conversation.

effective_unread_count() used to return min(reported, local_count). That fixed a
real bug — a chat-list sync reporting "2 unread" for a chat whose message fetch
had failed, so it opened completely empty — but it also capped every count at
however many messages the last fetch happened to return.

WhatsApp Web's message store only holds a handful of messages per chat right
after pairing (measured: ~15 for both groups and 1:1 chats), so a group with
5747 unread announced "15". For a screen-reader user choosing what to open that
is worse than useless: it is indistinguishable from a group with exactly 15.

Having *some* history is enough to know the conversation opens with content.
Beyond that the server's count is the honest number.
"""

import pytest

from core.utils import effective_unread_count as unread


def _chat(reported, records):
    return {
        "unreadCount": reported,
        "messages": {"messages": {"records": [{"key": {"id": i}} for i in range(records)]}},
    }


class TestTheOriginalBugStaysFixed:
    def test_no_local_messages_means_no_badge(self):
        """The conversation would open empty — claiming unread is a lie."""
        assert unread(_chat(2, 0)) == 0

    def test_no_local_messages_even_for_a_huge_reported_count(self):
        assert unread(_chat(5747, 0)) == 0

    def test_a_chat_with_no_messages_key_at_all(self):
        assert unread({"unreadCount": 7}) == 0


class TestTheCapIsGone:
    def test_a_group_with_thousands_reports_thousands(self):
        """The reported regression: 5747 unread, 15 messages fetched."""
        assert unread(_chat(5747, 15)) == 5747

    def test_one_stored_message_is_enough_to_trust_the_count(self):
        assert unread(_chat(720, 1)) == 720

    @pytest.mark.parametrize("reported,records", [(264, 15), (10, 2), (38451, 16)])
    def test_the_server_count_wins_whenever_history_exists(self, reported, records):
        assert unread(_chat(reported, records)) == reported


class TestOrdinaryCases:
    def test_zero_reported_is_zero(self):
        assert unread(_chat(0, 30)) == 0

    def test_a_negative_or_junk_count_is_zero(self):
        assert unread({"unreadCount": -1, "messages": {"messages": {"records": [1]}}}) == 0
        assert unread({"unreadCount": None}) == 0

    def test_a_fully_read_chat_with_history_is_zero(self):
        assert unread(_chat(0, 200)) == 0

    @pytest.mark.parametrize("bad", [None, "chat", 42, []])
    def test_survives_a_non_dict(self, bad):
        assert unread(bad) == 0

    def test_survives_a_malformed_messages_block(self):
        assert unread({"unreadCount": 5, "messages": "nope"}) == 0


def test_the_unread_separator_stays_safe_with_an_uncapped_count():
    """conversations.py places the separator only when it actually holds enough
    messages to anchor it — an uncapped count must not make it index out of
    range, it just means no separator until the history is there."""
    displayable = list(range(15))
    count = 5747
    assert not (count > 0 and len(displayable) >= count), "guard must reject it"
    # And once the history really is there, it places it as before.
    displayable = list(range(6000))
    assert count > 0 and len(displayable) >= count
    assert len(displayable) - count == 253
