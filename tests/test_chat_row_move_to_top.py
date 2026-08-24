"""A new message must move one row, not rebuild the whole conversations list.

refresh_chat_row_text() covers acks, which change a row's text but not its
position. A new message — sent or received, they go through the same path —
changes both: the chat rises to the top of its group. That used to mean a full
set_chats(), which re-resolves the display name of every chat in the account
and rebuilds every row's text, so a new message took seconds to appear in the
list on a large account.

move_chat_row_to_top() does it with two sort-key computations (this chat's and
the current top of its group), and deliberately refuses whenever "top of its
group" isn't a position it can reason about — a search or filter is active, the
chat isn't rendered yet, the arrays and the control disagree, or the chat
simply doesn't come out on top. The caller then falls back to the full path, so
a refusal costs correctness nothing.

MainWindow is a wx.Frame and can't be instantiated without a running wx.App, so
the methods are bound onto a stub carrying only what they touch.
"""

import pytest

import main as main_module
from main import MainWindow


@pytest.fixture(autouse=True)
def _no_wx_app(monkeypatch):
    """_apply_chat_rows_incrementally() asks wx which window has keyboard focus
    to decide whether to scroll; without a running wx.App that raises."""
    monkeypatch.setattr(main_module.wx.Window, "FindFocus", staticmethod(lambda: None))


class _FakeList:
    def __init__(self, texts):
        self.rows = list(texts)
        self.focused = -1
        self.selected = set()
        self.calls = []

    def GetItemCount(self):
        return len(self.rows)

    def GetItemText(self, idx, col=0):
        return self.rows[idx]

    def SetItem(self, idx, col, text):
        self.calls.append(("SetItem", idx))
        self.rows[idx] = text

    def DeleteItem(self, idx):
        self.calls.append(("DeleteItem", idx))
        self.rows.pop(idx)

    def InsertItem(self, idx, text):
        self.calls.append(("InsertItem", idx))
        self.rows.insert(idx, text)

    def DeleteAllItems(self):
        self.calls.append(("DeleteAllItems", None))
        self.rows = []

    def GetFocusedItem(self):
        return self.focused

    def IsSelected(self, idx):
        return idx in self.selected

    def Focus(self, idx):
        self.focused = idx

    def Select(self, idx, on=True):
        self.selected.add(idx) if on else self.selected.discard(idx)

    def EnsureVisible(self, idx):
        pass

    def Freeze(self):
        pass

    def Thaw(self):
        pass


class _SearchField:
    def __init__(self, value=""):
        self._value = value

    def GetValue(self):
        return self._value


class _Panel:
    def __init__(self, chats, names, texts, search="", conv_filter="all"):
        self.chats_list = list(chats)
        self.chat_names = list(names)
        self._all_chats_list = list(chats)
        self._all_chat_names = list(names)
        self._displayed_jids = [c["remoteJid"] for c in chats]
        self.conversations_list = _FakeList(texts)
        self.search_field = _SearchField(search)
        self._conv_filter = conv_filter
        self.selected_chats = set()


class _Win:
    move_chat_row_to_top = MainWindow.move_chat_row_to_top
    refresh_chat_row_text = MainWindow.refresh_chat_row_text
    _chat_sort_key = MainWindow._chat_sort_key
    _chat_last_ts = MainWindow._chat_last_ts
    _apply_chat_rows_incrementally = MainWindow._apply_chat_rows_incrementally

    def __init__(self, panel, pinned=()):
        self.conversations_panel = panel
        self._pinned_chats = set(pinned)
        self.chats = {c["remoteJid"]: c for c in panel.chats_list}
        self.build_calls = []

    # The row text itself is covered by test_status_update_refreshes_chat_list;
    # here it only needs to be distinguishable and counted.
    def _build_chat_item_text(self, chat, name):
        self.build_calls.append(chat.get("remoteJid"))
        return f"{name}|ts={self._chat_last_ts(chat)}"

    def _counts_as_last_message(self, m):
        return isinstance(m, dict)

    def _normalize_jid(self, jid):
        return jid

    def _schedule_set_chats(self):
        raise AssertionError("the fallback must be the caller's decision, not this method's")


def _chat(jid, ts):
    return {"remoteJid": jid, "t": ts}


def _win(order, pinned=(), search="", conv_filter="all"):
    """order: list of (jid, ts), already in the list's current display order."""
    chats = [_chat(j, ts) for j, ts in order]
    names = [j.split("@")[0] for j, _ in order]
    texts = [f"{n}|ts={ts}" for n, (_, ts) in zip(names, order)]
    panel = _Panel(chats, names, texts, search=search, conv_filter=conv_filter)
    return _Win(panel, pinned=pinned)


# ── the case that matters ─────────────────────────────────────────────────────

def test_a_chat_receiving_a_message_rises_to_the_top():
    win = _win([("a@s", 300), ("b@s", 200), ("c@s", 100)])
    win.chats["c@s"]["t"] = 999          # new message just landed in c
    assert win.move_chat_row_to_top("c@s") is True
    assert win.conversations_panel._displayed_jids == ["c@s", "a@s", "b@s"]
    assert win.conversations_panel.conversations_list.rows[0] == "c|ts=999"


def test_only_the_moved_row_is_rebuilt():
    """The point of the whole exercise: one row's text is recomputed, not the
    account's worth of them."""
    order = [(f"c{i}@s", 1000 - i) for i in range(400)]
    win = _win(order)
    win.chats["c399@s"]["t"] = 99999
    assert win.move_chat_row_to_top("c399@s") is True
    assert win.build_calls == ["c399@s"], "must not rebuild 400 rows to move one"


