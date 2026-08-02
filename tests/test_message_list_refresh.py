"""Tests for the guard that stops background refreshes rebuilding the message list.

Reported live: "o programa desvia o foco da lista de mensagens do nada" — every
so often, mid-read, focus jumped to a random message in the middle of the
conversation. The 60-second poll (start_periodic_contacts_sync) and the history
backfill both called populate_messages(preserve_focus=True) unconditionally, and
that does a full DeleteAllItems() + re-Append() of the native ListView. Even with
preserve_focus it can only restore focus to the *message* it saved — the moment
that message is no longer in the paginated window, or the list was sitting on the
unread separator, focus lands somewhere else entirely.

refresh_messages_if_changed() compares a fingerprint of what would be rendered
and skips the rebuild when nothing changed, so periodic polls stop touching the
list at all. Anything that genuinely changed still rebuilds.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against a
small stub — same approach as tests/test_message_bookmarks.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _Stub:
    _messages_signature = ConversationsPanel._messages_signature
    refresh_messages_if_changed = ConversationsPanel.refresh_messages_if_changed

    def __init__(self, records=None, jid="g@g.us"):
        self.conversation = {
            "remoteJid": jid,
            "messages": {"messages": {"records": records if records is not None else []}},
        }
        self._first_unread_msg_id = None
        self._pending_open_unread = 0
        self._messages_signature_cache = None
        self.populate_calls = []

    # The panel's own helpers, kept trivial here: what is under test is how the
    # signature is composed and what it decides, not their formatting.
    @staticmethod
    def _extract_timestamp(msg):
        return msg.get("messageTimestamp", 0)

    @staticmethod
    def _get_message_content(msg):
        return (msg.get("message") or {}).get("conversation", "")

    def populate_messages(self, preserve_focus=False):
        self.populate_calls.append(preserve_focus)
        # Mirrors the real method's finally block, including its tolerance of a
        # signature that raises.
        try:
            self._messages_signature_cache = self._messages_signature()
        except Exception:
            self._messages_signature_cache = None

    @property
    def _records(self):
        return self.conversation["messages"]["messages"]["records"]


def _msg(mid, text="oi", ts=1000, **extra):
    m = {
        "key": {"id": mid, "fromMe": False},
        "messageType": "conversation",
        "message": {"conversation": text},
        "messageTimestamp": ts,
    }
    m.update(extra)
    return m


class TestRefreshMessagesIfChanged:
    def test_the_first_call_always_rebuilds(self):
        """Nothing has been rendered yet — there is no cached signature to trust."""
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        assert s.populate_calls == [True]

    def test_a_repeat_poll_over_unchanged_records_does_nothing(self):
        """This is the whole point: the 60s poll must not touch the list."""
        s = _Stub([_msg("a"), _msg("b")])
        s.refresh_messages_if_changed()
        for _ in range(10):
            s.refresh_messages_if_changed()
        assert s.populate_calls == [True], "only the initial render should have run"

    def test_a_new_message_rebuilds(self):
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        s._records.append(_msg("b"))
        s.refresh_messages_if_changed()
        assert s.populate_calls == [True, True]

    def test_a_deleted_message_rebuilds(self):
        s = _Stub([_msg("a"), _msg("b")])
        s.refresh_messages_if_changed()
        s._records.pop()
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_an_edited_body_rebuilds(self):
        s = _Stub([_msg("a", text="oi")])
        s.refresh_messages_if_changed()
        s._records[0]["message"]["conversation"] = "oi, tudo bem?"
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_a_delivery_status_change_rebuilds(self):
        s = _Stub([_msg("a", status="SENT")])
        s.refresh_messages_if_changed()
        s._records[0]["status"] = "READ"
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_starring_rebuilds(self):
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        s._records[0]["starred"] = True
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_pinning_rebuilds(self):
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        s._records[0]["pinInChat"] = True
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_the_edited_marker_rebuilds(self):
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        s._records[0]["_edited"] = True
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_a_pending_message_being_confirmed_rebuilds(self):
        s = _Stub([_msg("a", _local_pending=True)])
        s.refresh_messages_if_changed()
        s._records[0]["_local_pending"] = False
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_switching_conversation_rebuilds(self):
        s = _Stub([_msg("a")])
        s.refresh_messages_if_changed()
        s.conversation["remoteJid"] = "other@g.us"
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_a_moved_unread_separator_rebuilds(self):
        s = _Stub([_msg("a"), _msg("b")])
        s.refresh_messages_if_changed()
        s._first_unread_msg_id = "b"
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2

    def test_no_open_conversation_is_a_no_op(self):
        s = _Stub([_msg("a")])
        s.conversation = None
        s.refresh_messages_if_changed()
        assert s.populate_calls == []

    def test_a_broken_signature_falls_back_to_rebuilding(self):
        """A fingerprinting hiccup must never swallow a real refresh."""
        s = _Stub([_msg("a")])

        def _boom(self):
            raise RuntimeError("nope")

        s._messages_signature = _boom.__get__(s)
        s.refresh_messages_if_changed()
        assert s.populate_calls == [True]

    def test_reordering_records_rebuilds(self):
        s = _Stub([_msg("a", ts=1), _msg("b", ts=2)])
        s.refresh_messages_if_changed()
        s._records.reverse()
        s.refresh_messages_if_changed()
        assert len(s.populate_calls) == 2


class TestMessagesSignature:
    def test_malformed_records_do_not_raise(self):
        s = _Stub([None, "junk", _msg("a")])
        assert s._messages_signature()

    def test_a_missing_records_container_is_tolerated(self):
        s = _Stub()
        s.conversation = {"remoteJid": "g@g.us"}
        assert s._messages_signature()
