"""Regression tests: a text message could end up duplicated forever.

Two separate bugs combined to produce this. Both are in the "our own message
comes back over the WebSocket" path — see CLAUDE.md's note on echo-matching
being the most fragile part of the message pipeline.

1. send_text_message() reports success as soon as the HTTP response comes
   back with status 200/201, but if the response body's id couldn't be
   parsed it used to still tell the rest of the app "sent" with no id at
   all. ConversationsPanel._mark_message_sent() then finalised the row (
   cleared _local_pending) regardless — which is exactly the flag
   on_new_message()'s echo match requires a row to still have. The one and
   only real id this message would ever receive arrived a moment later on
   the WebSocket, found no eligible row to attach to, and got appended as a
   brand new message instead: the same text, twice, permanently.

   Fix: _mark_message_sent() now returns without finalising the row when it
   isn't handed a real string id — leaving it pending for the second call
   the echo triggers, which always does carry one.

2. Separately, on_new_message()'s echo match picks the first still-pending
   row of the same message type — "conversation" and "extendedTextMessage"
   both count as one type for this purpose — with no correlation beyond
   that. A message already resolved via the synchronous HTTP-response path
   (its id recorded in _own_sent_ids the moment that response came back)
   whose echo is redelivered, or simply arrives late while a *second*
   message of the same type is still sending, would steal that second
   message's pending slot: the wrong row gets the id, and the message that
   id actually belongs to is left exactly where bug 1 leaves an unresolved
   send — permanently duplicated once its own real echo shows up with
   nothing left to match.

   Fix: the type search is skipped entirely for an id already present in
   _own_sent_ids, letting it fall through to the exact id/edit check that
   already exists further down instead.

MainWindow is a wx.Frame and ConversationsPanel a wx.Panel, neither
instantiable without a running wx.App — both methods are exercised against
plain stubs, same approach as tests/test_lid_merge_keeps_messages.py (whose
own docstring explains why on_new_message can't be driven through a real
instance) and tests/test_quote_lost_drops_reply_header.py.
"""

import threading

from main import MainWindow
from ui.conversations import ConversationsPanel

REMOTE = "5511999999999@s.whatsapp.net"


# ── Bug 1: _mark_message_sent must not finalise a row with no real id ───────


class _FakeList:
    def SetItemText(self, index, text):
        pass


class _FakeMainWindow:
    def _schedule_save(self, dirty_jid=None):
        pass

    def _schedule_set_chats(self):
        pass


def _make_panel(msg):
    panel = ConversationsPanel.__new__(ConversationsPanel)
    panel._sorted_messages = [msg]
    panel._played_sent_local_ids = set()
    panel._outgoing_virtual_messages = {"loc-1": msg}
    panel._media_upload_progress = {}
    panel._media_transfer_started = set()
    panel._hide_media_transfer_gauge = lambda: None
    panel.messages_list = _FakeList()
    panel.conversation = {"remoteJid": REMOTE}
    panel.main_window = _FakeMainWindow()
    panel._render_message_line = lambda m, **kw: "RENDERED:" + str(m.get("_local_id"))
    return panel


def _make_msg(**overrides):
    msg = {
        "_local_id": "loc-1",
        "_local_pending": True,
        "key": {"id": "loc-1", "fromMe": True, "remoteJid": REMOTE},
        "messageType": "conversation",
        "message": {"conversation": "teste"},
        "messageTimestamp": 1,
        "pushName": "",
    }
    msg.update(overrides)
    return msg


class TestMarkMessageSentWithNoRealId:
    def test_the_row_is_left_pending(self):
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id=None)

        assert msg["_local_pending"] is True
        assert msg["key"]["id"] == "loc-1"

    def test_the_outgoing_index_entry_survives_for_the_second_call(self):
        """Popping it here would break navigate_to_conversation()'s restore
        of a still-pending bubble for the (arbitrarily long) time until the
        echo actually resolves it."""
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id=None)

        assert panel._outgoing_virtual_messages == {"loc-1": msg}

    def test_a_non_string_real_id_is_treated_the_same_as_none(self):
        """send_text_message() can report "sent, id unknown" as a bare
        True — see message_queue.py's isinstance(real_id, str) guard."""
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id=True)

        assert msg["_local_pending"] is True

    def test_the_row_is_never_flagged_as_shown_sent(self):
        """_ui_sent is what guards against playing the sent sound/re-
        rendering twice — it must stay unset until the call that actually
        carries a real id."""
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id=None)

        assert "_ui_sent" not in msg

    def test_a_second_call_with_the_real_id_resolves_it_normally(self):
        """This is the call on_new_message()'s echo match makes once the
        real id shows up — the row must still be resolvable afterwards,
        exactly as if the first, inconclusive call had never happened."""
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id=None)
        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id="REAL")

        assert msg["_local_pending"] is False
        assert msg["key"]["id"] == "REAL"
        assert msg["_ui_sent"] is True


