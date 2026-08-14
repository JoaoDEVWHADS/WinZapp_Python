"""Tests for temporary message bookmarks (Alt+Shift+0..9 / Ctrl+Alt+Shift+0..9).

The ten permanent bookmarks (Ctrl+0..9, tests/test_message_bookmarks.py) span
conversations and survive closing one — which makes them the wrong tool for
"hold my place while I scroll off to check something", since that would spend a
slot the user is keeping for a message that matters. Temporary bookmarks are
the scratch set for exactly that: scoped to the conversation currently open and
cleared the moment it is left (that clearing is covered in
tests/test_close_conversation_for_panel_switch.py, which drives the real
_close_conversation_core()).

Alt+Shift+<digit> sets one on the focused message, or jumps to it when that
digit already holds one. Ctrl+Alt+Shift+<digit> removes it. Like the permanent
ones they key off the message id, not a list index, so they keep pointing at
the right message across a list rebuild.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against a
small stub carrying just the attributes they touch — same approach as
tests/test_message_bookmarks.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeI18n:
    """The real pt-BR templates for the keys these methods use."""

    _STRINGS = {
        "temp_bookmark_set": "Posicionado marcador temporário {digit} no elemento {position}: {text}",
        "temp_bookmark_jumped": "Movido para a posição {position} da lista (marcador temporário {digit})",
        "temp_bookmark_removed": "Removido marcador temporário {digit} na posição {position}",
        "temp_bookmark_removed_stale": "Removido marcador temporário {digit} (a mensagem original não está mais na lista)",
        "temp_bookmark_not_found": "Nenhum marcador temporário encontrado para o número {digit}",
    }

    def t(self, key):
        return self._STRINGS[key]


class _FakeMessagesList:
    def __init__(self, focused_item=-1):
        self._focused_item = focused_item
        self.focused_calls = []
        self.selected_calls = []
        self.ensure_visible_calls = []
        self.set_focus_called = False

    def GetFocusedItem(self):
        return self._focused_item

    def Focus(self, idx):
        self._focused_item = idx
        self.focused_calls.append(idx)

    def Select(self, idx, on=True):
        self.selected_calls.append((idx, on))

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)

    def SetFocus(self):
        self.set_focus_called = True

    def GetItemText(self, idx):
        return f"item-{idx}"


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.outputs = []

    def output(self, text, interrupt=False):
        self.outputs.append(text)


CONV = "a@s.whatsapp.net"


class _Stub:
    """Minimal stand-in for ConversationsPanel."""

    _is_separator = ConversationsPanel._is_separator
    _find_index_by_msg_id = ConversationsPanel._find_index_by_msg_id
    _focus_message_row = ConversationsPanel._focus_message_row
    _on_temp_bookmark_set_or_jump = ConversationsPanel._on_temp_bookmark_set_or_jump
    _on_temp_bookmark_remove = ConversationsPanel._on_temp_bookmark_remove

    def __init__(self, sorted_messages, focused_item=-1, conversation_jid=CONV):
        self._msg_temp_bookmarks = {}
        self._sorted_messages = sorted_messages
        self.messages_list = _FakeMessagesList(focused_item)
        self.main_window = _FakeMainWindow()
        self.conversation = {"remoteJid": conversation_jid} if conversation_jid else None


def _msg(msg_id, text="oi"):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "message": {"conversation": text},
        "messageType": "conversation",
    }


def _separator():
    return {"_type": "unread_separator", "count": 3}


class TestSet:
    def test_creates_bookmark_on_focused_message(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=1)

        panel._on_temp_bookmark_set_or_jump(5)

        assert panel._msg_temp_bookmarks == {5: "B"}
        assert panel.main_window.outputs == [
            "Posicionado marcador temporário 5 no elemento 2: item-1"
        ]

    def test_digit_zero_is_a_slot_like_any_other(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=0)

        panel._on_temp_bookmark_set_or_jump(0)

        assert panel._msg_temp_bookmarks == {0: "A"}

    def test_each_digit_holds_its_own_message(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=0)
        panel._on_temp_bookmark_set_or_jump(1)
        panel.messages_list._focused_item = 2
        panel._on_temp_bookmark_set_or_jump(2)

        assert panel._msg_temp_bookmarks == {1: "A", 2: "C"}

    def test_ignores_a_focused_separator_row(self):
        panel = _Stub([_msg("A"), _separator(), _msg("B")], focused_item=1)

        panel._on_temp_bookmark_set_or_jump(3)

        assert panel._msg_temp_bookmarks == {}
        assert panel.main_window.outputs == []

    def test_ignores_when_no_message_is_focused(self):
        panel = _Stub([_msg("A")], focused_item=-1)

        panel._on_temp_bookmark_set_or_jump(3)

        assert panel._msg_temp_bookmarks == {}

    def test_ignores_when_no_conversation_is_open(self):
        panel = _Stub([_msg("A")], focused_item=0, conversation_jid=None)

        panel._on_temp_bookmark_set_or_jump(3)

        assert panel._msg_temp_bookmarks == {}


class TestJump:
    def test_second_press_moves_focus_to_the_bookmarked_message(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=1)
        panel._on_temp_bookmark_set_or_jump(4)
        panel.messages_list._focused_item = 0
        panel.main_window.outputs.clear()

        panel._on_temp_bookmark_set_or_jump(4)

        assert panel.messages_list.focused_calls[-1] == 1
        assert panel.messages_list.selected_calls[-1] == (1, True)
        assert panel.messages_list.ensure_visible_calls[-1] == 1
        assert panel.messages_list.set_focus_called is True
        assert panel.main_window.outputs == [
            "Movido para a posição 2 da lista (marcador temporário 4)"
        ]

    def test_follows_the_message_after_the_list_is_rebuilt(self):
        # A new message arriving shifts every row down — the bookmark keys off
        # the message id, so it must still land on the same message.
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_temp_bookmark_set_or_jump(6)
        panel._sorted_messages = [_msg("X"), _msg("Y"), _msg("A"), _msg("B")]
        panel.main_window.outputs.clear()

        panel._on_temp_bookmark_set_or_jump(6)

        assert panel.messages_list.focused_calls[-1] == 3

    def test_message_gone_drops_the_bookmark_and_says_so(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_temp_bookmark_set_or_jump(2)
        panel._sorted_messages = [_msg("A")]      # "B" was deleted
        panel.main_window.outputs.clear()

        panel._on_temp_bookmark_set_or_jump(2)

        assert panel._msg_temp_bookmarks == {}
        assert panel.main_window.outputs == [
            "Nenhum marcador temporário encontrado para o número 2"
        ]


class TestRemove:
    def test_removes_an_existing_bookmark_and_announces_its_position(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=2)
        panel._on_temp_bookmark_set_or_jump(9)
        panel.main_window.outputs.clear()

        panel._on_temp_bookmark_remove(9)

        assert panel._msg_temp_bookmarks == {}
        assert panel.main_window.outputs == [
            "Removido marcador temporário 9 na posição 3"
        ]

    def test_removing_an_unset_digit_reports_nothing_found(self):
        panel = _Stub([_msg("A")], focused_item=0)

        panel._on_temp_bookmark_remove(8)

        assert panel.main_window.outputs == [
            "Nenhum marcador temporário encontrado para o número 8"
        ]

    def test_removing_a_stale_bookmark_still_clears_the_slot(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_temp_bookmark_set_or_jump(7)
        panel._sorted_messages = [_msg("A")]
        panel.main_window.outputs.clear()

        panel._on_temp_bookmark_remove(7)

        assert panel._msg_temp_bookmarks == {}
        assert panel.main_window.outputs == [
            "Removido marcador temporário 7 (a mensagem original não está mais na lista)"
        ]

    def test_removing_one_digit_leaves_the_others_alone(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=0)
        panel._on_temp_bookmark_set_or_jump(1)
        panel.messages_list._focused_item = 1
        panel._on_temp_bookmark_set_or_jump(2)

        panel._on_temp_bookmark_remove(1)

        assert panel._msg_temp_bookmarks == {2: "B"}


class TestIndependentFromPermanentBookmarks:
    def test_temporary_and_permanent_slots_do_not_share_storage(self):
        # Same digit, two separate sets: Alt+Shift+3 must not disturb whatever
        # Ctrl+3 is holding, which is the whole point of the second set.
        panel = _Stub([_msg("A"), _msg("B")], focused_item=0)
        panel._msg_bookmarks = {3: (CONV, "B")}

        panel._on_temp_bookmark_set_or_jump(3)

        assert panel._msg_temp_bookmarks == {3: "A"}
        assert panel._msg_bookmarks == {3: (CONV, "B")}
