"""Deleting one of the account's own statuses, for everyone who received it.

What WhatsApp Web's "Delete" in the status player does (statusDeleteController.ts
does it on the Node side); here the client call, the My status dialog's button
and Delete key, and the Status tab redrawn after it. No window is opened: the
dialog's methods run on a plain stub.
"""

import inspect
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from core import status_delete
from core.shortcut_catalog import SHORTCUTS
from main_window.chats_store import ChatsStoreMixin
from status_tab import status_dialogs
from status_tab.my_status_transcription import MyStatusTranscriptionKeys
from status_tab.status_dialogs import MyStatusDialog

CONNECTION = ("http://localhost", 6300, "token")


def _status(msg_id):
    return {"key": {"id": msg_id, "fromMe": True}, "messageType": "conversation",
            "message": {"conversation": "text"}}


class TestTheCall:
    def test_one_post_to_the_route(self, monkeypatch):
        post = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"status": "success"}))
        monkeypatch.setattr(status_delete, "api_post", post)
        assert status_delete.delete_own_status(CONNECTION, "3EB0ABC") is None
        post.assert_called_once()
        assert post.call_args.args[0] == "http://localhost:6300/api/token/status/3EB0ABC/delete"

    @pytest.mark.parametrize("reply, code", [
        (SimpleNamespace(status_code=404, json=lambda: {"status": "error", "code": "not_found"}), "not_found"),
        (SimpleNamespace(status_code=502, json=lambda: {}), "unavailable"),
    ])
    def test_a_failure_is_its_code_and_never_retried(self, monkeypatch, reply, code):
        post = Mock(return_value=reply)
        monkeypatch.setattr(status_delete, "api_post", post)
        with pytest.raises(ValueError, match=code):
            status_delete.delete_own_status(CONNECTION, "3EB0ABC")
        post.assert_called_once()

    def test_a_serialized_key_id_is_sent_as_its_id(self, monkeypatch):
        """The route refuses anything but the id part (invalid_request)."""
        post = Mock(return_value=SimpleNamespace(status_code=200, json=lambda: {"status": "success"}))
        monkeypatch.setattr(status_delete, "api_post", post)
        status_delete.delete_own_status(CONNECTION, "true_status@broadcast_3EB0ABC_5511@c.us")
        assert post.call_args.args[0].endswith("/status/3EB0ABC/delete")

    @pytest.mark.parametrize("value, plain", [
        ("3EB0ABC", "3EB0ABC"),
        ("true_status@broadcast_3EB0ABC", "3EB0ABC"),
        ("false_status@broadcast_3EB0ABC_456@lid", "3EB0ABC"),
        ("weird_id_here", "weird_id_here"),
        (None, None),
    ])
    def test_plain_key_id(self, value, plain):
        assert status_delete.plain_key_id(value) == plain

    def test_a_timeout_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(status_delete, "api_post", Mock(side_effect=TimeoutError("private")))
        with pytest.raises(ValueError, match="^unavailable$"):
            status_delete.delete_own_status(CONNECTION, "3EB0ABC")


class _Dialog:
    _own_status = MyStatusTranscriptionKeys._own_status
    _on_delete_status = MyStatusDialog._on_delete_status
    _finish_delete_status = MyStatusDialog._finish_delete_status
    _drop_status = MyStatusDialog._drop_status

    def __init__(self, ids, current=0):
        self._statuses = [_status(i) for i in ids]
        self._current = current
        self._deleting = False
        self.deleted_status_ids = []
        self._mw = SimpleNamespace(i18n=SimpleNamespace(t=lambda key: key), output=Mock(),
                                   wpp_server="http://localhost", wpp_port=6300, token="token",
                                   db=SimpleNamespace(delete_status_update=Mock()))
        self._update_content = Mock()
        self._cleanup = Mock()
        self.EndModal = Mock()

    def __bool__(self):
        return True


@pytest.fixture
def run_inline(monkeypatch):
    """The worker thread and CallAfter run where they are called."""
    class _Thread:
        def __init__(self, target, daemon=True):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(status_dialogs.threading, "Thread", _Thread)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args: fn(*args))


def _answer(monkeypatch, answer):
    box = Mock(return_value=answer)
    monkeypatch.setattr(wx, "MessageBox", box)
    return box


