"""Tests for message-list bookmarks (Ctrl+0..9 / Ctrl+Shift+0..9).

Ctrl+<digit> on the focused message row either creates a bookmark (no
bookmark yet for that digit) or jumps focus/selection to the already-
bookmarked message. Ctrl+Shift+<digit> removes a bookmark if one exists.

Bookmarks are keyed by the message's stable key.id, not by raw list index, so
they keep pointing at the right message even if the list is rebuilt (new
message arriving, pagination) between setting a bookmark and using it.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against a
small stub carrying just the attributes they touch — same approach as
tests/test_sender_names.py and tests/test_notifications.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeI18n:
    """Returns the real pt-BR templates for the keys these methods use."""

    _STRINGS = {
        "bookmark_set": "Posicionado marcador {digit} no elemento {position}: {text}",
        "bookmark_jumped": "Movido para a posição {position} da lista (marcador {digit})",
        "bookmark_removed": "Removido marcador {digit} na posição {position}",
        "bookmark_removed_stale": "Removido marcador {digit} (a mensagem original não está mais na lista)",
        "bookmark_not_found": "Nenhum marcador encontrado para o número {digit}",
    }

    def t(self, key):
        return self._STRINGS[key]


class _FakeMessagesList:
    """Records Focus()/Select()/EnsureVisible()/SetFocus() calls."""

    def __init__(self, focused_item=-1):
        self._focused_item = focused_item
        self.focused_calls = []
        self.selected_calls = []
        self.ensure_visible_calls = []
        self.set_focus_called = False
        self._texts = {}

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
        return self._texts.get(idx, f"item-{idx}")


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.outputs = []

    def output(self, text, interrupt=False):
        self.outputs.append(text)


class _Stub:
    """Minimal stand-in for ConversationsPanel."""

    _is_separator = ConversationsPanel._is_separator
    _find_index_by_msg_id = ConversationsPanel._find_index_by_msg_id
    _on_bookmark_set_or_jump = ConversationsPanel._on_bookmark_set_or_jump
    _on_bookmark_remove = ConversationsPanel._on_bookmark_remove

    def __init__(self, sorted_messages, focused_item=-1):
        self._msg_bookmarks = {}
        self._sorted_messages = sorted_messages
        self.messages_list = _FakeMessagesList(focused_item)
        self.main_window = _FakeMainWindow()


def _msg(msg_id, text="oi"):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "message": {"conversation": text},
        "messageType": "conversation",
    }


def _separator():
    return {"_type": "unread_separator", "count": 3}


class TestBookmarkSet:
    def test_creates_bookmark_on_focused_message(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=1)

        panel._on_bookmark_set_or_jump(5)

        assert panel._msg_bookmarks[5] == "B"
        assert panel.main_window.outputs == [
            "Posicionado marcador 5 no elemento 2: item-1"
        ]

    def test_no_focused_item_creates_no_bookmark(self):
        panel = _Stub([_msg("A")], focused_item=-1)

        panel._on_bookmark_set_or_jump(0)

        assert panel._msg_bookmarks == {}
        assert panel.main_window.outputs == []

    def test_focused_separator_creates_no_bookmark(self):
        panel = _Stub([_msg("A"), _separator(), _msg("B")], focused_item=1)

        panel._on_bookmark_set_or_jump(3)

        assert panel._msg_bookmarks == {}
        assert panel.main_window.outputs == []


class TestBookmarkJump:
    def test_second_press_jumps_to_bookmarked_message(self):
        panel = _Stub([_msg("A"), _msg("B"), _msg("C")], focused_item=0)
        panel._on_bookmark_set_or_jump(7)  # bookmark "A" at position 1
        panel.main_window.outputs.clear()

        # User moved focus elsewhere, then presses Ctrl+7 again.
        panel.messages_list._focused_item = 2
        panel._on_bookmark_set_or_jump(7)

        assert panel.messages_list.focused_calls[-1] == 0
        assert panel.messages_list.selected_calls[-1] == (0, True)
        assert panel.messages_list.ensure_visible_calls[-1] == 0
        assert panel.messages_list.set_focus_called is True
        assert panel.main_window.outputs == [
            "Movido para a posição 1 da lista (marcador 7)"
        ]
        # Jumping must not touch/recreate the bookmark itself.
        assert panel._msg_bookmarks[7] == "A"

    def test_jump_follows_message_after_list_is_rebuilt(self):
        """A bookmark keeps pointing at the same message even if the list
        was rebuilt (e.g. a new message arrived) and the position shifted."""
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_bookmark_set_or_jump(1)  # bookmark "B" at position 2
        panel.main_window.outputs.clear()

        # Simulate populate_messages() rebuilding the list with a new
        # message inserted before the bookmarked one.
        panel._sorted_messages = [_msg("A"), _msg("NEW"), _msg("B")]

        panel._on_bookmark_set_or_jump(1)

        assert panel.messages_list.focused_calls[-1] == 2  # "B" is now at index 2
        assert panel.main_window.outputs == [
            "Movido para a posição 3 da lista (marcador 1)"
        ]

    def test_jump_to_deleted_message_drops_stale_bookmark(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_bookmark_set_or_jump(2)  # bookmark "B"
        panel.main_window.outputs.clear()

        # "B" is no longer in the list (deleted, paged out, ...).
        panel._sorted_messages = [_msg("A")]

        panel._on_bookmark_set_or_jump(2)

        assert 2 not in panel._msg_bookmarks
        assert panel.main_window.outputs == [
            "Nenhum marcador encontrado para o número 2"
        ]
        # Must not have moved focus anywhere.
        assert panel.messages_list.focused_calls == []


class TestBookmarkRemove:
    def test_removes_existing_bookmark(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_bookmark_set_or_jump(9)  # bookmark "B" at position 2
        panel.main_window.outputs.clear()

        panel._on_bookmark_remove(9)

        assert 9 not in panel._msg_bookmarks
        assert panel.main_window.outputs == [
            "Removido marcador 9 na posição 2"
        ]

    def test_removing_unset_bookmark_announces_not_found(self):
        panel = _Stub([_msg("A")], focused_item=0)

        panel._on_bookmark_remove(3)

        assert panel._msg_bookmarks == {}
        assert panel.main_window.outputs == [
            "Nenhum marcador encontrado para o número 3"
        ]

    def test_removing_bookmark_for_deleted_message(self):
        panel = _Stub([_msg("A"), _msg("B")], focused_item=1)
        panel._on_bookmark_set_or_jump(4)  # bookmark "B"
        panel.main_window.outputs.clear()
        panel._sorted_messages = [_msg("A")]  # "B" gone

        panel._on_bookmark_remove(4)

        assert 4 not in panel._msg_bookmarks
        assert panel.main_window.outputs == [
            "Removido marcador 4 (a mensagem original não está mais na lista)"
        ]


class TestBookmarksAreIndependentPerDigit:
    def test_ten_digits_can_hold_ten_independent_bookmarks(self):
        messages = [_msg(str(i)) for i in range(10)]
        panel = _Stub(messages, focused_item=0)

        for digit in range(10):
            panel.messages_list._focused_item = digit
            panel._on_bookmark_set_or_jump(digit)

        assert panel._msg_bookmarks == {d: str(d) for d in range(10)}
