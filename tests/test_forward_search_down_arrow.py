"""Down arrow in the forward dialog's search field focuses the first result."""

import wx

from ui.conversation_panel.forwarding import focus_first_result


class _Event:
    def __init__(self, key):
        self.key = key
        self.skipped = False

    def GetKeyCode(self):
        return self.key

    def Skip(self):
        self.skipped = True


class _List:
    def __init__(self, count):
        self.count = count
        self.calls = []

    def GetCount(self):
        return self.count

    def SetFocus(self):
        self.calls.append("focus")

    def SetSelection(self, idx):
        self.calls.append(("select", idx))


def test_down_focuses_list_and_selects_first_row():
    event, lst = _Event(wx.WXK_DOWN), _List(3)
    assert focus_first_result(event, lst) is True
    assert lst.calls == ["focus", ("select", 0)]
    assert not event.skipped


def test_down_with_no_results_is_swallowed_without_moving_focus():
    event, lst = _Event(wx.WXK_DOWN), _List(0)
    assert focus_first_result(event, lst) is True
    assert lst.calls == []


def test_other_keys_stay_with_the_search_field():
    event, lst = _Event(ord("A")), _List(3)
    assert focus_first_result(event, lst) is False
    assert event.skipped
    assert lst.calls == []
