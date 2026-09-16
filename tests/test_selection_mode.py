"""Tests for the persistent "selection mode" (issue #99).

Once a first selection exists on a surface — the messages list, the
conversations list or the forward dialog's contact list — plain Space keeps
selecting/deselecting instead of doing its normal job, and stops doing so the
moment the selection goes empty again. The mode is *derived* from the
selection set being non-empty (plus the setting), never stored in a flag, so
it cannot drift away from the set the mass actions clear behind it.

Also covered here: Esc clearing an active message selection before it closes
the conversation, and the unconditional bug fix that stops a selection leaking
into the next conversation (which ignores both settings on purpose).

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are bound onto plain stubs carrying only the
attributes each one touches — same pattern as tests/test_bulk_selection.py and
tests/test_message_bookmarks.py.
"""

import ast
from pathlib import Path
from unittest.mock import Mock

import wx

from ui.conversations import ConversationsPanel

ROOT = Path(__file__).resolve().parents[1]


class _FakeI18n:
    """The real pt-BR values for the keys these paths announce."""

    _STRINGS = {
        "selected": "Selecionado",
        "unselected": "Desmarcado",
        "all_selected": "Tudo selecionado",
        "all_unselected": "Tudo desmarcado",
        "selection_mode_on": "Modo de seleção ativado",
        "selection_mode_off": "Modo de seleção desativado",
    }

    def t(self, key):
        return self._STRINGS[key]


class _FakeMainWindow:
    def __init__(self, ui_settings=None):
        self.settings = {"user_interface": dict(ui_settings or {})}
        self.i18n = _FakeI18n()
        self.outputs = []
        self.add_chats_to_ui = Mock()

    def output(self, text, interrupt=False):
        self.outputs.append(text)


class _FakeList:
    """Just enough wx.ListCtrl for the two key handlers."""

    def __init__(self, focused=0, count=0):
        self._focused = focused
        self._count = count

    def GetFocusedItem(self):
        return self._focused

    def GetItemCount(self):
        return self._count

    def Focus(self, idx):
        self._focused = idx

    def Select(self, idx, on=True):
        pass

    def EnsureVisible(self, idx):
        pass


def _key_event(key, ctrl=False, shift=False):
    event = Mock()
    event.GetKeyCode.return_value = key
    event.ControlDown.return_value = ctrl
    event.ShiftDown.return_value = shift
    return event


def _msg(msg_id, msg_type="conversation", **message):
    return {
        "key": {"id": msg_id},
        "messageType": msg_type,
        "message": {msg_type: dict(message)} if message else {},
    }


def _separator():
    return {"_type": "unread_separator", "count": 1}


class _Stub:
    """Minimal stand-in for ConversationsPanel."""

    _is_separator = ConversationsPanel._is_separator
    _selection_mode_enabled = ConversationsPanel._selection_mode_enabled
    _escape_clears_selection_enabled = ConversationsPanel._escape_clears_selection_enabled
    _selection_mode_announcement = ConversationsPanel._selection_mode_announcement
    _toggle_message_selection = ConversationsPanel._toggle_message_selection
    _space_toggles_playback = ConversationsPanel._space_toggles_playback
    _toggle_chat_selection = ConversationsPanel._toggle_chat_selection
    _select_message_at = ConversationsPanel._select_message_at
    _all_selectable_message_ids = ConversationsPanel._all_selectable_message_ids
    _on_messages_list_key_down = ConversationsPanel._on_messages_list_key_down
    _on_conv_list_key_down = ConversationsPanel._on_conv_list_key_down
    _on_escape_conversation = ConversationsPanel._on_escape_conversation

    def __init__(self, sorted_messages=None, chats_list=None, ui_settings=None,
                 focused=0, video_viewer_dialog=False):
        self._sorted_messages = sorted_messages or []
        self.chats_list = chats_list or []
        self.selected_messages = set()
        self.selected_chats = set()
        self.main_window = _FakeMainWindow(ui_settings)
        self.messages_list = _FakeList(focused, len(self._sorted_messages))
        self.conversations_list = _FakeList(focused, len(self.chats_list))
        self.selection_sound = Mock()
        self._is_loading_more = False
        self._messages_offset = 0
        self._refresh_message_rows_by_ids = Mock()
        self._toggle_audio_message_playback = Mock()
        self._play_toggle_video_message = Mock()
        self._paste_from_messages_list = Mock(return_value=False)
        self._use_conversation_video_media_viewer_dialog = Mock(
            return_value=video_viewer_dialog)
        self.close_conversation = Mock()
        self._page_jump_size = Mock(return_value=15)


