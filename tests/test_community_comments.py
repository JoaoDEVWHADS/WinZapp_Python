"""Community comments keep parent identity, do not retry sends, and never open wx windows."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from core.community_comments import (CommunityCommentsError, can_open_comments,
                                     comment_send_confirmed, parse_comments)
from main_window.community_comments import CommunityCommentsMixin
from ui.dialogs.community_comments import CommunityCommentsDialog

JID = "123@g.us"
PARENT = "false_123@g.us_PARENT_456@lid"

def row(mid="reply", stamp=10, kind="comment", mine=False):
    return {"id": mid, "parentMsgId": PARENT, "chatId": JID, "author": "456@lid",
            "timestamp": stamp, "type": kind, "body": "private text", "messageSecret": "secret",
            "fromMe": mine}

class API(CommunityCommentsMixin):
    wpp_server, wpp_port, token = "http://localhost", 6300, "account:secret"
    def _serialize_msg_id(self, jid, key, message):
        return key.get("id")

class Widget:
    def __init__(self, value=""):
        self.value, self.items, self.selection = value, [], -1
        self.Enable = Mock()
        self.SetEditable = Mock()
        self.SetFocus = Mock()
        self.SetLabel = Mock()
        self.Freeze, self.Thaw = Mock(), Mock()
    def GetValue(self): return self.value
    def ChangeValue(self, value): self.value = value
    def GetItems(self): return self.items
    def SetItems(self, items): self.items = items
    def GetSelection(self): return self.selection
    def SetSelection(self, index): self.selection = index

class Dialog:
    # Bind real methods to a plain Python object; no wx dialog is constructed.
    _active = CommunityCommentsDialog._active
    _update_buttons = CommunityCommentsDialog._update_buttons
    _on_refresh = CommunityCommentsDialog._on_refresh
    _finish_refresh = CommunityCommentsDialog._finish_refresh
    _on_send = CommunityCommentsDialog._on_send
    _finish_send = CommunityCommentsDialog._finish_send
    _row_label = CommunityCommentsDialog._row_label
    close_comments = CommunityCommentsDialog.close_comments
    _on_text_key = CommunityCommentsDialog._on_text_key
    _register = CommunityCommentsDialog._register
    _resend_blocked = CommunityCommentsDialog._resend_blocked
    on_reply_count_changed = CommunityCommentsDialog.on_reply_count_changed
    _run_pending_refresh = CommunityCommentsDialog._run_pending_refresh
    def __init__(self):
        self.work = []
        self._mw = SimpleNamespace(token="session", _shutting_down=False,
            i18n=SimpleNamespace(t=lambda key: {"community_comments_count":"Replies: {count}",
                                               "datetime_fmt":"%Y-%m-%d %H:%M"}.get(key, key)),
            speak_output=SimpleNamespace(output=Mock()),
            _msg_bg_executor=SimpleNamespace(submit=lambda fn: self.work.append(fn)),
            get_announcement_comments=Mock(return_value=[row()]),
            send_announcement_comment=Mock(return_value=True),
            _resolve_jid_name=Mock(return_value="Author"), _normalize_jid=lambda value:value,
            self_reference_label=lambda: "You",
            _announcement_comment_id=lambda jid, message: message["key"]["id"])
        self._jid, self._message, self._token = JID, {"key":{"id":"PARENT"}}, "session"
        self._closed = self._busy = self._loaded = self._uncertain = False
        self._refresh_pending = False
        self._rows = []
        self._list, self._text = Widget(), Widget(" exact text ")
        self._send, self._status = Widget(), Widget()

@pytest.fixture(autouse=True)
def callbacks_inline(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn,*args: fn(*args))

class TestCommentContracts:
    def test_group_candidate_and_cached_metadata(self):
        msg={"key":{"id":"parent"}}
        # Reported: every group's menu offered replies, because list-chats
        # leaves the group metadata out and a missing flag counted as "maybe".
        assert not can_open_comments({"remoteJid":JID},msg)
        assert can_open_comments({"remoteJid":JID,"groupMetadata":{"defaultSubgroup":True}},msg)
        assert not can_open_comments({"remoteJid":JID,"groupMetadata":{"defaultSubgroup":"false"}},msg)
        assert not can_open_comments({"remoteJid":"123@lid"},msg)
        assert not can_open_comments({"remoteJid":JID},{"key":"bad"})
    def test_safe_sorted_rows_and_no_stale_deleted_text(self):
        result=parse_comments({"status":"success","response":[row("b",2),row("a",1,"revoked")]},PARENT)
        assert [r["id"] for r in result]==["a","b"]
        assert result[0]["body"]==""
        assert "messageSecret" not in result[1]
        assert result[1]["author"]=="456@lid"
    @pytest.mark.parametrize("changes",[{"parentMsgId":"wrong"},{"chatId":"999@g.us"},
        {"timestamp":float("nan")},{"timestamp":True},{"type":"other"},{"author":{}},{"body":12}])
    def test_invalid_payload_is_not_a_false_empty_success(self,changes):
        with pytest.raises(CommunityCommentsError):
            parse_comments({"status":"success","response":[{**row(),**changes}]},PARENT)
    def test_only_native_ok_confirms_a_comment_without_requiring_normal_message_id(self):
        assert comment_send_confirmed(201,{"status":"success","response":{"messageSendResult":"OK"}})
        for code,result in [(200,{"messageSendResult":"OK"}),(201,{}),(201,{"messageSendResult":"ERROR_UNKNOWN"})]:
            assert not comment_send_confirmed(code,{"status":"success","response":result})
    def test_read_keeps_complete_parent_key_and_url_encodes_it(self,monkeypatch):
        get=Mock(return_value=SimpleNamespace(status_code=200,raise_for_status=Mock(),
            json=lambda:{"status":"success","response":[row()]}))
        monkeypatch.setattr("main_window.community_comments.api_get",get)
        assert API().get_announcement_comments(JID,{"key":{"id":PARENT}})[0]["parentMsgId"]==PARENT
        assert "false_123%40g.us_PARENT_456%40lid" in get.call_args.args[0]
    @pytest.mark.parametrize("result",[{}, {"status":"success","response":{"messageSendResult":"ERROR_UNKNOWN"}}])
    def test_send_calls_once_and_never_uses_normal_outbox(self,monkeypatch,result):
        post=Mock(return_value=SimpleNamespace(status_code=201,json=lambda:result))
        monkeypatch.setattr("main_window.community_comments.api_post",post)
        with pytest.raises(CommunityCommentsError,match="unconfirmed"):
            API().send_announcement_comment(JID,{"key":{"id":PARENT}}," exact text ")
        post.assert_called_once()
        assert post.call_args.kwargs["json"]=={"text":" exact text "}
    def test_timeout_does_not_resend_or_expose_private_exception(self,monkeypatch):
        post=Mock(side_effect=TimeoutError("private token/text"))
        monkeypatch.setattr("main_window.community_comments.api_post",post)
        with pytest.raises(CommunityCommentsError,match="^unconfirmed$"):
            API().send_announcement_comment(JID,{"key":{"id":PARENT}},"text")
        post.assert_called_once()
    def test_foreign_parent_refused_before_http(self,monkeypatch):
        post=Mock();monkeypatch.setattr("main_window.community_comments.api_post",post)
        with pytest.raises(CommunityCommentsError):
            API().send_announcement_comment(JID,{"key":{"id":"false_999@g.us_X_456@lid"}},"text")
        post.assert_not_called()

class TestCommentWindow:
    def test_read_failure_logs_only_a_static_code(self, caplog):
        dlg=Dialog()
        dlg._finish_refresh(None, "private token/name/text")
        assert caplog.messages == ["[community_comments] read_failed code=unavailable"]

    def test_send_failure_logs_only_a_static_code(self, caplog):
        dlg=Dialog();dlg._loaded=True
        dlg._mw.send_announcement_comment.side_effect=TimeoutError("private token/name/text")
        dlg._on_send(None);dlg.work.pop()()
        assert caplog.messages == ["[community_comments] send_failed code=unconfirmed"]
        assert dlg._text.value==" exact text " and dlg._uncertain

    def test_initial_read_is_background_and_preserves_focus(self):
        dlg=Dialog();dlg._on_refresh(None)
        dlg._mw.get_announcement_comments.assert_not_called()
        assert not dlg._list.SetFocus.called
        dlg.work.pop()()
        assert dlg._loaded and len(dlg._rows)==1
        dlg._list.Freeze.assert_called_once();dlg._list.Thaw.assert_called_once()
        dlg._list.SetFocus.assert_not_called()
    def test_selection_survives_inserted_history_and_deleted_body(self):
        dlg=Dialog();dlg._finish_refresh([row("selected",10)],None)
        dlg._list.selection=0
        dlg._finish_refresh([row("older",1),row("selected",10,"revoked")],None)
        assert dlg._list.selection==1
        assert "private text" not in dlg._list.items[1]
    @pytest.mark.parametrize("stale",["closed","account","shutdown"])
    def test_stale_completion_never_touches_widgets_or_speech(self,stale):
        dlg=Dialog();dlg._on_refresh(None)
        if stale=="closed": dlg.close_comments()
        elif stale=="account": dlg._mw.token="new"
        else: dlg._mw._shutting_down=True
        dlg.work.pop()()
        assert not dlg._loaded
        dlg._list.Freeze.assert_not_called()
        dlg._mw.speak_output.output.assert_not_called()
    def test_send_requires_successful_read_and_prevents_double_clicks(self):
        dlg=Dialog();dlg._on_send(None);assert not dlg.work
        dlg._loaded=True;dlg._on_send(None);dlg._on_send(None)
        assert len(dlg.work)==1
        dlg.work.pop()()
        dlg._mw.send_announcement_comment.assert_called_once_with(JID,dlg._message," exact text ")
        assert dlg._text.value=="" and len(dlg.work)==1  # background refresh
    def test_ambiguous_send_keeps_draft_and_is_never_resent_by_itself(self):
        dlg=Dialog();dlg._loaded=True;dlg._mw.send_announcement_comment.side_effect=TimeoutError()
        dlg._on_send(None);dlg.work.pop()()
        assert dlg._text.value==" exact text " and dlg._uncertain
        assert len(dlg.work)==1   # the thread is read again on its own, never resent
        dlg._on_send(None);assert len(dlg.work)==1
        dlg.work.pop()()
        dlg._mw.send_announcement_comment.assert_called_once()

    def _unconfirmed(self):
        dlg=Dialog();dlg._finish_refresh([row("old", 1, mine=True)], None)
        dlg._mw.send_announcement_comment.side_effect=TimeoutError()
        dlg._on_send(None);dlg.work.pop()()
        return dlg

    def test_a_read_without_the_reply_keeps_the_same_text_blocked(self):
        """The reply may still be on its way: a second Ctrl+Enter would post
        it twice to the whole community."""
        dlg=self._unconfirmed()
        dlg._mw.get_announcement_comments.return_value=[row("old", 1, mine=True)]
        dlg.work.pop()()
        assert dlg._uncertain and dlg._resend_blocked()
        assert dlg._send.Enable.call_args.args == (False,)
        dlg._on_send(None)
        assert not dlg.work
        dlg._mw.send_announcement_comment.assert_called_once()

    def test_a_read_showing_the_reply_says_it_went_and_clears_the_field(self):
        dlg=self._unconfirmed()
        dlg._mw.get_announcement_comments.return_value=[row("old", 1, mine=True),
                                                         row("new", 20, mine=True)]
        dlg.work.pop()()
        assert not dlg._uncertain and dlg._text.value==""
        assert dlg._mw.speak_output.output.call_args.args[0] == "community_comments_sent Replies: 2"

    def test_someone_elses_new_reply_proves_nothing(self):
        dlg=self._unconfirmed()
        dlg._mw.get_announcement_comments.return_value=[row("old", 1, mine=True), row("theirs", 20)]
        dlg.work.pop()()
        assert dlg._uncertain and dlg._text.value==" exact text "

    def test_a_changed_text_is_a_new_reply_and_can_go(self):
        dlg=self._unconfirmed();dlg.work.pop()()
        dlg._text.value="another reply"
        dlg._update_buttons()
        assert dlg._send.Enable.call_args.args == (True,)
        dlg._on_send(None)
        assert len(dlg.work)==1
    def test_unavailable_read_does_not_enable_sending(self):
        dlg=Dialog();dlg._finish_refresh(None,"not_announcement")
        assert not dlg._loaded
        dlg._send.Enable.assert_called_with(False)
    def test_unknown_author_is_never_displayed_as_raw_jid(self):
        dlg=Dialog();dlg._mw._resolve_jid_name.return_value="456@lid"
        assert "456@lid" not in dlg._row_label(row())


def test_native_community_comments_adapter():
    from pathlib import Path
    import shutil
    import subprocess
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node") or str(root / "client/node/node.exe")
    if not (root / "client/api/node_modules/typescript").is_dir():
        pytest.skip("Node API not installed in this checkout")
    completed = subprocess.run([node, str(root / "tests/community_comments_runtime.cjs")],
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_refresh_does_not_move_focus():
    dlg=Dialog();dlg._on_refresh(None)
    assert not dlg._text.SetFocus.called


def test_there_is_no_refresh_button():
    import inspect
    src = inspect.getsource(CommunityCommentsDialog)
    assert "community_comments_refresh" not in src and "_reload" not in src


def test_reply_field_stays_editable_while_reading_and_sending():
    dlg=Dialog();dlg._on_refresh(None)
    dlg._text.SetEditable.assert_called_with(True)
    dlg.work.pop()()
    dlg._on_send(None)
    dlg._text.SetEditable.assert_called_with(True)
    dlg._send.Enable.assert_called_with(False)
    assert {call.args[0] for call in dlg._text.SetEditable.call_args_list} == {True}


def test_text_typed_during_a_send_is_kept():
    dlg=Dialog();dlg._loaded=True;dlg._on_send(None)
    dlg._text.value=" exact text and more"
    dlg.work.pop()()
    assert dlg._text.value==" exact text and more"


def test_closed_dialog_makes_the_field_read_only():
    dlg=Dialog();dlg.close_comments();dlg._update_buttons()
    dlg._text.SetEditable.assert_called_with(False)


def test_closed_dialog_ignores_in_flight_send_completion():
    dlg=Dialog();dlg._loaded=True;dlg._on_send(None);dlg.close_comments();dlg.work.pop()()
    assert dlg._text.value==" exact text "
    dlg._mw.speak_output.output.assert_not_called()
    assert not dlg.work


def test_malformed_parent_is_refused_before_http(monkeypatch):
    post=Mock();monkeypatch.setattr("main_window.community_comments.api_post",post)
    with pytest.raises(CommunityCommentsError):
        API().send_announcement_comment(JID,{"key":{"id":"broken"}},"text")
    post.assert_not_called()


def test_ctrl_enter_sends_but_enter_keeps_multiline_editing():
    dlg=Dialog();dlg._loaded=True
    event=SimpleNamespace(ControlDown=lambda:False,GetKeyCode=lambda:wx.WXK_RETURN,Skip=Mock())
    dlg._on_text_key(event);event.Skip.assert_called_once();assert not dlg.work
    event.ControlDown=lambda:True
    dlg._on_text_key(event);assert len(dlg.work)==1


class TestReplyNamesAndCounts:
    def test_profile_name_fills_missing_local_contact(self):
        from core.community_comments import comment_author_label
        dlg=Dialog();dlg._mw._resolve_jid_name.return_value="unnamed_participant"
        assert comment_author_label({**row(),"authorName":"Profile name"},dlg._mw,JID)=="Profile name"
    def test_saved_name_has_priority_over_profile_name(self):
        from core.community_comments import comment_author_label
        dlg=Dialog();dlg._mw._resolve_jid_name.return_value="Saved contact"
        assert comment_author_label({**row(),"authorName":"Profile name"},dlg._mw,JID)=="Saved contact"
    @pytest.mark.parametrize("native_self",[True,False])
    def test_own_comment_uses_personal_self_reference(self,native_self):
        from core.community_comments import comment_author_label
        dlg=Dialog();dlg._mw._is_self_jid=lambda _jid: not native_self
        dlg._mw.self_reference_label=lambda:"Custom self label"
        assert comment_author_label({**row(),"fromMe":native_self},dlg._mw,JID)=="Custom self label"
        dlg._mw._resolve_jid_name.assert_not_called()
    def test_wire_parser_retains_name_and_own_flag(self):
        result=parse_comments({"status":"success","response":[{**row(),"authorName":"Profile name","fromMe":True}]},PARENT)
        assert result[0]["authorName"]=="Profile name" and result[0]["fromMe"] is True
    def test_count_is_normalized_and_spoken_after_the_body(self):
        from tests.test_edited_marker_survives_sync import _Normalizer
        from tests.test_forwarded_prefix_setting import _Stub as Renderer
        raw={"id":PARENT,"from":JID,"type":"chat","body":"text","timestamp":10,"replyCount":7}
        normalized=_Normalizer()._normalize_wpp_message(raw)
        assert normalized["replyCount"]==7
        panel=Renderer()
        panel._get_message_content=lambda msg: msg["message"]["conversation"]
        panel.main_window.i18n=SimpleNamespace(t=lambda key: "Replies: {count}" if key=="community_comments_count" else key)
        rendered=panel._render_message_line(normalized)
        assert ", Replies: 7" in rendered
        assert rendered.index("text") < rendered.index("Replies: 7")
        for bad in [None,True,-1,"7",float("inf")]:
            normalized=_Normalizer()._normalize_wpp_message({**raw,"replyCount":bad})
            assert "replyCount" not in normalized
            assert "Replies:" not in panel._render_message_line(normalized)
    def test_open_thread_updates_parent_count_without_changing_selection(self):
        from ui.conversation_panel.community_comments import CommunityCommentsPanelMixin
        original={"key":{"id":"parent"}}
        resident={"key":{"id":"parent"}}
        panel=SimpleNamespace(conversation={"remoteJid":JID,"messages":{"messages":{"records":[resident]}}},
            _sorted_messages=[resident],_repaint_or_repopulate=Mock())
        CommunityCommentsPanelMixin._update_announcement_reply_count(panel,JID,original,7)
        assert original["replyCount"]==resident["replyCount"]==7
        panel._repaint_or_repopulate.assert_called_once_with(["parent"])
        CommunityCommentsPanelMixin._update_announcement_reply_count(panel,JID,original,7)
        panel._repaint_or_repopulate.assert_called_once()


class TestLiveReplyCount:
    def test_event_parsing_keeps_parent_identity_and_rejects_anything_else(self):
        from core.community_comments import parse_reply_count_event
        assert parse_reply_count_event({"id": PARENT, "chatId": JID, "replyCount": 2}) == {
            "chat": JID, "parent": PARENT, "key_id": "PARENT", "count": 2}
        for bad in [None, {"id": PARENT, "chatId": "123@lid", "replyCount": 2},
                    {"id": PARENT, "chatId": JID, "replyCount": True},
                    {"id": PARENT, "chatId": JID, "replyCount": -1},
                    {"id": "false_999@g.us_X", "chatId": JID, "replyCount": 1},
                    {"id": "broken", "chatId": JID, "replyCount": 1}]:
            assert parse_reply_count_event(bad) is None

    def test_cached_announcement_gets_the_new_count(self):
        from core.community_comments import apply_reply_count
        chat = {"messages": {"messages": {"records": [{"key": {"id": "PARENT"}},
                                                      {"key": {"id": "other"}}]}}}
        assert apply_reply_count(chat, "PARENT", 3) is True
        assert chat["messages"]["messages"]["records"][0]["replyCount"] == 3
        assert "replyCount" not in chat["messages"]["messages"]["records"][1]
        assert apply_reply_count(chat, "PARENT", 3) is False
        assert apply_reply_count(None, "PARENT", 3) is False

    def test_open_window_reads_itself_again_for_its_own_announcement(self):
        dlg = Dialog(); dlg._finish_refresh([row()], None)
        dlg.on_reply_count_changed(JID, "OTHER", 2)
        assert not dlg.work
        dlg.on_reply_count_changed("999@g.us", "PARENT", 2)
        assert not dlg.work
        dlg.on_reply_count_changed(JID, "PARENT", 1)   # already showing one reply
        assert not dlg.work
        dlg.on_reply_count_changed(JID, "PARENT", 2)
        assert len(dlg.work) == 1
        dlg.work.pop()()
        dlg._list.SetFocus.assert_not_called()

    def test_event_during_a_read_is_read_after_it(self):
        dlg = Dialog(); dlg._on_refresh(None)
        dlg.on_reply_count_changed(JID, "PARENT", 5)
        assert len(dlg.work) == 1 and dlg._refresh_pending
        dlg.work.pop()()
        assert len(dlg.work) == 1 and not dlg._refresh_pending

    def test_closed_window_ignores_events_and_leaves_the_registry(self):
        dlg = Dialog(); dlg._register()
        assert dlg in dlg._mw._announcement_comment_dialogs
        dlg.close_comments()
        assert dlg not in dlg._mw._announcement_comment_dialogs
        dlg.on_reply_count_changed(JID, "PARENT", 5)
        assert not dlg.work

    def test_main_window_updates_row_cache_and_open_windows(self):
        from main_window.community_comments import CommunityCommentsMixin
        dialog = Mock()
        record = {"key": {"id": "PARENT"}}
        mw = SimpleNamespace(
            conversations_panel=SimpleNamespace(_update_announcement_reply_count=Mock()),
            chats={JID: {"messages": {"messages": {"records": [record]}}}},
            _announcement_comment_dialogs={dialog})
        CommunityCommentsMixin.on_announcement_reply_count(
            mw, {"chat": JID, "parent": PARENT, "key_id": "PARENT", "count": 4})
        args = mw.conversations_panel._update_announcement_reply_count.call_args.args
        assert args[0] == JID and args[1]["key"]["id"] == "PARENT" and args[2] == 4
        assert record["replyCount"] == 4
        dialog.on_reply_count_changed.assert_called_once_with(JID, "PARENT", 4)

    def test_the_open_window_is_found_whatever_form_the_author_part_takes(self):
        """The stored parent's author is @c.us when _phone_to_lid has no entry;
        the page sends @lid. The window still reads itself again."""
        dlg = Dialog(); dlg._finish_refresh([row()], None)
        dlg._mw._announcement_comment_dialogs = {dlg}
        dlg._mw.conversations_panel = None
        dlg._mw.chats = {}
        CommunityCommentsMixin.on_announcement_reply_count(
            dlg._mw, {"chat": JID, "parent": "false_123@g.us_PARENT_5511999999999@c.us",
                      "key_id": "PARENT", "count": 2})
        assert len(dlg.work) == 1


def test_socket_event_reaches_the_main_window_on_the_ui_thread(monkeypatch):
    from core.websocket_client import WebSocketClient
    calls = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args: calls.append((fn, args)))
    mw = SimpleNamespace(on_announcement_reply_count=Mock())
    client = SimpleNamespace(main_window=mw, _belongs_to_this_session=lambda data: True)
    WebSocketClient.on_announcement_replies(
        client, {"session": "s", "id": PARENT, "chatId": JID, "replyCount": 2})
    WebSocketClient.on_announcement_replies(client, {"session": "s", "id": "bad"})
    assert calls == [(mw.on_announcement_reply_count,
                      ({"chat": JID, "parent": PARENT, "key_id": "PARENT", "count": 2},))]


def test_announcement_reply_bridge_runtime():
    from pathlib import Path
    import shutil
    import subprocess
    root = Path(__file__).resolve().parents[1]
    node = shutil.which("node") or str(root / "client/node/node.exe")
    if not (root / "client/api/node_modules/typescript").is_dir():
        pytest.skip("Node API not installed in this checkout")
    completed = subprocess.run([node, str(root / "tests/announcement_reply_bridge_runtime.cjs")],
                               capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


class TestOnlyAnnouncementGroupsOfferReplies:
    """Reported: the menu of an ordinary group offered "replies to the
    announcement". The flag comes from /group-info, asked when a group opens."""

    def test_group_info_records_the_kind_on_the_chat(self):
        from main_window.groups import GroupsMixin
        window = SimpleNamespace(chats={JID: {"remoteJid": JID}, "2@g.us": {"remoteJid": "2@g.us",
                                 "groupMetadata": {"subject": "Family"}}})
        GroupsMixin._remember_group_kind(window, JID, {"defaultSubgroup": True})
        GroupsMixin._remember_group_kind(window, "2@g.us", {"defaultSubgroup": False})
        GroupsMixin._remember_group_kind(window, "9@g.us", {"defaultSubgroup": True})  # unknown chat
        assert window.chats[JID]["groupMetadata"] == {"defaultSubgroup": True}
        assert window.chats["2@g.us"]["groupMetadata"] == {"subject": "Family",
                                                           "defaultSubgroup": False}
        assert "9@g.us" not in window.chats

    def test_an_answer_without_the_flag_changes_nothing(self):
        from main_window.groups import GroupsMixin
        window = SimpleNamespace(chats={JID: {"remoteJid": JID}})
        GroupsMixin._remember_group_kind(window, JID, {"name": "x"})
        assert "groupMetadata" not in window.chats[JID]

    def test_the_panel_reads_the_flag_from_the_list_copy_of_the_chat(self):
        from ui.conversation_panel.community_comments import CommunityCommentsPanelMixin
        msg = {"key": {"id": "parent"}}
        known = {"remoteJid": JID, "groupMetadata": {"defaultSubgroup": True}}
        panel = SimpleNamespace(conversation={"remoteJid": JID},
                                main_window=SimpleNamespace(chats={JID: known}))
        assert CommunityCommentsPanelMixin._can_open_announcement_comments(panel, msg)
        panel.main_window.chats = {JID: {"remoteJid": JID}}
        assert not CommunityCommentsPanelMixin._can_open_announcement_comments(panel, msg)

    def test_both_engines_state_the_kind_in_group_info(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parents[1]
        wpp = (root / "client" / "api_patches" / "src" / "controller"
               / "groupOperationsController.ts").read_text(encoding="utf-8")
        bridge = (root / "neonize_bridge" / "server.py").read_text(encoding="utf-8")
        assert "defaultSubgroup: meta.defaultSubgroup === true" in wpp
        assert '"defaultSubgroup": bool(g.GroupIsDefaultSub.IsDefaultSubGroup)' in bridge
