"""Regression test for clear_chat_messages_local() sending a cleared
conversation to the bottom of the chat list.

Reported live: since v0.24.0.0beta, clearing a conversation moved it to the
very end of the chat list instead of keeping its position. Root cause:
_recompute_chat_last_message() zeroes chat["t"] when no messages survive the
clear, and _chat_last_ts() (main.py) treats t=0 as ts=1 — the oldest
possible sort key, so the chat always sorts last. Clearing must only empty
the preview, not move the conversation.
"""

from main import MainWindow


class _FakeDB:
    def __init__(self):
        self.upsert_calls = []

    def delete_chat_messages_except(self, remote_jid, keep_message_ids):
        pass

    def upsert_chat(self, jid, chat):
        self.upsert_calls.append(jid)


class _Stub:
    clear_chat_messages_local = MainWindow.clear_chat_messages_local
    _recompute_chat_last_message = MainWindow._recompute_chat_last_message
    _counts_as_last_message = MainWindow._counts_as_last_message

    def __init__(self, chat):
        self.chats = {"jid1": chat}
        self.settings = {}
        self.db = _FakeDB()

    def save_settings(self):
        pass

    def _schedule_save(self, dirty_jid=None):
        pass


def _msg(msg_id, ts, starred=False):
    return {
        "key": {"remoteJid": "jid1", "fromMe": False, "id": msg_id},
        "message": {"conversation": f"text {msg_id}"},
        "messageType": "conversation",
        "messageTimestamp": ts,
        "starred": starred,
    }


def _chat_with(records, t):
    return {
        "remoteJid": "jid1",
        "messages": {"messages": {"records": records}},
        "lastMessage": records[-1] if records else None,
        "t": t,
        "unreadCount": 3,
    }


class TestClearChatPreservesListPosition:
    def test_t_keeps_previous_value_when_no_messages_survive(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 500)], t=500)
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert chat["t"] == 500
        assert chat["lastMessage"] is None

    def test_t_reflects_surviving_starred_message_instead(self):
        chat = _chat_with([_msg("a", 100, starred=True), _msg("b", 500)], t=500)
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert chat["t"] == 100
        assert chat["lastMessage"]["key"]["id"] == "a"

    def test_db_upsert_called_to_persist_restored_t(self):
        chat = _chat_with([_msg("a", 100), _msg("b", 500)], t=500)
        stub = _Stub(chat)

        stub.clear_chat_messages_local("jid1")

        assert "jid1" in stub.db.upsert_calls