class TestTheDialog:
    def test_nothing_is_sent_without_a_yes(self, monkeypatch, run_inline):
        _answer(monkeypatch, wx.NO)
        sent = Mock()
        monkeypatch.setattr(status_dialogs, "delete_own_status", sent)
        dialog = _Dialog(["A", "B"])
        dialog._on_delete_status()
        sent.assert_not_called()
        assert len(dialog._statuses) == 2

    def test_the_shown_status_is_deleted_and_the_next_one_said(self, monkeypatch, run_inline):
        box = _answer(monkeypatch, wx.YES)
        sent = Mock()
        monkeypatch.setattr(status_dialogs, "delete_own_status", sent)
        dialog = _Dialog(["A", "B", "C"], current=2)
        dialog._on_delete_status()
        assert box.call_args.args[0] == "status_delete_confirm"
        sent.assert_called_once_with(("http://localhost", 6300, "token"), "C")
        assert [s["key"]["id"] for s in dialog._statuses] == ["A", "B"]
        assert dialog._current == 1
        dialog._update_content.assert_called_once_with(said_first="status_deleted")
        dialog._mw.db.delete_status_update.assert_called_once_with("C")
        assert dialog.deleted_status_ids == ["C"]

    def test_the_deleted_status_leaves_the_in_memory_statuses_too(self, monkeypatch, run_inline):
        """_load_statuses merges MainWindow._status_updates back in: left
        there, the deleted status came back with the status API down."""
        _answer(monkeypatch, wx.YES)
        monkeypatch.setattr(status_dialogs, "delete_own_status", Mock())
        dialog = _Dialog(["A", "B"], current=1)
        mine = "me@s.whatsapp.net"
        dialog._mw._status_updates = {mine: [_status("A"), _status("B")]}
        dialog._mw.remove_failed_status_update = (
            lambda message_id, refresh=True: ChatsStoreMixin.remove_failed_status_update(
                dialog._mw, message_id, refresh=refresh))
        dialog._on_delete_status()
        assert [s["key"]["id"] for s in dialog._mw._status_updates[mine]] == ["A"]
        dialog._mw.db.delete_status_update.assert_called_once_with("B")

    def test_the_tab_is_not_reloaded_twice(self, monkeypatch, run_inline):
        _answer(monkeypatch, wx.YES)
        monkeypatch.setattr(status_dialogs, "delete_own_status", Mock())
        dialog = _Dialog(["A", "B"])
        dialog._mw.remove_failed_status_update = Mock()
        dialog._on_delete_status()
        dialog._mw.remove_failed_status_update.assert_called_once_with("A", refresh=False)

    def test_the_last_status_deleted_closes_the_dialog(self, monkeypatch, run_inline):
        _answer(monkeypatch, wx.YES)
        monkeypatch.setattr(status_dialogs, "delete_own_status", Mock())
        dialog = _Dialog(["A"])
        dialog._on_delete_status()
        assert dialog._statuses == []
        dialog.EndModal.assert_called_once_with(wx.ID_CANCEL)
        assert dialog._mw.output.call_args.args[0] == "status_deleted"

    def test_a_status_already_gone_leaves_the_list_too(self, monkeypatch, run_inline):
        _answer(monkeypatch, wx.YES)
        monkeypatch.setattr(status_dialogs, "delete_own_status",
                            Mock(side_effect=ValueError(status_delete.NOT_FOUND)))
        dialog = _Dialog(["A", "B"])
        dialog._on_delete_status()
        assert [s["key"]["id"] for s in dialog._statuses] == ["B"]
        dialog._update_content.assert_called_once_with(said_first="status_delete_not_found")

    def test_a_failure_keeps_the_status_and_says_so(self, monkeypatch, run_inline, caplog):
        _answer(monkeypatch, wx.YES)
        monkeypatch.setattr(status_dialogs, "delete_own_status",
                            Mock(side_effect=ValueError("delete_unconfirmed")))
        dialog = _Dialog(["A", "B"])
        dialog._on_delete_status()
        assert len(dialog._statuses) == 2 and not dialog._deleting
        assert dialog._mw.output.call_args.args[0] == "status_delete_failed"
        dialog._mw.db.delete_status_update.assert_not_called()
        assert caplog.messages == ["[status] delete_failed code=delete_unconfirmed"]

    def test_a_second_press_while_deleting_does_nothing(self, monkeypatch):
        box = _answer(monkeypatch, wx.YES)
        dialog = _Dialog(["A"])
        dialog._deleting = True
        dialog._on_delete_status()
        box.assert_not_called()


class TestTheKey:
    def test_delete_is_catalogued_for_the_status_scope(self):
        [shortcut] = [s for s in SHORTCUTS if s.id == "status.ID_DELETE"]
        assert (shortcut.scope, shortcut.command, shortcut.mod, shortcut.key) == \
            ("status", "ID_DELETE", 0, wx.WXK_DELETE)

    def test_the_dialog_puts_delete_in_its_one_accelerator_table(self):
        source = inspect.getsource(MyStatusDialog._init_ui)
        assert "(wx.ACCEL_NORMAL, wx.WXK_DELETE, self.ID_DELETE)" in source
        assert "self._on_delete_status, id=self.ID_DELETE" in source
        assert "AccessibleStatusDelete" in source

    def test_the_dialogs_extra_keys_join_the_transcription_ones(self, monkeypatch):
        """A window has one accelerator table: Delete must go into the same
        one as the transcription keys, or one table replaces the other."""
        from status_tab import my_status_transcription
        tables = []
        monkeypatch.setattr(my_status_transcription, "make_shortcut_table",
                            lambda window, scope, entries: (scope, list(entries)))

        class _Keys:
            _create_transcription_accelerators = \
                MyStatusTranscriptionKeys._create_transcription_accelerators
            SetAcceleratorTable = tables.append
            Bind = Mock()
            _on_transcribe_own_status = _on_transcribe_own_status_inline = Mock()
            _on_delete_own_status_transcription = Mock()

        delete = (wx.ACCEL_NORMAL, wx.WXK_DELETE, 4242)
        _Keys()._create_transcription_accelerators(extra=[delete])
        [(scope, entries)] = tables
        assert scope == "status" and len(entries) == 4
        assert entries[-1] == delete
        assert (wx.ACCEL_ALT | wx.ACCEL_SHIFT, ord("T")) == entries[0][:2]


def test_the_status_tab_redraws_after_a_deletion(monkeypatch):
    from status_tab.status_viewer import StatusViewerMixin

    class _FakeDialog:
        RC_ADD_STATUS = 1

        def __init__(self, main_window, statuses):
            statuses.pop()
            self.deleted_status_ids = ["B"]

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass

    monkeypatch.setattr("status_tab.status_viewer.MyStatusDialog", _FakeDialog)
    panel = SimpleNamespace(main_window=None, _my_statuses=[_status("A"), _status("B")],
                            _status_contacts=[], _populate_list=Mock(), _on_add_status=Mock())
    StatusViewerMixin._open_my_status_dialog(panel)
    panel._populate_list.assert_called_once_with(panel._my_statuses, [])
    assert len(panel._my_statuses) == 1