class TestSettingReaders:
    def test_space_selects_defaults_to_enabled(self):
        assert _Stub()._selection_mode_enabled() is True

    def test_space_selects_can_be_turned_off(self):
        stub = _Stub(ui_settings={"space_selects_in_selection_mode": False})
        assert stub._selection_mode_enabled() is False

    def test_escape_clears_defaults_to_enabled(self):
        assert _Stub()._escape_clears_selection_enabled() is True

    def test_escape_clears_can_be_turned_off(self):
        stub = _Stub(ui_settings={"escape_clears_selection": False})
        assert stub._escape_clears_selection_enabled() is False


class TestSelectionModeAnnouncement:
    def test_empty_to_non_empty_announces_the_mode_turning_on(self):
        stub = _Stub()
        assert stub._selection_mode_announcement("Selecionado", False, True) == (
            "Selecionado. Modo de seleção ativado"
        )

    def test_non_empty_to_empty_announces_the_mode_turning_off(self):
        stub = _Stub()
        assert stub._selection_mode_announcement("Tudo desmarcado", True, False) == (
            "Tudo desmarcado. Modo de seleção desativado"
        )

    def test_no_transition_leaves_the_base_text_alone(self):
        stub = _Stub()
        assert stub._selection_mode_announcement("Selecionado", True, True) == "Selecionado"
        assert stub._selection_mode_announcement("Desmarcado", False, False) == "Desmarcado"

    def test_setting_off_leaves_the_base_text_alone(self):
        stub = _Stub(ui_settings={"space_selects_in_selection_mode": False})
        assert stub._selection_mode_announcement("Selecionado", False, True) == "Selecionado"


class TestMessagesListPlainSpace:
    def test_with_no_selection_it_plays_the_focused_audio(self):
        stub = _Stub(sorted_messages=[_msg("A1", "audioMessage", seconds=7)])

        stub._on_messages_list_key_down(_key_event(wx.WXK_SPACE))

        stub._toggle_audio_message_playback.assert_called_once_with(
            stub._sorted_messages[0])
        assert stub.selected_messages == set()

    def test_with_a_selection_it_toggles_instead_of_playing(self):
        stub = _Stub(sorted_messages=[_msg("A1", "audioMessage", seconds=7),
                                      _msg("A2", "audioMessage", seconds=3)],
                     focused=1)
        stub.selected_messages.add("A1")

        stub._on_messages_list_key_down(_key_event(wx.WXK_SPACE))

        assert stub.selected_messages == {"A1", "A2"}
        stub._toggle_audio_message_playback.assert_not_called()

    def test_deselecting_the_last_one_ends_the_mode_out_loud(self):
        stub = _Stub(sorted_messages=[_msg("A1", "audioMessage", seconds=7)])
        stub.selected_messages.add("A1")

        stub._on_messages_list_key_down(_key_event(wx.WXK_SPACE))

        assert stub.selected_messages == set()
        assert stub.main_window.outputs == ["Desmarcado. Modo de seleção desativado"]

    def test_setting_off_keeps_space_on_playback_even_with_a_selection(self):
        stub = _Stub(sorted_messages=[_msg("A1", "audioMessage", seconds=7)],
                     ui_settings={"space_selects_in_selection_mode": False})
        stub.selected_messages.add("A1")

        stub._on_messages_list_key_down(_key_event(wx.WXK_SPACE))

        stub._toggle_audio_message_playback.assert_called_once()
        assert stub.selected_messages == {"A1"}

    def test_non_playable_message_with_no_selection_skips_the_key(self):
        stub = _Stub(sorted_messages=[_msg("A1", "conversation")])
        event = _key_event(wx.WXK_SPACE)

        stub._on_messages_list_key_down(event)

        event.Skip.assert_called_once()
        assert stub.selected_messages == set()

    def test_ctrl_space_still_toggles_with_nothing_selected(self):
        stub = _Stub(sorted_messages=[_msg("A1", "audioMessage", seconds=7)])

        stub._on_messages_list_key_down(_key_event(wx.WXK_SPACE, ctrl=True))

        assert stub.selected_messages == {"A1"}
        assert stub.main_window.outputs == ["Selecionado. Modo de seleção ativado"]


