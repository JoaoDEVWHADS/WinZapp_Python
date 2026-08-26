"""CompatListBoxMessagesCtrl.RefreshItem() — the wx.ListCtrl call every
messages-list repaint makes, mapped onto what a native LISTBOX can do.

ui/conversations.py calls `self.messages_list.RefreshItem(i)` in three places
after SetItemText(), because Windows otherwise defers the visual update to the
next paint cycle. wx.ListCtrl has that method; CompatListBoxMessagesCtrl — the
wx.ListBox the accessibility fallback swaps in — did not, and the three call
sites failed in two different ways:

  * refresh_message_status() and the unconfirmed-send marker wrap the call in
    `try/except Exception: pass`, so under this control the repaint was simply
    skipped — silently producing the frozen delivery-status icon that
    refresh_message_status()'s own comment says the call exists to prevent.
  * update_media_upload_progress() does not, so it raised AttributeError out
    of a wx.CallAfter callback and upload progress stopped updating.

The method is bound onto a plain stub rather than instantiated: this is a
wx.ListBox subclass and cannot exist without a running wx.App, and the method
only reaches GetCount()/Refresh().
"""

import ast
import types
from pathlib import Path

from ui.accessible import CompatListBoxMessagesCtrl


ROOT = Path(__file__).resolve().parents[1]


class _ListBoxStub:
    """Bound in __init__, not as a class attribute: a missing method would
    otherwise raise at import time and take the whole module down with a
    collection error, hiding the surface guard below — which is the test
    whose failure message actually explains the problem."""

    def __init__(self, count):
        self._count = count
        self.refreshes = 0
        self.RefreshItem = types.MethodType(
            CompatListBoxMessagesCtrl.RefreshItem, self
        )

    def GetCount(self):
        return self._count

    def Refresh(self):
        self.refreshes += 1


class TestRefreshItem:
    def test_a_valid_row_repaints_the_control(self):
        stub = _ListBoxStub(5)
        stub.RefreshItem(2)
        assert stub.refreshes == 1

    def test_the_first_and_last_rows_count_as_valid(self):
        stub = _ListBoxStub(5)
        stub.RefreshItem(0)
        stub.RefreshItem(4)
        assert stub.refreshes == 2

    def test_an_out_of_range_row_is_a_no_op(self):
        """Mirrors the bounds check every other row-addressed method on this
        class already does (Focus/Select/EnsureVisible/DeleteItem): the
        messages list is mutated from several threads via wx.CallAfter, so a
        row index can arrive after the row is gone."""
        stub = _ListBoxStub(3)
        stub.RefreshItem(3)
        stub.RefreshItem(-1)
        stub.RefreshItem(99)
        assert stub.refreshes == 0

    def test_an_empty_list_never_repaints(self):
        stub = _ListBoxStub(0)
        stub.RefreshItem(0)
        assert stub.refreshes == 0


def test_the_control_answers_the_whole_listctrl_surface_the_messages_list_uses():
    """The regression this guards: a wx.ListCtrl method used on
    `self.messages_list` that this stand-in does not implement is an
    AttributeError the moment a user turns the accessibility fallback on —
    and only for those users, which is why it went unnoticed.

    Collected from the source rather than hardcoded, so a call added later is
    covered without editing this list.
    """
    src = (ROOT / "client" / "ui" / "conversations.py").read_text(encoding="utf-8")
    tree = ast.parse(src, filename="conversations.py")

    used = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "messages_list"
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
        ):
            used.add(node.func.attr)

    assert "RefreshItem" in used, "the AST walk found no messages_list calls at all"

    missing = sorted(
        name for name in used
        if not hasattr(CompatListBoxMessagesCtrl, name)
    )
    assert not missing, (
        f"ui/conversations.py calls {missing} on self.messages_list, but "
        f"CompatListBoxMessagesCtrl does not implement them — that is an "
        f"AttributeError for every user on the accessibility fallback control."
    )
