"""Tests for the incremental chat-list update path.

A new message (or a reaction, or a read receipt) reorders the conversations
list — almost always by moving one chat to the top. That misses
add_chats_to_ui()'s SetItem fast path (which requires the JID order to be
unchanged) and used to fall through to a full rebuild: DeleteAllItems() plus
one Append() per row. The cost of showing a new preview therefore scaled with
how many chats the account has, which is what made the preview visibly lag,
and screen readers were handed a brand-new list on every message.

plan_row_updates() (core/utils.py) turns that into a couple of native calls,
and MainWindow._apply_chat_rows_incrementally() applies them.

MainWindow is a wx.Frame and can't be instantiated without a running wx.App,
so the method under test is bound onto a stub carrying a fake ListCtrl — same
approach as the rest of this suite.
"""

import pytest

from core.utils import plan_row_updates


def _apply(old, ops, new):
    """Replay a plan the way the wx.ListCtrl does, to check it really lands
    on *new*."""
    work = list(old)
    for kind, idx in ops:
        if kind == "delete":
            work.pop(idx)
        else:
            work.insert(idx, new[idx])
    return work


# ── plan_row_updates ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("old,new,label", [
    (list("ABCD"), list("CABD"), "a chat moves up (a new message arrived)"),
    (list("ABCD"), list("BCAD"), "a chat moves down"),
    (list("ABC"),  list("DABC"), "a brand-new chat appears at the top"),
    (list("ABC"),  list("AC"),   "a chat is removed (deleted/archived)"),
    (list("ABCDE"), list("CEABD"), "two chats moved in one debounce window"),
    (list("ABC"),  list("CBA"),  "full reversal"),
    ([],           list("AB"),   "first chats ever"),
    (list("AB"),   [],           "every chat gone"),
])
def test_a_plan_reproduces_the_target_order(old, new, label):
    ops = plan_row_updates(old, new, max_ops=99)
    assert ops is not None, label
    assert _apply(old, ops, new) == new, label


def test_the_common_case_costs_two_operations():
    """One chat jumping to the top must not depend on list length."""
    short = plan_row_updates(list("ABCD"), list("CABD"))
    long_old = [f"c{i}" for i in range(500)]
    long_new = [long_old[300]] + long_old[:300] + long_old[301:]
    long_plan = plan_row_updates(long_old, long_new)
    assert len(short) == 2
    assert len(long_plan) == 2, "cost must not scale with the number of chats"


def test_an_unchanged_list_plans_nothing():
    assert plan_row_updates(list("ABC"), list("ABC")) == []


def test_a_churny_change_is_refused_so_the_caller_rebuilds():
    old = [f"c{i}" for i in range(60)]
    new = list(reversed(old))
    assert plan_row_updates(old, new) is None


def test_duplicate_identities_are_refused_rather_than_mangled():
    """index() would be ambiguous and the plan silently wrong."""
    assert plan_row_updates(["A", "A", "B"], ["B", "A", "A"]) is None
    assert plan_row_updates(["A", "B"], ["B", "B"]) is None


# ── _apply_chat_rows_incrementally ────────────────────────────────────────────

class _FakeListCtrl:
    """Enough wx.ListCtrl for the row surgery under test, and it records the
    native calls so a test can assert the list was not rebuilt."""

    def __init__(self, texts=()):
        self.rows = list(texts)
        self.focused = -1
        self.selected = set()
        self.calls = []
        self.frozen = 0
        self.ensure_visible = []

    # -- mutation
    def DeleteItem(self, idx):
        self.calls.append(("DeleteItem", idx))
        self.rows.pop(idx)

    def InsertItem(self, idx, text):
        self.calls.append(("InsertItem", idx))
        self.rows.insert(idx, text)

    def SetItem(self, idx, col, text):
        self.calls.append(("SetItem", idx))
        self.rows[idx] = text

    def DeleteAllItems(self):
        self.calls.append(("DeleteAllItems", None))
        self.rows = []

    # -- queries
    def GetItemCount(self):
        return len(self.rows)

    def GetItemText(self, idx, col=0):
        return self.rows[idx]

    def GetFocusedItem(self):
        return self.focused

    def IsSelected(self, idx):
        return idx in self.selected

    # -- focus/selection
    def Focus(self, idx):
        self.focused = idx

    def Select(self, idx, on=True):
        self.selected.add(idx) if on else self.selected.discard(idx)

    def EnsureVisible(self, idx):
        self.ensure_visible.append(idx)

    def Freeze(self):
        self.frozen += 1

    def Thaw(self):
        self.frozen -= 1


