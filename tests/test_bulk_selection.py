"""Tests for the bulk-selection helpers backing "Ações em massa":

- append_selected_marker() (core/utils.py): the pure "selecionado" marker
  logic shared by the messages list and the conversations list rows.
- ConversationsPanel._select_message_at / _all_selectable_message_ids /
  _select_chat_at / _all_chat_jids / _bulk_shortcuts_enabled: the selection
  bookkeeping used by Ctrl+Space, Shift+Down, Shift+Home/End, Ctrl+Shift+Space
  and the shortcut-to-bulk-action redirect.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so these methods are bound onto a plain stub carrying only the
attributes they touch — same pattern as tests/test_message_bookmarks.py.
"""

from core.utils import append_selected_marker
from ui.conversations import ConversationsPanel


class TestAppendSelectedMarker:
    def test_not_selected_returns_text_unchanged(self):
        assert append_selected_marker("João: oi", "selecionado", "end", False) == "João: oi"

    def test_selected_appends_at_end_by_default(self):
        assert append_selected_marker("João: oi", "selecionado", "end", True) == "João: oi selecionado"

    def test_selected_prepends_at_start(self):
        assert append_selected_marker("João: oi", "selecionado", "start", True) == "selecionado João: oi"

    def test_unknown_position_falls_back_to_end(self):
        assert append_selected_marker("x", "selecionado", "", True) == "x selecionado"


class _FakeMainWindow:
    def __init__(self, ui_settings=None):
        self.settings = {"user_interface": dict(ui_settings or {})}
        self.i18n = self
        self.outputs = []

    def t(self, key):
        return key

    def output(self, text, interrupt=False):
        self.outputs.append(text)


def _msg(msg_id, separator=False):
    if separator:
        return {"_type": "unread_separator", "count": 1}
    return {"key": {"id": msg_id}}


class _Stub:
    """Minimal stand-in for ConversationsPanel."""

    _is_separator = ConversationsPanel._is_separator
    _select_message_at = ConversationsPanel._select_message_at
    _all_selectable_message_ids = ConversationsPanel._all_selectable_message_ids
    _select_chat_at = ConversationsPanel._select_chat_at
    _all_chat_jids = ConversationsPanel._all_chat_jids
    _bulk_shortcuts_enabled = ConversationsPanel._bulk_shortcuts_enabled

    def __init__(self, sorted_messages=None, chats_list=None, ui_settings=None):
        self._sorted_messages = sorted_messages or []
        self.chats_list = chats_list or []
        self.selected_messages = set()
        self.selected_chats = set()
        self.main_window = _FakeMainWindow(ui_settings)


class TestSelectMessageAt:
    def test_selects_real_message(self):
        stub = _Stub(sorted_messages=[_msg("A1"), _msg("A2")])
        assert stub._select_message_at(0) is True
        assert stub.selected_messages == {"A1"}

    def test_skips_separator_rows(self):
        stub = _Stub(sorted_messages=[_msg("A1"), _msg("SEP", separator=True)])
        assert stub._select_message_at(1) is False
        assert stub.selected_messages == set()

    def test_out_of_range_index_is_a_noop(self):
        stub = _Stub(sorted_messages=[_msg("A1")])
        assert stub._select_message_at(5) is False
        assert stub.selected_messages == set()

    def test_already_selected_returns_false(self):
        stub = _Stub(sorted_messages=[_msg("A1")])
        stub.selected_messages.add("A1")
        assert stub._select_message_at(0) is False


class TestAllSelectableMessageIds:
    def test_excludes_separators_and_ids_without_key(self):
        stub = _Stub(sorted_messages=[_msg("A1"), _msg("SEP", separator=True), _msg("A2")])
        assert stub._all_selectable_message_ids() == ["A1", "A2"]


def _chat(jid):
    return {"remoteJid": jid}


class TestSelectChatAt:
    def test_selects_chat_by_index(self):
        stub = _Stub(chats_list=[_chat("a@s.whatsapp.net"), _chat("b@s.whatsapp.net")])
        assert stub._select_chat_at(1) is True
        assert stub.selected_chats == {"b@s.whatsapp.net"}

    def test_out_of_range_index_is_a_noop(self):
        stub = _Stub(chats_list=[_chat("a@s.whatsapp.net")])
        assert stub._select_chat_at(3) is False

    def test_already_selected_returns_false(self):
        stub = _Stub(chats_list=[_chat("a@s.whatsapp.net")])
        stub.selected_chats.add("a@s.whatsapp.net")
        assert stub._select_chat_at(0) is False


class TestAllChatJids:
    def test_lists_every_chat_jid(self):
        stub = _Stub(chats_list=[_chat("a@s.whatsapp.net"), _chat("b@s.whatsapp.net")])
        assert stub._all_chat_jids() == ["a@s.whatsapp.net", "b@s.whatsapp.net"]


class TestBulkShortcutsEnabled:
    def test_defaults_to_enabled(self):
        stub = _Stub()
        assert stub._bulk_shortcuts_enabled() is True

    def test_respects_disabled_setting(self):
        stub = _Stub(ui_settings={"bulk_action_shortcuts": False})
        assert stub._bulk_shortcuts_enabled() is False
