"""Tests for MainWindow.clear_chat_messages_local() preserving starred
messages instead of wiping the whole conversation.

Reported live: "clear conversation" deleted every message unconditionally,
including ones the user had explicitly starred/favorited to keep — starring
a message is supposed to make it durable, matching WhatsApp's own behavior.

MainWindow is a wx.Frame and can't be instantiated without a running wx.App,
so the methods under test are bound onto a plain stub — same approach as
the rest of this test suite.
"""

import time

from main import MainWindow


class _FakeDB:
    def __init__(self):
        self.delete_calls = []
        self.upsert_calls = []

    def delete_chat_messages_except(self, remote_jid, keep_message_ids):
        self.delete_calls.append((remote_jid, list(keep_message_ids or [])))

    def upsert_chat(self, jid, chat):
        self.upsert_calls.append(jid)


class _Stub:
    clear_chat_messages_local = MainWindow.clear_chat_messages_local
    _is_cleared_message = MainWindow._is_cleared_message
    _recompute_chat_last_message = MainWindow._recompute_chat_last_message
    _counts_as_last_message = MainWindow._counts_as_last_message

    def __init__(self, chat):
        self.chats = {"jid1": chat}
        self.settings = {}
        self.db = _FakeDB()
        self._schedule_save_calls = []

    def save_settings(self):
        pass

    def _schedule_save(self, dirty_jid=None):
        self._schedule_save_calls.append(dirty_jid)


def _msg(msg_id, ts, starred=False):
    return {
        "key": {"remoteJid": "jid1", "fromMe": False, "id": msg_id},
        "message": {"conversation": f"text {msg_id}"},
        "messageType": "conversation",
        "messageTimestamp": ts,
        "starred": starred,
    }


def _chat_with(records):
    return {
        "remoteJid": "jid1",
        "messages": {"messages": {"records": records}},
        "lastMessage": records[-1] if records else None,
        "t": records[-1]["messageTimestamp"] if records else 0,
        "unreadCount": 5,
    }


class TestClearChatKeepsStarredMessages:
    def test_non_starred_messages_are_removed(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        records = chat["messages"]["messages"]["records"]
        assert records == []

    def test_starred_messages_survive(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200, starred=True), _msg("c", 300)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        records = chat["messages"]["messages"]["records"]
        assert [m["key"]["id"] for m in records] == ["b"]

    def test_db_delete_keeps_only_starred_message_ids(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200, starred=True)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert stub.db.delete_calls == [("jid1", ["b"])]

    def test_db_delete_with_no_starred_messages_keeps_nothing(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert stub.db.delete_calls == [("jid1", [])]

    def test_last_message_recomputed_from_the_surviving_starred_message(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200, starred=True)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert chat["lastMessage"]["key"]["id"] == "b"
        assert chat["t"] == 200

    def test_last_message_is_none_when_nothing_survives(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 200)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert chat["lastMessage"] is None
        # "t" keeps its pre-clear value (not reset to 0) so the chat stays at
        # its current position in the list instead of sorting to the bottom.
        assert chat["t"] == 200

    def test_unread_count_is_always_reset(self):
        chat = _chat_with([_msg("a", 100, starred=True)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert chat["unreadCount"] == 0

    def test_record_cutoff_still_recorded_when_starred_messages_survive(self):
        chat = _chat_with([_msg("a", 100, starred=True)])
        stub = _Stub(chat)

        before = int(time.time())
        stub.clear_chat_messages_local("jid1", record_cutoff=True)

        assert stub.settings["cleared_chats"]["jid1"] >= before


class TestStarredMessagesSurviveTheClearCutoff:
    """clear_chat_messages_local() keeping the starred records in memory and
    in the database was only half the job: every path that rebuilds a
    conversation afterwards — the history sync, the on-disk cache merge, a
    WebSocket re-delivery — runs its candidates through
    _is_cleared_message() and drops anything older than the clear cutoff.
    Starred survivors are older than the cutoff by definition, so they were
    filtered straight back out and vanished on the next sync or restart —
    reported live as "limpar uma conversa tambem apaga as mensagens
    favoritas".
    """

    def _stub_with_cutoff(self, cutoff=500):
        stub = _Stub(_chat_with([_msg("a", 100)]))
        stub.settings = {"cleared_chats": {"jid1": cutoff}}
        return stub

    def test_an_ordinary_pre_clear_message_is_still_dropped(self):
        stub = self._stub_with_cutoff()

        assert stub._is_cleared_message("jid1", _msg("a", 100)) is True

    def test_a_starred_pre_clear_message_is_kept(self):
        stub = self._stub_with_cutoff()

        assert stub._is_cleared_message("jid1", _msg("a", 100, starred=True)) is False

    def test_a_post_clear_message_is_kept_whether_starred_or_not(self):
        stub = self._stub_with_cutoff()

        assert stub._is_cleared_message("jid1", _msg("b", 900)) is False
        assert stub._is_cleared_message("jid1", _msg("b", 900, starred=True)) is False

    def test_a_chat_with_no_cutoff_keeps_everything(self):
        stub = _Stub(_chat_with([_msg("a", 100)]))
        stub.settings = {}

        assert stub._is_cleared_message("jid1", _msg("a", 100)) is False

    def test_a_non_dict_message_does_not_crash_the_starred_check(self):
        stub = self._stub_with_cutoff()

        assert stub._is_cleared_message("jid1", {}) is False

    def test_the_survivors_of_a_real_clear_all_pass_the_cutoff(self):
        """The two halves together: clear the chat, then re-run every record
        it kept through the filter the next sync would apply."""
        chat = _chat_with([_msg("a", 100), _msg("b", 200, starred=True)])
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        survivors = chat["messages"]["messages"]["records"]
        assert [m["key"]["id"] for m in survivors] == ["b"]
        assert [m for m in survivors if stub._is_cleared_message("jid1", m)] == []
