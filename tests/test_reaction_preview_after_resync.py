"""Tests for the chat-list preview showing "Mensagem incompatível" after a
restart or F5 resync, when the conversation's last event was a reaction.

Reported live: reacting to a message shows the correct "você reagiu com X"
preview immediately (on_new_message()/_on_own_reaction_sent() both call
_track_last_reaction()), but after closing and reopening WinZapp — or
pressing F5 to resync — the SAME chat's preview showed "Mensagem
incompatível" instead.

Root cause, in two parts:

1. chat["_last_reaction"] (populated by _track_last_reaction(), consumed by
   _last_msg_preview() to render the reaction summary) is in-memory only.
   A restart/resync wipes it, and on_historical_message() — the function
   that processes WhatsApp's history-sync redelivery of that same reaction
   event — never called _track_last_reaction() to repopulate it, unlike
   on_new_message() (the live path). Fixed by adding that call.

2. Independently, MainWindow._PREVIEW_MESSAGE_TYPES (the allowlist behind
   _counts_as_last_message()) used to include "reactionMessage" — so once
   _last_reaction was empty, _last_msg_preview() picked the raw
   reactionMessage record itself as the chat's "last message". That record
   has no rendering case in _last_msg_preview()'s type switch, so it fell
   through to the generic "notif_unsupported" ("Mensagem incompatível")
   text. Fixed by excluding "reactionMessage" from that allowlist — see
   tests/test_chat_ordering.py's test_reaction_message_does_not_count()
   for the dedicated coverage of that half of the fix.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so _last_msg_preview()/_track_last_reaction() are exercised via the
existing _MainWindowStub from tests/test_reported_bugfixes.py.
"""

import inspect

from main import MainWindow
from tests.test_reported_bugfixes import _MainWindowStub

JID = "5511999999999@s.whatsapp.net"


def _reaction_record(ts=1700000100):
    return {
        "messageType": "reactionMessage",
        "message": {
            "reactionMessage": {"key": {"id": "orig1"}, "text": "👍"},
        },
        "key": {"remoteJid": JID, "fromMe": True, "id": "_rxn_orig1"},
        "messageTimestamp": ts,
    }


def _original_record(ts=1700000000):
    return {
        "key": {"id": "orig1", "fromMe": False},
        "messageType": "conversation",
        "message": {"conversation": "Chegando em 10 min"},
        "messageTimestamp": ts,
    }


class TestOnHistoricalMessageCallsTrackLastReaction:
    """on_historical_message() is a large method deep in DB/threading/wx
    interactions not practical to drive end to end here — the wiring is
    pinned structurally via source inspection, same approach used
    elsewhere in this codebase for similarly heavy methods."""

    def test_reaction_messages_trigger_track_last_reaction(self):
        src = inspect.getsource(MainWindow.on_historical_message)
        assert 'msg.get("messageType") == "reactionMessage"' in src
        assert "self._track_last_reaction(remote_jid, msg)" in src

    def test_the_call_happens_before_the_record_is_appended(self):
        """Order matters only in that both must happen — _track_last_reaction
        must run somewhere in the function, and the record must still reach
        `records` afterwards (needed for the in-conversation reaction
        display) rather than being skipped via an early return."""
        src = inspect.getsource(MainWindow.on_historical_message)
        track_pos  = src.index("self._track_last_reaction(remote_jid, msg)")
        append_pos = src.index("records.append(msg)")
        assert track_pos < append_pos


class TestPreviewAfterSimulatedResync:
    """Simulates what on_historical_message() now does when WhatsApp's
    history sync redelivers a reaction after a restart/F5: the reaction
    record lands in `records` (as it always did) AND _track_last_reaction()
    is called (the fix) — exactly as if a fresh chat object had just been
    rebuilt from a cold start with no _last_reaction carried over."""

    def test_a_lone_reaction_after_restart_shows_the_reaction_preview(self):
        mw = _MainWindowStub()
        reaction = _reaction_record()
        original = _original_record()
        chat = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [original, reaction]}},
        }
        mw.chats = {JID: chat}

        # What on_historical_message() now does for a reactionMessage record.
        mw._track_last_reaction(JID, reaction)

        preview = mw._last_msg_preview(chat)
        assert "incompat" not in preview.lower()
        assert "👍" in preview

    def test_without_the_fix_a_lone_reaction_record_alone_is_never_shown_as_unsupported(self):
        """Even if _track_last_reaction() were somehow never called (e.g. a
        future refactor drops it again), the second half of the fix
        (_PREVIEW_MESSAGE_TYPES no longer including reactionMessage) means
        the raw record still can't surface as "Mensagem incompatível" — the
        preview falls back to the last real message instead."""
        mw = _MainWindowStub()
        reaction = _reaction_record()
        original = _original_record()
        chat = {
            "remoteJid": JID,
            "messages": {"messages": {"records": [original, reaction]}},
        }
        mw.chats = {JID: chat}

        # Deliberately NOT calling _track_last_reaction() here.
        preview = mw._last_msg_preview(chat)

        assert "incompat" not in preview.lower()
        assert "Chegando em 10 min" in preview