class TestSpaceTogglesPlayback:
    """Space stays strictly narrower than Enter — it never opens a window."""

    def test_separator_row_is_not_playable(self):
        stub = _Stub()
        assert stub._space_toggles_playback(_separator()) is False

    def test_audio_is_played(self):
        stub = _Stub()
        msg = _msg("A1", "audioMessage", seconds=4)
        assert stub._space_toggles_playback(msg) is True
        stub._toggle_audio_message_playback.assert_called_once_with(msg)

    def test_classic_mode_video_is_played(self):
        stub = _Stub()
        msg = _msg("V1", "videoMessage", seconds=10)
        assert stub._space_toggles_playback(msg) is True
        stub._play_toggle_video_message.assert_called_once_with(msg)

    def test_gif_has_no_audio_track_so_space_does_nothing(self):
        stub = _Stub()
        msg = _msg("V1", "videoMessage", gifPlayback=True)
        assert stub._space_toggles_playback(msg) is False
        stub._play_toggle_video_message.assert_not_called()

    def test_video_in_media_viewer_mode_is_left_to_enter(self):
        stub = _Stub(video_viewer_dialog=True)
        msg = _msg("V1", "videoMessage", seconds=10)
        assert stub._space_toggles_playback(msg) is False
        stub._play_toggle_video_message.assert_not_called()

    def test_documents_images_contacts_and_text_never_open_from_space(self):
        stub = _Stub()
        for msg_type in ("documentMessage", "imageMessage", "contactMessage",
                         "locationMessage", "conversation", "extendedTextMessage"):
            assert stub._space_toggles_playback(_msg("X", msg_type)) is False


class TestConversationsListPlainSpace:
    def test_with_a_selection_it_selects_the_focused_chat(self):
        stub = _Stub(chats_list=[{"remoteJid": "a@s.whatsapp.net"},
                                 {"remoteJid": "b@s.whatsapp.net"}],
                     focused=1)
        stub.selected_chats.add("a@s.whatsapp.net")
        event = _key_event(wx.WXK_SPACE)

        stub._on_conv_list_key_down(event)

        assert stub.selected_chats == {"a@s.whatsapp.net", "b@s.whatsapp.net"}
        event.Skip.assert_not_called()

    def test_with_no_selection_it_keeps_falling_through(self):
        stub = _Stub(chats_list=[{"remoteJid": "a@s.whatsapp.net"}])
        event = _key_event(wx.WXK_SPACE)

        stub._on_conv_list_key_down(event)

        assert stub.selected_chats == set()
        event.Skip.assert_called_once()

    def test_setting_off_keeps_falling_through_even_with_a_selection(self):
        stub = _Stub(chats_list=[{"remoteJid": "a@s.whatsapp.net"},
                                 {"remoteJid": "b@s.whatsapp.net"}],
                     focused=1,
                     ui_settings={"space_selects_in_selection_mode": False})
        stub.selected_chats.add("a@s.whatsapp.net")
        event = _key_event(wx.WXK_SPACE)

        stub._on_conv_list_key_down(event)

        assert stub.selected_chats == {"a@s.whatsapp.net"}
        event.Skip.assert_called_once()

    def test_ctrl_space_goes_through_the_same_toggle(self):
        stub = _Stub(chats_list=[{"remoteJid": "a@s.whatsapp.net"}])

        stub._on_conv_list_key_down(_key_event(wx.WXK_SPACE, ctrl=True))

        assert stub.selected_chats == {"a@s.whatsapp.net"}
        stub.main_window.add_chats_to_ui.assert_called_once()
        assert stub.main_window.outputs == ["Selecionado. Modo de seleção ativado"]


