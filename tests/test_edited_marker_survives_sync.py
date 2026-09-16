"""The "Editada" marker must survive a sync, a restart and another device.

``_edited`` was only ever set by WinZapp itself — the optimistic local edit and
the live edit echo (_apply_possible_edit()). A sync replaces a chat's records
with the server's copies, which never carried it, so every edited message went
back to looking unedited, and an edit made on the phone was never marked at
all.

WhatsApp Web does keep the fact. Read over DevTools from the running app
(2026-09-14): an edited reply came back from WAPI.getMessages — the call behind
get-messages — with ``latestEditMsgKey`` (an object with ``_serialized``) and
``latestEditSenderTimestampMs`` (a number); 4 of the 60 messages fetched had
them. The normaliser now reads that, and the sync merge keeps a local marker
the server copy does not restate.
"""

import inspect

from core.message_edit import carry_over_edited_marker, server_marks_edited
from core.websocket_client import WebSocketClient
from main import MainWindow

GROUP = "120363427511142886@g.us"


class _Normalizer:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _raw(mid="3EB037EC32C70B38BF05EB", **overrides):
    raw = {
        "id": f"true_{GROUP}_{mid}", "from": "5511999999999@c.us", "to": GROUP,
        "fromMe": True, "timestamp": 1789360394, "type": "chat", "body": "depois",
    }
    raw.update(overrides)
    return raw


# The shape measured on the live page.
_EDIT_FIELDS = {
    "latestEditMsgKey": {"fromMe": True, "remote": GROUP, "id": "3EB0BC2F9AA9CFAFBB5098",
                         "_serialized": f"true_{GROUP}_3EB0BC2F9AA9CFAFBB5098"},
    "latestEditSenderTimestampMs": 1789360406,
}


class TestNormalizer:
    def test_a_message_whatsapp_marks_as_edited_is_marked(self):
        result = _Normalizer()._normalize_wpp_message(_raw(**_EDIT_FIELDS))
        assert result["_edited"] is True

    def test_an_edited_reply_keeps_its_quote_and_the_marker(self):
        raw = _raw(**_EDIT_FIELDS, quotedStanzaID="3EB0QUOTEDQUOTEDQUOTE1",
                   quotedParticipant="5511888888888@c.us")
        result = _Normalizer()._normalize_wpp_message(raw)
        assert result["_edited"] is True
        assert result["messageType"] == "extendedTextMessage"

    def test_an_unedited_message_is_not_marked(self):
        result = _Normalizer()._normalize_wpp_message(_raw())
        assert "_edited" not in result

    def test_a_null_key_is_not_an_edit(self):
        result = _Normalizer()._normalize_wpp_message(_raw(latestEditMsgKey=None))
        assert "_edited" not in result

    def test_a_revoked_message_never_reads_edited(self):
        result = _Normalizer()._normalize_wpp_message(_raw(type="revoked", **_EDIT_FIELDS))
        assert "_edited" not in result

    def test_the_edit_event_itself_is_not_marked(self):
        """wa-js sets latestEditMsgKey on the protocol message it creates; that
        event is dropped, but it must not look like an edited row either."""
        raw = _raw(mid="3EB0BC2F9AA9CFAFBB5098", type="protocol", subtype="message_edit",
                   protocolMessageKey=f"true_{GROUP}_3EB037EC32C70B38BF05EB",
                   **_EDIT_FIELDS)
        result = _Normalizer()._normalize_wpp_message(raw)
        assert "_edited" not in result


class TestServerMarksEdited:
    def test_non_dict(self):
        assert server_marks_edited(None) is False

    def test_protocol_types_are_never_marked(self):
        assert server_marks_edited({"type": "protocol", **_EDIT_FIELDS}) is False

    def test_a_serialized_string_key_counts_too(self):
        assert server_marks_edited({
            "type": "chat",
            "latestEditMsgKey": f"true_{GROUP}_3EB0BC2F9AA9CFAFBB5098",
        }) is True


class _Executor:
    def submit(self, fn, *a, **kw):
        fn(*a, **kw)


class _Db:
    def __init__(self):
        self.inserted = []

    def insert_message(self, jid, record):
        self.inserted.append((jid, record["key"]["id"]))


class _EchoStub:
    _apply_possible_edit = MainWindow._apply_possible_edit
    _apply_remote_revoke = MainWindow._apply_remote_revoke
    _persist_and_repaint_edit = MainWindow._persist_and_repaint_edit

    def __init__(self):
        self.db = _Db()
        self._msg_bg_executor = _Executor()
        self.repaints = 0
        stub = self

        class _Panel:
            def refresh_active_conversation_messages(self):
                stub.repaints += 1

        self.conversations_panel = _Panel()

    def _schedule_set_chats(self):
        pass


def _rec(mid, edited=False, mtype="conversation"):
    r = {"key": {"id": mid}, "messageType": mtype, "message": {"conversation": "x"}}
    if edited:
        r["_edited"] = True
    return r


class TestCarryOver:
    def test_a_local_marker_survives_a_server_copy_without_it(self):
        new = [_rec("a"), _rec("b")]
        assert carry_over_edited_marker(new, [_rec("a", edited=True), _rec("b")]) == 1
        assert new[0]["_edited"] is True
        assert "_edited" not in new[1]

    def test_a_deleted_message_does_not_inherit_the_marker(self):
        new = [_rec("a", mtype="protocolMessage")]
        assert carry_over_edited_marker(new, [_rec("a", edited=True)]) == 0
        assert "_edited" not in new[0]

    def test_an_already_marked_copy_is_not_counted(self):
        new = [_rec("a", edited=True)]
        assert carry_over_edited_marker(new, [_rec("a", edited=True)]) == 0

    def test_nothing_marked_locally_is_a_no_op(self):
        new = [_rec("a")]
        assert carry_over_edited_marker(new, [_rec("a")]) == 0
        assert carry_over_edited_marker(new, None) == 0

    def test_a_live_echo_with_the_same_text_still_sets_a_missing_marker(self, monkeypatch):
        """A sync applied the new text before the marker existed; the edit echo
        then arrives with identical text. It used to be a no-op, leaving the
        row unmarked until the next sync."""
        monkeypatch.setattr("main.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
        stub = _EchoStub()
        existing = _rec("a")
        incoming = _rec("a", edited=True)

        stub._apply_possible_edit(existing, incoming, GROUP)

        assert existing["_edited"] is True
        assert stub.db.inserted == [(GROUP, "a")]
        assert stub.repaints == 1

    def test_a_plain_redelivery_with_the_same_text_changes_nothing(self, monkeypatch):
        monkeypatch.setattr("main.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
        stub = _EchoStub()
        existing = _rec("a")

        stub._apply_possible_edit(existing, _rec("a"), GROUP)

        assert "_edited" not in existing
        assert stub.db.inserted == []

    def test_the_sync_merge_runs_it_before_writing_records(self):
        """The merged list is what sync_chat_messages writes with
        insert_messages_batch(), so carrying in memory also reaches the disk."""
        src = inspect.getsource(MainWindow.sync_chat_messages)
        assert "carry_over_edited_marker(all_messages, local_records)" in src
        assert (src.index("carry_over_edited_marker(")
                < src.index("self.db.insert_messages_batch(remote_jid, all_messages)"))
