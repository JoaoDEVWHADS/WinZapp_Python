"""Runtime replacement of the messages-list control.

Switching Settings > User Interface between Classic and List box must replace
the native wx control immediately without rebuilding pagination, losing the
focused row, or leaving the old control alive behind the new one.
"""

import pytest

wx = pytest.importorskip("wx")
from ui.conversations import ConversationsPanel


class _OldList:
    def __init__(self, focused=1):
        self.focused = focused
        self.hidden = False
        self.destroyed = False

    def GetFocusedItem(self):
        return self.focused

    def Hide(self):
        self.hidden = True

    def Destroy(self):
        self.destroyed = True


class _NewList:
    def __init__(self):
        self.rows = []
        self.focused = -1
        self.selected = -1
        self.visible = -1
        self.frozen = False
        self.focus_calls = 0

    def Freeze(self):
        self.frozen = True

    def Thaw(self):
        self.frozen = False

    def Append(self, entry):
        self.rows.append(entry[0])

    def Focus(self, row):
        self.focused = row

    def Select(self, row):
        self.selected = row

    def EnsureVisible(self, row):
        self.visible = row

    def SetFocus(self):
        self.focus_calls += 1


class _Sizer:
    def __init__(self):
        self.replacements = []

    def Replace(self, old, new):
        self.replacements.append((old, new))
        return True


class _Panel:
    def __init__(self, sizer):
        self.sizer = sizer
        self.layouts = 0

    def GetSizer(self):
        return self.sizer

    def Layout(self):
        self.layouts += 1


class _ReadMore:
    def __init__(self):
        self.hidden = False

    def Hide(self):
        self.hidden = True


class _Stub:
    apply_message_list_mode = ConversationsPanel.apply_message_list_mode

    def __init__(self):
        self._message_list_mode = "classic"
        self.messages_list = _OldList(focused=1)
        self._sorted_messages = ["first", "second", "third"]
        self.sizer = _Sizer()
        self.conversation_panel = _Panel(self.sizer)
        self._read_more_btn = _ReadMore()
        self._read_more_remainder = "tail"
        self.created = None
        self.rerendered = 0

    def _create_messages_list_control(self, mode):
        self.created = _NewList()
        return self.created

    def _render_message_line(self, msg, index=None, total=None):
        return f"{msg}:{index + 1}/{total}"

    def _rerender_messages_list_rows(self):
        self.rerendered += 1

    def _update_read_more_button(self, index):
        pass


def test_switch_replaces_control_and_keeps_the_current_row(monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))
    old = stub.messages_list

    stub.apply_message_list_mode("listbox")

    assert stub._message_list_mode == "listbox"
    assert stub.sizer.replacements == [(old, stub.created)]
    assert stub.created.rows == ["first:1/3", "second:2/3", "third:3/3"]
    assert stub.created.focused == 1
    assert stub.created.selected == 1
    assert stub.created.visible == 1
    assert old.hidden is True
    assert old.destroyed is True
    assert stub._read_more_btn.hidden is True
    assert stub._read_more_remainder == ""


def test_same_mode_only_rerenders_rows_in_place(monkeypatch):
    stub = _Stub()
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: None))

    stub.apply_message_list_mode("classic")

    assert stub.rerendered == 1
    assert stub.created is None
