"""Tests for repainting individual rows of the messages list instead of
rebuilding it (ConversationsPanel._repaint_message_rows and friends).

Starring, pinning and a remote "delete for everyone" only change the text of
rows already on screen — the list is sorted by timestamp, which none of them
touch — yet each of them went through populate_messages(), which re-sorts and
de-duplicates every record in the conversation, rebuilds the reaction map,
recomputes the unread separator and pagination window, and then
DeleteAllItems() + Append()s every row. That is the same disproportion
main.py's refresh_chat_row_text() fixed for the conversations list, plus a
fresh flood of accessibility events for the screen reader every time.

The signature bookkeeping is the subtle half: populate_messages() snapshots
_messages_signature() on its way out, so a local change landed in the cache as
a side effect of the rebuild. Repainting instead has to move that cache
forward itself, or refresh_messages_if_changed() would see a mismatch on the
next background poll and rebuild the whole list anyway (moving the user's
focus for something already correct on screen) — but only when the rows that
changed are the ones just repainted, or a change that arrived from somewhere
else would be swallowed and never rendered.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are bound to a small stub — same approach as
tests/test_message_bookmarks.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeList:
    def __init__(self, count=0):
        self._count = count
        self.texts = {}

    def GetItemCount(self):
        return self._count

    def SetItemText(self, idx, text):
        self.texts[idx] = text


class _Panel:
    _repaint_message_rows = ConversationsPanel._repaint_message_rows
    _repaint_or_repopulate = ConversationsPanel._repaint_or_repopulate
    _set_message_row_texts = ConversationsPanel._set_message_row_texts
    _refresh_message_rows_by_ids = ConversationsPanel._refresh_message_rows_by_ids
    _adopt_signature_after_repaint = ConversationsPanel._adopt_signature_after_repaint
    _signature_changed_ids = staticmethod(ConversationsPanel._signature_changed_ids)
    _is_separator = ConversationsPanel._is_separator

    def __init__(self, messages=(), item_count=None):
        self._sorted_messages = list(messages)
        self.messages_list = _FakeList(
            count=len(self._sorted_messages) if item_count is None else item_count
        )
        self._messages_signature_cache = None
        self.populate_calls = 0
        # Drives _messages_signature() without the real record plumbing: the
        # test sets what the next fingerprint should look like.
        self._next_signature = None
        self.signature_raises = False

    def populate_messages(self, preserve_focus=False):
        self.populate_calls += 1

    def _render_message_line(self, msg, index=None, total=None):
        mid = msg.get("key", {}).get("id", "")
        flags = "".join(f for f, k in (("*", "starred"), ("P", "pinInChat")) if msg.get(k))
        return f"{mid}{flags}@{index}/{total}"

    def _messages_signature(self):
        if self.signature_raises:
            raise RuntimeError("boom")
        return self._next_signature


def _msg(mid, **flags):
    m = {"key": {"id": mid, "fromMe": False}, "messageType": "conversation"}
    m.update(flags)
    return m


def _sig(*rows, jid="grupo@g.us", first_unread=None, pending=0):
    """A _messages_signature()-shaped tuple: (jid, first_unread_id,
    pending_unread, per-message rows), each row starting with the id."""
    return (jid, first_unread, pending, tuple(rows))


class TestRepaintMessageRows:
    def test_repaints_only_the_requested_rows(self):
        panel = _Panel([_msg("m1"), _msg("m2", starred=True), _msg("m3")])

        assert panel._repaint_message_rows(["m2"]) is True
        assert panel.messages_list.texts == {1: "m2*@1/3"}

    def test_reports_the_rows_it_could_not_find(self):
        """A row paginated out of the current window, or replaced by a resync
        while a server call was in flight, can only be shown by a rebuild."""
        panel = _Panel([_msg("m1")])

        assert panel._repaint_message_rows(["m1", "gone"]) is False

    def test_skips_separator_rows_without_matching_them(self):
        panel = _Panel([{"_type": "unread_separator", "count": 2}, _msg("m1")])

        assert panel._repaint_message_rows(["m1"]) is True
        assert panel.messages_list.texts == {1: "m1@1/2"}

    def test_a_control_out_of_step_with_the_rows_refuses(self):
        """SetItemText against a stale index would write the right text into
        the wrong row — that's a rebuild, not a repaint."""
        panel = _Panel([_msg("m1"), _msg("m2")], item_count=5)

        assert panel._repaint_message_rows(["m1"]) is False
        assert panel.messages_list.texts == {}

    def test_no_ids_and_no_rows_refuse(self):
        assert _Panel([_msg("m1")])._repaint_message_rows([]) is False
        assert _Panel([_msg("m1")])._repaint_message_rows([""]) is False
        assert _Panel([])._repaint_message_rows(["m1"]) is False

    def test_a_rendering_failure_falls_back_instead_of_raising(self):
        panel = _Panel([_msg("m1")])
        panel._render_message_line = lambda *a, **kw: (_ for _ in ()).throw(ValueError("nope"))

        assert panel._repaint_message_rows(["m1"]) is False


