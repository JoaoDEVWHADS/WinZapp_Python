"""Issue #72: deleting a message you'd reacted to left the reaction showing
as the chat's latest activity in the chat list forever ("You reacted with
X to: <deleted message>").

Root cause: a reactionMessage is deliberately never added to a chat's
`records` (see _track_last_reaction()) — it's tracked separately in
chat["_last_reaction"] and shown in place of the last real message whenever
its timestamp is newer than anything left in `records`. Deleting the
target message removes it from `records`, but nothing recomputed whether
_last_reaction's target still exists — so with no newer message behind it,
the stale reaction preview outlived the message it was pointing to
indefinitely.

_recompute_chat_last_message() (already the single place that reconciles a
chat's preview/sort state after any message removal — local delete,
revoke-for-everyone, remote-mirrored deletion) now also drops
chat["_last_reaction"] once its target_id is no longer among the surviving
records.

MainWindow is a wx.Frame and can't be instantiated without a running
wx.App, so the method under test is bound onto a plain stub — same
approach as tests/test_clear_chat_preserves_position.py.
"""

from main import MainWindow


class _FakeDB:
    def upsert_chat(self, jid, chat):
        pass


class _Stub:
    _recompute_chat_last_message = MainWindow._recompute_chat_last_message
    _counts_as_last_message = MainWindow._counts_as_last_message

    def __init__(self, chat):
        self.chats = {"jid1": chat}
        self.db = _FakeDB()


def _msg(msg_id, ts):
    return {
        "key": {"remoteJid": "jid1", "fromMe": False, "id": msg_id},
        "message": {"conversation": f"text {msg_id}"},
        "messageType": "conversation",
        "messageTimestamp": ts,
    }


def _last_reaction(target_id, ts):
    return {"target_id": target_id, "timestamp": ts, "emoji": "❤️", "from_me": True}


class TestReactionPreviewClearedWhenTargetDeleted:
    def test_last_reaction_is_dropped_when_its_target_message_is_gone(self):
        # "a" was reacted to and then deleted — only "records" reflects the
        # deletion (remove_messages_by_id already filtered it out) before
        # _recompute_chat_last_message runs.
        chat = {
            "messages": {"messages": {"records": [_msg("b", 100)]}},
            "_last_reaction": _last_reaction("a", 999),
        }
        stub = _Stub(chat)

        stub._recompute_chat_last_message("jid1")

        assert "_last_reaction" not in chat

    def test_last_reaction_survives_when_its_target_is_still_present(self):
        chat = {
            "messages": {"messages": {"records": [_msg("a", 100)]}},
            "_last_reaction": _last_reaction("a", 999),
        }
        stub = _Stub(chat)

        stub._recompute_chat_last_message("jid1")

        assert chat["_last_reaction"]["target_id"] == "a"

    def test_no_last_reaction_at_all_is_a_no_op(self):
        chat = {"messages": {"messages": {"records": [_msg("a", 100)]}}}
        stub = _Stub(chat)

        stub._recompute_chat_last_message("jid1")  # must not raise

        assert "_last_reaction" not in chat