def test_the_list_is_not_cleared():
    win = _win([("a@s", 300), ("b@s", 200), ("c@s", 100)])
    win.chats["c@s"]["t"] = 999
    win.move_chat_row_to_top("c@s")
    calls = win.conversations_panel.conversations_list.calls
    assert ("DeleteAllItems", None) not in calls


def test_the_backing_arrays_follow_the_rows():
    """Row indices map back to chats everywhere downstream (activation, context
    menu, focus restore) — they must not drift apart."""
    win = _win([("a@s", 300), ("b@s", 200), ("c@s", 100)])
    win.chats["c@s"]["t"] = 999
    win.move_chat_row_to_top("c@s")
    panel = win.conversations_panel
    assert [c["remoteJid"] for c in panel.chats_list] == ["c@s", "a@s", "b@s"]
    assert panel.chat_names == ["c", "a", "b"]
    assert [c["remoteJid"] for c in panel._all_chats_list] == ["c@s", "a@s", "b@s"]
    assert panel._displayed_jids == [c["remoteJid"] for c in panel.chats_list]


def test_focus_follows_the_chat_it_was_on():
    win = _win([("a@s", 300), ("b@s", 200), ("c@s", 100)])
    lst = win.conversations_panel.conversations_list
    lst.focused = 0                       # user is on a@s
    win.chats["c@s"]["t"] = 999
    win.move_chat_row_to_top("c@s")
    assert win.conversations_panel._displayed_jids[lst.focused] == "a@s"


# ── pinned chats ──────────────────────────────────────────────────────────────

def test_an_unpinned_chat_stops_below_the_pinned_ones():
    win = _win([("p@s", 100), ("a@s", 300), ("b@s", 200)], pinned=["p@s"])
    win.chats["b@s"]["t"] = 999
    assert win.move_chat_row_to_top("b@s") is True
    assert win.conversations_panel._displayed_jids == ["p@s", "b@s", "a@s"]


def test_a_pinned_chat_rises_within_the_pinned_group():
    win = _win([("p1@s", 300), ("p2@s", 200), ("a@s", 100)], pinned=["p1@s", "p2@s"])
    win.chats["p2@s"]["t"] = 999
    assert win.move_chat_row_to_top("p2@s") is True
    assert win.conversations_panel._displayed_jids == ["p2@s", "p1@s", "a@s"]


# ── refusals: the caller falls back to the full recompute ─────────────────────

def test_a_chat_already_on_top_just_repaints_its_row():
    win = _win([("a@s", 300), ("b@s", 200)])
    win.chats["a@s"]["t"] = 999
    assert win.move_chat_row_to_top("a@s") is True
    assert win.conversations_panel._displayed_jids == ["a@s", "b@s"]
    assert win.conversations_panel.conversations_list.rows[0] == "a|ts=999"


def test_a_message_that_does_not_actually_reach_the_top_is_refused():
    """An older message arriving late, or a clock skew — don't guess."""
    win = _win([("a@s", 300), ("b@s", 200), ("c@s", 100)])
    win.chats["c@s"]["t"] = 250          # newer than b, still older than a
    assert win.move_chat_row_to_top("c@s") is False


def test_an_active_search_is_refused():
    """The displayed list isn't the sorted chat list, so "top of its group"
    isn't a position this can reason about."""
    win = _win([("a@s", 300), ("b@s", 100)], search="foo")
    win.chats["b@s"]["t"] = 999
    assert win.move_chat_row_to_top("b@s") is False


def test_an_active_filter_is_refused():
    win = _win([("a@s", 300), ("b@s", 100)], conv_filter="unread")
    win.chats["b@s"]["t"] = 999
    assert win.move_chat_row_to_top("b@s") is False


def test_a_chat_not_yet_rendered_is_refused():
    """A brand-new conversation has no row to move; the full path adds it."""
    win = _win([("a@s", 300)])
    win.chats["new@s"] = _chat("new@s", 999)
    assert win.move_chat_row_to_top("new@s") is False


def test_misaligned_arrays_are_refused():
    win = _win([("a@s", 300), ("b@s", 200)])
    win.conversations_panel.chat_names.pop()      # arrays now disagree
    assert win.move_chat_row_to_top("b@s") is False


def test_a_chat_stored_under_a_different_key_than_its_remotejid_is_found():
    win = _win([("real@s", 100), ("a@s", 300)])
    win.chats["stored@lid"] = win.chats["real@s"]
    win.chats["real@s"]["t"] = 999
    assert win.move_chat_row_to_top("stored@lid") is True
    assert win.conversations_panel._displayed_jids[0] == "real@s"


# ── the ordering rule itself ──────────────────────────────────────────────────

def test_sort_key_matches_the_lists_documented_ordering():
    """pinned first, then most-recent descending, then alphabetically —
    the same key _compute_chat_lists() sorts by."""
    win = _win([("a@s", 100)])
    pinned = {"p@s"}
    assert win._chat_sort_key(_chat("p@s", 1), "z", pinned)[0] == 0
    assert win._chat_sort_key(_chat("a@s", 1), "a", pinned)[0] == 1
    newer = win._chat_sort_key(_chat("a@s", 500), "a", pinned)
    older = win._chat_sort_key(_chat("b@s", 100), "a", pinned)
    assert newer < older
    first = win._chat_sort_key(_chat("a@s", 100), "aaa", pinned)
    second = win._chat_sort_key(_chat("b@s", 100), "bbb", pinned)
    assert first < second


def test_millisecond_timestamps_are_normalised():
    win = _win([("a@s", 100)])
    assert win._chat_last_ts({"t": 1_700_000_000_000}) == 1_700_000_000
    assert win._chat_last_ts({"t": 1_700_000_000}) == 1_700_000_000