class TestMarkMessageSentWithARealId:
    def test_still_resolves_normally(self):
        """Guards against the id-present path regressing while touching the
        function above it."""
        msg = _make_msg()
        panel = _make_panel(msg)

        ConversationsPanel._mark_message_sent(panel, "loc-1", real_id="REAL")

        assert msg["_local_pending"] is False
        assert msg["key"]["id"] == "REAL"
        assert "loc-1" not in panel._outgoing_virtual_messages


# ── Bug 2: an already-resolved echo must not steal a different pending row ──


class _SyncExecutor:
    """Stands in for _msg_bg_executor: the DB write it would schedule is
    irrelevant here and dropping it keeps this stub free of a fake db."""

    def submit(self, fn):
        return None


class _Stub:
    on_new_message = MainWindow.on_new_message

    def __init__(self, chat, own_sent_ids=()):
        self.chats = {REMOTE: chat}
        self._deleted_chats = set()
        self._own_sent_ids = set(own_sent_ids)
        self._own_sent_ids_lock = threading.Lock()
        self._msg_bg_executor = _SyncExecutor()
        self.applied_edits = []

    # Reached unconditionally before the from_me branch — all no-ops for a
    # plain 1:1 text message with no lid/group involved.
    def _live_events_ready(self):
        return True

    def _normalize_jid(self, jid):
        return jid

    def _is_self_jid(self, jid):
        return False

    def _extract_lid_mapping(self, msg):
        pass

    def _redirect_self_chat_artifact(self, remote_jid, key, from_me):
        # Real MainWindow.on_new_message() calls this (see
        # _redirect_self_chat_artifact()'s own docstring/PR) to catch a fake
        # self-chat sync artifact — irrelevant to the echo-matching this file
        # tests, so it's a pure passthrough here rather than a stubbed-out
        # dependency this stub simply doesn't have.
        return remote_jid, from_me

    def _apply_group_subject_change(self, remote_jid, chat, msg, live=False):
        pass

    def _refresh_mention_cache_on_membership_change(self, remote_jid, msg):
        pass

    def _apply_possible_edit(self, existing, msg, remote_jid):
        self.applied_edits.append((existing, msg, remote_jid))

    def _schedule_save(self, dirty_jid=None):
        pass

    def _schedule_set_chats(self):
        pass


def _chat_with(records):
    return {
        "remoteJid": REMOTE,
        "unreadCount": 0,
        "messages": {"messages": {"records": records}},
    }


def _pending_record(local_id, local_pending=True, real_id=None):
    return {
        "key": {"id": real_id or local_id, "fromMe": True, "remoteJid": REMOTE},
        "messageType": "conversation",
        "_local_id": local_id,
        "_local_pending": local_pending,
        "messageTimestamp": 0,
    }


def _echo(msg_id, message_type="conversation"):
    return {
        "key": {"id": msg_id, "fromMe": True, "remoteJid": REMOTE},
        "messageType": message_type,
        "message": {"conversation": "teste"},
        "messageTimestamp": 5,
        "pushName": "",
    }


class TestEchoAlreadyResolvedDoesNotStealAPendingRow:
    def test_a_redelivered_resolved_echo_leaves_the_other_pending_row_alone(self):
        record_a = _pending_record("locA", local_pending=False, real_id="REAL_A")
        record_b = _pending_record("locB", local_pending=True)
        stub = _Stub(_chat_with([record_a, record_b]), own_sent_ids={"REAL_A"})

        stub.on_new_message(_echo("REAL_A"))

        assert record_b["_local_pending"] is True
        assert record_b["key"]["id"] == "locB"

    def test_the_redelivered_echo_is_routed_to_the_edit_check_instead(self):
        record_a = _pending_record("locA", local_pending=False, real_id="REAL_A")
        record_b = _pending_record("locB", local_pending=True)
        stub = _Stub(_chat_with([record_a, record_b]), own_sent_ids={"REAL_A"})

        stub.on_new_message(_echo("REAL_A"))

        assert len(stub.applied_edits) == 1
        assert stub.applied_edits[0][0] is record_a

    def test_no_duplicate_record_is_appended(self):
        record_a = _pending_record("locA", local_pending=False, real_id="REAL_A")
        record_b = _pending_record("locB", local_pending=True)
        chat = _chat_with([record_a, record_b])
        stub = _Stub(chat, own_sent_ids={"REAL_A"})

        stub.on_new_message(_echo("REAL_A"))

        assert len(chat["messages"]["messages"]["records"]) == 2


class TestEchoMatchingStillWorksWhenNothingIsAlreadyResolved:
    def test_the_only_pending_row_of_that_type_is_matched(self):
        record_b = _pending_record("locB", local_pending=True)
        stub = _Stub(_chat_with([record_b]))

        stub.on_new_message(_echo("REAL_B"))

        assert record_b["_local_pending"] is False
        assert record_b["key"]["id"] == "REAL_B"

    def test_the_resolved_id_is_remembered(self):
        record_b = _pending_record("locB", local_pending=True)
        stub = _Stub(_chat_with([record_b]))

        stub.on_new_message(_echo("REAL_B"))

        assert "REAL_B" in stub._own_sent_ids
