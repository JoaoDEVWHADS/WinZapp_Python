"""Tests for chat["_last_reaction"] being reconstructed from persisted
reactionMessage records right when self.chats is loaded from the DB at
startup (MainWindow._reconstruct_last_reactions_from_records()).

tests/test_reaction_preview_after_resync.py already fixed the case where a
reaction's preview reverted to "Mensagem incompatível" once WhatsApp's
history sync happened to redeliver that same reaction after a restart/F5 —
on_historical_message() now calls _track_last_reaction() when that redelivery
arrives. But chat["_last_reaction"] is in-memory only (see
_track_last_reaction()'s own docstring), and a redelivery is not guaranteed
to happen right away (or ever, for an old reaction) — so between a cold
start and whatever resync eventually re-touches that chat, the preview
silently fell back to the chat's last REAL message instead of the reaction,
never even reaching the "Mensagem incompatível" fallback the other fix
covers. Reported live: reacting to a message shows the right preview
immediately, but after actually closing and reopening WinZapp (not merely
resyncing) the preview reverts to the pre-reaction message and stays that
way.

The reactionMessage record is already persisted (kept so
ConversationsPanel can rebuild the in-conversation reaction display — see
on_historical_message()), so _reconstruct_last_reactions_from_records()
replays it from self.chats[...]["messages"]["messages"]["records"] right
after get_chats() loads them, with no extra DB round-trip.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App — reuses the existing _MainWindowStub from test_reported_bugfixes.py.
"""

from tests.test_reported_bugfixes import _MainWindowStub

JID = "5511999999999@s.whatsapp.net"
OTHER_JID = "5511888888888@s.whatsapp.net"


def _reaction_record(target_id, emoji, ts, from_me=True):
    return {
        "messageType": "reactionMessage",
        "message": {"reactionMessage": {"key": {"id": target_id}, "text": emoji}},
        "key": {"remoteJid": JID, "fromMe": from_me, "id": f"_rxn_{target_id}_{ts}"},
        "messageTimestamp": ts,
    }


def _original_record(msg_id, text, ts):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "messageType": "conversation",
        "message": {"conversation": text},
        "messageTimestamp": ts,
    }


class TestReconstructionOnColdStart:
    def test_lone_reaction_record_repopulates_last_reaction(self):
        mw = _MainWindowStub()
        original = _original_record("orig1", "Chegando em 10 min", 1700000000)
        reaction = _reaction_record("orig1", "👍", 1700000100)
        chat = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [original, reaction]}},
        }
        mw.chats = {JID: chat}

        # No _track_last_reaction() call anywhere — this is what a fresh
        # chats dict loaded straight from the DB looks like right after
        # get_chats(), before any live event or resync has touched it.
        assert "_last_reaction" not in chat

        mw._reconstruct_last_reactions_from_records()

        preview = mw._last_msg_preview(chat)
        assert "incompat" not in preview.lower()
        assert "👍" in preview

    def test_chat_with_no_reactions_is_left_untouched(self):
        mw = _MainWindowStub()
        original = _original_record("orig1", "oi", 1700000000)
        chat = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [original]}},
        }
        mw.chats = {JID: chat}

        mw._reconstruct_last_reactions_from_records()

        assert "_last_reaction" not in chat

    def test_only_the_newest_reaction_wins(self):
        mw = _MainWindowStub()
        a = _original_record("a", "primeira", 1700000000)
        b = _original_record("b", "segunda", 1700000050)
        older_reaction = _reaction_record("a", "👍", 1700000100)
        newer_reaction = _reaction_record("b", "❤", 1700000200)
        chat = {
            "remoteJid": JID,
            # Deliberately out of chronological order — records aren't
            # guaranteed sorted the way the DB returns them.
            "messages": {"messages": {"records": [newer_reaction, a, b, older_reaction]}},
        }
        mw.chats = {JID: chat}

        mw._reconstruct_last_reactions_from_records()

        assert chat["_last_reaction"]["emoji"] == "❤"
        assert chat["_last_reaction"]["target_id"] == "b"

    def test_a_later_removal_record_clears_the_reaction(self):
        """An empty-text reactionMessage record means the reaction was
        removed — _track_last_reaction() already handles this for the live
        path; replaying persisted records must reach the same end state."""
        mw = _MainWindowStub()
        original = _original_record("orig1", "oi", 1700000000)
        added = _reaction_record("orig1", "👍", 1700000100)
        removed = _reaction_record("orig1", "", 1700000150)
        chat = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [original, added, removed]}},
        }
        mw.chats = {JID: chat}

        mw._reconstruct_last_reactions_from_records()

        assert "_last_reaction" not in chat
        preview = mw._last_msg_preview(chat)
        assert "oi" in preview

    def test_multiple_chats_are_reconstructed_independently(self):
        mw = _MainWindowStub()
        chat_a = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [
                _original_record("a1", "oi", 1700000000),
                _reaction_record("a1", "👍", 1700000100),
            ]}},
        }
        chat_b = {
            "remoteJid": OTHER_JID,
            "messages": {"messages": {"records": [
                _original_record("b1", "tudo bem?", 1700000000),
            ]}},
        }
        mw.chats = {JID: chat_a, OTHER_JID: chat_b}

        mw._reconstruct_last_reactions_from_records()

        assert chat_a["_last_reaction"]["emoji"] == "👍"
        assert "_last_reaction" not in chat_b

    def test_missing_records_wrapper_does_not_raise(self):
        mw = _MainWindowStub()
        mw.chats = {JID: {"remoteJid": JID}}

        mw._reconstruct_last_reactions_from_records()  # must not raise