class _Win:
    """Stands in for MainWindow, carrying only what the method touches."""

    from main import MainWindow
    _apply_chat_rows_incrementally = MainWindow._apply_chat_rows_incrementally


@pytest.fixture
def win(monkeypatch):
    # wx.Window.FindFocus() is consulted to decide whether to scroll the list.
    import main as main_module
    monkeypatch.setattr(main_module.wx.Window, "FindFocus", staticmethod(lambda: None))
    return _Win()


def _texts(jids, previews=None):
    previews = previews or {}
    return [f"{j}{previews.get(j, '')}" for j in jids]


def test_a_chat_moving_up_is_two_calls_and_no_rebuild(win):
    old = list("ABCD")
    new = list("CABD")
    lst = _FakeListCtrl(_texts(old))
    ok = win._apply_chat_rows_incrementally(lst, old, new, _texts(new), None)
    assert ok is True
    assert lst.rows == _texts(new)
    assert ("DeleteAllItems", None) not in lst.calls
    row_ops = [c for c in lst.calls if c[0] in ("DeleteItem", "InsertItem")]
    assert len(row_ops) == 2


def test_the_moved_row_gets_its_new_preview(win):
    """The whole point: the chat that just received a message shows the new
    preview, and the other rows are resynced too."""
    old = list("ABC")
    new = list("BAC")
    lst = _FakeListCtrl(_texts(old))
    new_texts = _texts(new, previews={"B": " new message", "C": " 2 unread"})
    assert win._apply_chat_rows_incrementally(lst, old, new, new_texts, None) is True
    assert lst.rows == new_texts


def test_focus_follows_the_chat_not_the_row_index(win):
    """A chat jumping to the top must not drag the user's cursor along, and
    must not reset focus to row 0 the way a rebuild does."""
    old = list("ABCD")
    new = list("CABD")          # C jumps to the top
    lst = _FakeListCtrl(_texts(old))
    lst.focused = 0             # user is on A
    ok = win._apply_chat_rows_incrementally(lst, old, new, _texts(new), "A")
    assert ok is True
    assert lst.rows[lst.focused] == "A"   # still on A, now at index 1


def test_focus_is_left_alone_when_its_chat_is_gone(win):
    old = list("ABC")
    new = list("BC")
    lst = _FakeListCtrl(_texts(old))
    lst.focused = 0
    assert win._apply_chat_rows_incrementally(lst, old, new, _texts(new), "A") is True
    assert lst.rows == _texts(new)


def test_the_list_is_frozen_while_rows_move(win):
    """Batch the mutations so screen readers get one event, not one per row."""
    old, new = list("ABCD"), list("CABD")
    lst = _FakeListCtrl(_texts(old))
    win._apply_chat_rows_incrementally(lst, old, new, _texts(new), None)
    assert lst.frozen == 0, "Freeze/Thaw must be balanced"


def test_a_churny_change_falls_back_to_the_caller(win):
    old = [f"c{i}" for i in range(60)]
    new = list(reversed(old))
    lst = _FakeListCtrl(_texts(old))
    assert win._apply_chat_rows_incrementally(lst, old, new, _texts(new), None) is False
    assert lst.calls == [], "must not half-apply before giving up"


def test_a_native_failure_falls_back_instead_of_leaving_a_half_list(win):
    old, new = list("ABCD"), list("CABD")
    lst = _FakeListCtrl(_texts(old))

    def _boom(idx, text):
        raise RuntimeError("Couldn't insert list control item")

    lst.InsertItem = _boom
    assert win._apply_chat_rows_incrementally(lst, old, new, _texts(new), None) is False
    assert lst.frozen == 0, "Thaw must still run after a failure"


def test_a_row_count_mismatch_falls_back(win):
    """If the control ends up disagreeing with the plan, rebuild rather than
    leave indices and chats pointing at different rows."""
    old, new = list("ABC"), list("CAB")
    lst = _FakeListCtrl(_texts(old))
    real_insert = lst.InsertItem

    def _insert_and_add_junk(idx, text):
        real_insert(idx, text)
        lst.rows.append("junk")     # simulate the control disagreeing

    lst.InsertItem = _insert_and_add_junk
    assert win._apply_chat_rows_incrementally(lst, old, new, _texts(new), None) is False
