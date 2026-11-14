"""Tests for MainWindow._apply_remote_revoke() — reacting live to a message
someone else deleted ("delete for everyone") while it's already on screen.

Reported live: unlike the official client, which swaps a deleted message for
"Mensagem apagada" the instant the delete arrives (and stops playback if you
were mid-listen to an audio note), WinZapp kept showing the original content
— audio kept playing — until the next periodic remote-deletion poll
(_mirror_remote_deletions, which only removes the row outright, not marks it
deleted, and can take a while to run at all).

Root cause: a "delete for everyone" arrives live as a normal message re-using
the SAME key.id as the message it deletes (messageType "protocolMessage",
type 3/REVOKE) — on_new_message()'s dedup path already recognized the
duplicate id and routed it to _apply_possible_edit(), but that function only
ever handled TEXT edits: for anything else (audio, image, a revoke's own
protocolMessage type) `_text_of()` returns None and it silently no-ops,
leaving the original record completely untouched.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a small
stub — same approach as tests/test_message_bookmarks.py.
"""

import pytest

from main import MainWindow
from core.websocket_client import WebSocketClient


@pytest.fixture(autouse=True)
def _synchronous_call_after(monkeypatch):
    """_apply_remote_revoke() notifies the conversation panel via
    wx.CallAfter(), which asserts a running wx.App exists — run it inline
    instead so this can be tested as a plain function, same as every other
    wx.CallAfter-using method under test elsewhere in this suite."""
    monkeypatch.setattr("main.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


class _FakeExecutor:
    def submit(self, fn, *a, **kw):
        fn(*a, **kw)  # run synchronously — no need for real threading in a test


class _FakeConversationsPanel:
    def __init__(self):
        self.revoked_calls = []

    def on_message_revoked(self, msg_id):
        self.revoked_calls.append(msg_id)


class _Stub:
    _apply_remote_revoke = MainWindow._apply_remote_revoke
    _revoke_stored_copies = MainWindow._revoke_stored_copies

    def __init__(self):
        self.db = _FakeDb()
        self._msg_bg_executor = _FakeExecutor()
        self.conversations_panel = _FakeConversationsPanel()
        self.set_chats_calls = 0

    def _schedule_set_chats(self):
        self.set_chats_calls += 1


class _FakeDb:
    def __init__(self):
        self.inserted = []

    def insert_message(self, remote_jid, record):
        self.inserted.append((remote_jid, dict(record)))

    def upsert_chat(self, jid, chat):
        self.upserted = getattr(self, "upserted", []) + [jid]


def _text_msg(mid, text="oi"):
    return {
        "key": {"id": mid, "fromMe": False},
        "messageType": "conversation",
        "message": {"conversation": text},
        "messageTimestamp": 1000,
    }


def _audio_msg(mid):
    return {
        "key": {"id": mid, "fromMe": False},
        "messageType": "audioMessage",
        "message": {"audioMessage": {"url": "https://example/x.ogg", "seconds": 5}},
        "messageTimestamp": 1000,
    }


def _revoke(mid):
    return {
        "key": {"id": mid, "fromMe": False},
        "messageType": "protocolMessage",
        "message": {"protocolMessage": {"type": 3}},
    }


class TestApplyRemoteRevoke:
    def test_a_text_message_being_revoked_is_marked_deleted(self):
        s = _Stub()
        existing = _text_msg("A")
        handled = s._apply_remote_revoke(existing, _revoke("A"), "jid@g.us")
        assert handled is True
        assert existing["messageType"] == "protocolMessage"
        assert existing["message"]["protocolMessage"]["type"] == 3

    def test_an_audio_message_being_revoked_is_marked_deleted(self):
        """This is exactly the case _apply_possible_edit's old text-only
        _text_of() check silently ignored — audio kept "playing" as far as
        the stored record was concerned."""
        s = _Stub()
        existing = _audio_msg("B")
        handled = s._apply_remote_revoke(existing, _revoke("B"), "jid@g.us")
        assert handled is True
        assert existing["messageType"] == "protocolMessage"

    def test_notifies_the_conversation_panel_to_stop_playback_and_refresh(self):
        s = _Stub()
        existing = _audio_msg("C")
        s._apply_remote_revoke(existing, _revoke("C"), "jid@g.us")
        assert s.conversations_panel.revoked_calls == ["C"]

    def test_persists_the_revoked_record_and_refreshes_the_chat_list(self):
        s = _Stub()
        existing = _text_msg("D")
        s._apply_remote_revoke(existing, _revoke("D"), "jid@g.us")
        assert s.db.inserted == [("jid@g.us", existing)]
        assert s.set_chats_calls == 1

    def test_clears_a_stale_edited_marker(self):
        s = _Stub()
        existing = _text_msg("E")
        existing["_edited"] = True
        s._apply_remote_revoke(existing, _revoke("E"), "jid@g.us")
        assert "_edited" not in existing

    def test_a_second_revoke_of_an_already_revoked_message_is_a_no_op(self):
        s = _Stub()
        existing = _text_msg("F")
        s._apply_remote_revoke(existing, _revoke("F"), "jid@g.us")
        s.db.inserted.clear()
        s.set_chats_calls = 0
        s.conversations_panel.revoked_calls.clear()

        handled = s._apply_remote_revoke(existing, _revoke("F"), "jid@g.us")

        assert handled is True
        assert s.db.inserted == []
        assert s.set_chats_calls == 0
        assert s.conversations_panel.revoked_calls == []

    def test_a_normal_message_is_not_treated_as_a_revoke(self):
        s = _Stub()
        existing = _text_msg("G", text="oi")
        incoming = _text_msg("G", text="oi, tudo bem?")
        assert s._apply_remote_revoke(existing, incoming, "jid@g.us") is False
        assert existing["messageType"] == "conversation"


class _NormalizeStub:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _raw_wpp_revoke(protocol_key):
    return {
        "id": "true_5511999999999@c.us_REVOKEEVENTID",
        "from": "5511999999999@c.us",
        "to": "5511999999999@c.us",
        "fromMe": True,
        "timestamp": 1700000000,
        "type": "revoked",
        "protocolMessageKey": protocol_key,
    }


class TestRevokeNormalization:
    # Real WhatsApp message ids are a single alphanumeric token — never
    # underscore-separated — because clean_message_id() (core/message_edit.py)
    # takes a fixed field position (index 2, or the last field for a group's
    # trailing participant suffix) out of the serialized `true_<jid>_<id>`/
    # `true_<jid>_<id>_<participant>` key; an id with its own underscores
    # would collide with that positional split.
    def test_revoke_event_reuses_the_deleted_messages_id(self):
        raw = _raw_wpp_revoke(
            "true_5511999999999@c.us_ORIGINALMESSAGEID"
        )

        result = _NormalizeStub()._normalize_wpp_message(raw)

        assert result["key"]["id"] == "ORIGINALMESSAGEID"
        assert result["messageType"] == "protocolMessage"
        assert result["message"]["protocolMessage"] == {
            "type": 3,
            "key": "ORIGINALMESSAGEID",
        }

    def test_revoke_target_accepts_msgkey_shaped_protocol_key(self):
        raw = _raw_wpp_revoke({
            "_serialized": "true_5511999999999@c.us_ORIGINALMESSAGEID"
        })

        result = _NormalizeStub()._normalize_wpp_message(raw)

        assert result["key"]["id"] == "ORIGINALMESSAGEID"

    def test_revoke_without_target_keeps_its_event_id_as_fallback(self):
        result = _NormalizeStub()._normalize_wpp_message(
            _raw_wpp_revoke(None)
        )

        assert result["key"]["id"] == "REVOKEEVENTID"
        assert result["message"]["protocolMessage"]["type"] == 3


class TestEveryStoredCopyIsRevoked:
    """Reported: deleting the last message left its text in the chat list
    until another conversation was opened. The records held the message
    twice; the conversation showed (and revoked) the last copy, the preview
    read the first."""

    def _stub_with_chat(self, records, last=None):
        s = _Stub()
        s.chats = {"jid@g.us": {"remoteJid": "jid@g.us", "lastMessage": last,
                                "messages": {"messages": {"records": records}}}}
        s._normalize_jid = lambda jid: jid
        return s

    def test_the_other_copy_becomes_the_tombstone(self):
        first, second = _text_msg("A", "segredo"), _text_msg("A", "segredo")
        s = self._stub_with_chat([first, second])
        s._apply_remote_revoke(second, _revoke("A"), "jid@g.us")
        assert first["messageType"] == second["messageType"] == "protocolMessage"
        assert "segredo" not in str(first)

    def test_a_last_message_that_is_the_revoked_one_is_revoked_and_saved(self):
        last = _text_msg("A", "segredo")
        s = self._stub_with_chat([_text_msg("A", "segredo")], last=last)
        s._apply_remote_revoke(s.chats["jid@g.us"]["messages"]["messages"]["records"][0],
                               _revoke("A"), "jid@g.us")
        assert last["messageType"] == "protocolMessage"
        assert s.db.upserted == ["jid@g.us"]

    def test_a_last_message_that_is_the_record_itself_is_still_saved(self):
        """Reviewer: live messages set lastMessage to the very record, which
        is already the tombstone when the copies are revoked; the chat row
        kept the withdrawn text in the database."""
        record = _text_msg("A", "segredo")
        s = self._stub_with_chat([record], last=record)
        s._apply_remote_revoke(record, _revoke("A"), "jid@g.us")
        assert record["messageType"] == "protocolMessage"
        assert s.db.upserted == ["jid@g.us"]

    def test_a_newer_last_message_is_left_alone_and_not_rewritten(self):
        """Reviewer: recomputing it from the records put an older preview over
        a newer lastMessage and moved the chat down the list."""
        newer = _text_msg("Z", "mais nova")
        s = self._stub_with_chat([_text_msg("A")], last=newer)
        s._apply_remote_revoke(s.chats["jid@g.us"]["messages"]["messages"]["records"][0],
                               _revoke("A"), "jid@g.us")
        assert newer["messageType"] == "conversation"
        assert not getattr(s.db, "upserted", [])

    def test_a_copy_of_another_message_is_left_alone(self):
        other = _text_msg("B", "fica")
        target = _text_msg("A")
        s = self._stub_with_chat([other, target])
        s._apply_remote_revoke(target, _revoke("A"), "jid@g.us")
        assert other["messageType"] == "conversation"


class TestMarkCopiesRevoked:
    def test_only_the_id_and_only_what_is_not_a_tombstone(self):
        from core.revoked_copies import mark_copies_revoked
        tomb = {"protocolMessage": {"type": 3}}
        records = [_text_msg("A"), _text_msg("B"), dict(_text_msg("A"), _edited=True,
                                                        transcription="t"),
                   {"key": {"id": "A"}, "messageType": "protocolMessage", "message": "old"}, None]
        assert mark_copies_revoked(records, "A", tomb, drop_keys=("transcription",)) == 2
        assert records[0]["message"] is tomb and records[1]["messageType"] == "conversation"
        assert "_edited" not in records[2] and "transcription" not in records[2]
        assert records[3]["message"] == "old"
        assert mark_copies_revoked(records, "", tomb) == 0
        assert mark_copies_revoked(None, "A", tomb) == 0