class TestEscape:
    def test_first_escape_clears_the_selection_instead_of_closing(self):
        stub = _Stub(sorted_messages=[_msg("A1")])
        stub.selected_messages.add("A1")

        stub._on_escape_conversation(None)

        assert stub.selected_messages == set()
        stub.close_conversation.assert_not_called()
        stub._refresh_message_rows_by_ids.assert_called_once_with(["A1"])
        assert stub.main_window.outputs == ["Tudo desmarcado. Modo de seleção desativado"]

    def test_second_escape_closes_the_conversation(self):
        stub = _Stub(sorted_messages=[_msg("A1")])
        stub.selected_messages.add("A1")

        stub._on_escape_conversation(None)
        stub._on_escape_conversation(None)

        stub.close_conversation.assert_called_once()

    def test_setting_off_closes_immediately_even_with_a_selection(self):
        stub = _Stub(sorted_messages=[_msg("A1")],
                     ui_settings={"escape_clears_selection": False})
        stub.selected_messages.add("A1")

        stub._on_escape_conversation(None)

        stub.close_conversation.assert_called_once()
        assert stub.selected_messages == {"A1"}

    def test_the_mention_popup_still_wins_the_first_escape(self):
        # It is an overlay right in front of the user, and the close path
        # already answers Esc by just dismissing it.
        stub = _Stub(sorted_messages=[_msg("A1")])
        stub.selected_messages.add("A1")
        stub._mention_panel = Mock()
        stub._mention_panel.IsShown.return_value = True

        stub._on_escape_conversation(None)

        stub.close_conversation.assert_called_once()
        assert stub.selected_messages == {"A1"}

    def test_a_chat_selection_does_not_change_what_escape_does(self):
        # Scoped to the message selection: Esc inside a conversation must not
        # start answering to what is selected in the chat list behind it.
        stub = _Stub()
        stub.selected_chats.add("a@s.whatsapp.net")

        stub._on_escape_conversation(None)

        stub.close_conversation.assert_called_once()
        assert stub.selected_chats == {"a@s.whatsapp.net"}


def _method_source(class_name: str, method_name: str) -> str:
    path = ROOT / "client" / "ui" / "conversations.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{class_name}.{method_name} not found")


class TestSelectionDoesNotSurviveTheConversation:
    """Unconditional — a user who unticked the Esc option would otherwise
    still reopen a conversation with its old rows still selected."""

    def test_closing_clears_the_message_selection(self):
        from tests.test_close_conversation_for_panel_switch import _Stub as _CloseStub

        stub = _CloseStub({"remoteJid": "5511999999999@s.whatsapp.net"})
        stub.selected_messages = {"A1", "A2"}

        stub.close_conversation_for_panel_switch()

        assert stub.selected_messages == set()

    def test_switching_straight_to_another_chat_clears_it_too(self):
        # navigate_to_conversation() starts threads and drives real widgets, so
        # it cannot be bound onto a stub — the clear is pinned at the source
        # seam instead, the same way test_media_transfer_progress_wiring.py
        # pins _hide_media_transfer_gauge() in this very method.
        assert "self.selected_messages.clear()" in _method_source(
            "ConversationsPanel", "navigate_to_conversation")

    def test_the_close_path_carries_the_same_clear(self):
        assert "self.selected_messages.clear()" in _method_source(
            "ConversationsPanel", "_close_conversation_core")
