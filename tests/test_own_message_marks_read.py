"""Tests for main.own_message_marks_chat_read() — replying from the phone
(or any other linked device) clears the unread badge in WinZapp.

Reported live: a chat sitting at "Bruna — 2 mensagens não lidas" whose own
last line already read "Eu: áudio 0:06 11:18 Entregue". The reply had been
sent from the phone seconds earlier and its echo had already arrived (that
is where "Eu: áudio" came from) — but on_new_message() only ever touched
the badge inside `if not from_me`, and returned outright on `if from_me` a
few lines later, so nothing in the whole app could lower the count. Reading
the chat on the phone is supposed to be handled by the chats-update path
(WPP.on('chat.unread_count_changed') → on_chat_unread_update); replying is
a second, independent and much stronger signal that never had a handler at
all.

The recency rule is what keeps this honest: a re-delivered *old* message of
ours must never clear a badge for messages that arrived after it.
"""

import pytest

from main import own_message_marks_chat_read


def _mine(msg_id, ts):
    return {
        "key": {"id": msg_id, "fromMe": True},
        "message": {"conversation": "minha resposta"},
        "messageType": "conversation",
        "messageTimestamp": ts,
    }


def _theirs(msg_id, ts):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "message": {"conversation": "oi"},
        "messageType": "conversation",
        "messageTimestamp": ts,
    }


def _system_event(msg_id, ts):
    """A group promote/join/leave — never counted toward the badge."""
    return {
        "key": {"id": msg_id, "fromMe": False},
        "message": {},
        "messageType": "groupNotification",
        "messageTimestamp": ts,
    }


class TestTheReportedCase:
    def test_a_reply_newer_than_the_unread_messages_clears_them(self):
        """Two unread arrive, then we answer from the phone."""
        mine = _mine("C", 1100)
        records = [_theirs("A", 1000), _theirs("B", 1050), mine]

        assert own_message_marks_chat_read(records, mine) is True

    def test_a_reply_in_the_same_second_still_counts(self):
        """WhatsApp timestamps are whole seconds — an answer typed fast
        carries the same `t` as the message it answers. Requiring strictly
        newer would leave exactly the burst case this exists for unfixed."""
        mine = _mine("B", 1000)
        records = [_theirs("A", 1000), mine]

        assert own_message_marks_chat_read(records, mine) is True

    def test_the_echo_is_ignored_when_already_appended_to_records(self):
        """on_new_message() appends the message before the unread block runs,
        so the record list handed over always contains it."""
        mine = _mine("C", 1100)
        records = [_theirs("A", 1000), mine]

        assert own_message_marks_chat_read(records, mine) is True


class TestRecency:
    def test_an_older_message_of_ours_never_clears_newer_unread(self):
        """A re-delivered old send must not wipe a badge for messages that
        arrived after it."""
        mine = _mine("A", 1000)
        records = [mine, _theirs("B", 1200)]

        assert own_message_marks_chat_read(records, mine) is False

    def test_only_the_newest_received_message_decides(self):
        """An old received message sitting further back is irrelevant once a
        newer one is present."""
        mine = _mine("X", 1100)
        records = [_theirs("A", 900), _theirs("B", 1500), mine]

        assert own_message_marks_chat_read(records, mine) is False

    def test_a_message_with_no_timestamp_is_refused(self):
        """Refuse rather than guess — the 60s list-chats poll and the next
        chats-update both still get their chance to fix the count."""
        mine = {"key": {"id": "C", "fromMe": True}, "messageType": "conversation"}
        records = [_theirs("A", 1000), mine]

        assert own_message_marks_chat_read(records, mine) is False


class TestNothingRealToProtect:
    def test_no_received_messages_at_all(self):
        mine = _mine("A", 1000)

        assert own_message_marks_chat_read([mine], mine) is True

    def test_empty_records(self):
        assert own_message_marks_chat_read([], _mine("A", 1000)) is True

    def test_system_events_are_not_treated_as_unread_messages(self):
        """is_countable_message() excludes group promotes/joins/leaves from
        the badge, so a newer one of those must not block the clear either —
        same rule the increment side applies."""
        mine = _mine("B", 1000)
        records = [mine, _system_event("C", 5000)]

        assert own_message_marks_chat_read(records, mine) is True


class TestGuards:
    def test_a_message_that_is_not_ours_never_clears_anything(self):
        theirs = _theirs("A", 9999)

        assert own_message_marks_chat_read([theirs], theirs) is False

    def test_a_message_without_a_key_is_not_ours(self):
        assert own_message_marks_chat_read([], {"messageTimestamp": 1000}) is False

    @pytest.mark.parametrize("junk", [None, "", 0, [], "nope"])
    def test_survives_a_non_dict_message(self, junk):
        assert own_message_marks_chat_read([], junk) is False

    def test_survives_junk_inside_the_record_list(self):
        mine = _mine("B", 1000)
        records = [None, "nope", 7, _theirs("A", 500), mine]

        assert own_message_marks_chat_read(records, mine) is True

    def test_survives_a_none_record_list(self):
        assert own_message_marks_chat_read(None, _mine("A", 1000)) is True