class TestRepaintOrRepopulate:
    def test_a_successful_repaint_never_rebuilds(self):
        panel = _Panel([_msg("m1")])
        panel._repaint_or_repopulate(["m1"])
        assert panel.populate_calls == 0

    def test_an_impossible_repaint_rebuilds(self):
        panel = _Panel([_msg("m1")])
        panel._repaint_or_repopulate(["gone"])
        assert panel.populate_calls == 1


class TestSignatureChangedIds:
    def test_reports_the_rows_whose_entry_differs(self):
        old = _sig(("m1", False), ("m2", False))
        new = _sig(("m1", False), ("m2", True))
        assert ConversationsPanel._signature_changed_ids(old, new) == {"m2"}

    def test_an_added_or_removed_row_counts_as_changed(self):
        old = _sig(("m1", False))
        new = _sig(("m1", False), ("m2", False))
        assert ConversationsPanel._signature_changed_ids(old, new) == {"m2"}

    def test_identical_snapshots_report_nothing(self):
        sig = _sig(("m1", False))
        assert ConversationsPanel._signature_changed_ids(sig, sig) == set()

    @pytest.mark.parametrize("new", [
        _sig(("m1", False), jid="outro@g.us"),      # different conversation
        _sig(("m1", False), first_unread="m1"),     # separator moved
        _sig(("m1", False), pending=3),             # unread count changed
    ])
    def test_a_header_difference_is_not_expressible_as_changed_rows(self, new):
        old = _sig(("m1", False))
        assert ConversationsPanel._signature_changed_ids(old, new) is None

    def test_repeated_or_empty_ids_make_the_comparison_ambiguous(self):
        old = _sig(("m1", False), ("m1", True))
        assert ConversationsPanel._signature_changed_ids(old, _sig(("m1", False))) is None
        assert ConversationsPanel._signature_changed_ids(
            _sig(("", False)), _sig(("", True))
        ) is None

    def test_a_missing_snapshot_is_not_comparable(self):
        assert ConversationsPanel._signature_changed_ids(None, _sig(("m1", False))) is None
        assert ConversationsPanel._signature_changed_ids(_sig(("m1", False)), None) is None


class TestAdoptSignatureAfterRepaint:
    def test_adopts_when_only_the_repainted_rows_changed(self):
        panel = _Panel([_msg("m1")])
        panel._messages_signature_cache = _sig(("m1", False), ("m2", False))
        panel._next_signature = _sig(("m1", True), ("m2", False))

        panel._adopt_signature_after_repaint({"m1"})

        assert panel._messages_signature_cache == panel._next_signature

    def test_keeps_the_stale_cache_when_something_else_also_changed(self):
        """That other change still needs the rebuild this repaint didn't do —
        adopting here would swallow it and it would never be rendered."""
        stale = _sig(("m1", False), ("m2", False))
        panel = _Panel([_msg("m1")])
        panel._messages_signature_cache = stale
        panel._next_signature = _sig(("m1", True), ("m2", True))

        panel._adopt_signature_after_repaint({"m1"})

        assert panel._messages_signature_cache == stale

    def test_keeps_the_stale_cache_when_the_rows_are_not_comparable(self):
        stale = _sig(("m1", False))
        panel = _Panel([_msg("m1")])
        panel._messages_signature_cache = stale
        panel._next_signature = _sig(("m1", True), jid="outro@g.us")

        panel._adopt_signature_after_repaint({"m1"})

        assert panel._messages_signature_cache == stale

    def test_a_failing_fingerprint_clears_the_cache_so_the_next_refresh_rebuilds(self):
        panel = _Panel([_msg("m1")])
        panel._messages_signature_cache = _sig(("m1", False))
        panel.signature_raises = True

        panel._adopt_signature_after_repaint({"m1"})

        assert panel._messages_signature_cache is None

    def test_a_successful_repaint_moves_the_cache_forward(self):
        """End-to-end: the repaint path itself must leave the fingerprint
        describing what is now on screen, or the next background poll rebuilds
        the list and moves the user's focus for nothing."""
        panel = _Panel([_msg("m1", starred=True)])
        panel._messages_signature_cache = _sig(("m1", False))
        panel._next_signature = _sig(("m1", True))

        assert panel._repaint_message_rows(["m1"]) is True
        assert panel._messages_signature_cache == _sig(("m1", True))


class TestSelectionRefreshIsUnaffected:
    def test_selection_repaint_leaves_the_fingerprint_alone(self):
        """_refresh_message_rows_by_ids() is the selection-marker path: the
        selection isn't part of the fingerprint, and it must not adopt one —
        it has no idea whether anything else is waiting for a rebuild."""
        panel = _Panel([_msg("m1")])
        panel._messages_signature_cache = _sig(("m1", False))
        panel._next_signature = _sig(("m1", True))

        panel._refresh_message_rows_by_ids(["m1"])

        assert panel.messages_list.texts == {0: "m1@0/1"}
        assert panel._messages_signature_cache == _sig(("m1", False))
