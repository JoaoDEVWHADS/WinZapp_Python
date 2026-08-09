"""Test for ConversationsPanel._on_accel_jump_last() (Alt+2).

Reported live after this session's unread-separator-reuse fix: sending a
message and pressing Alt+2 no longer focused the user's own just-sent
message — it landed on the wrong row, or on the last message from someone
else. Root cause (fixed alongside this in the same change): the unread
separator row could end up placed at the very bottom of the list even when
the true last message was the user's own — _on_accel_jump_last() blindly
trusted `messages_list.GetItemCount() - 1` as "the last message" without
checking whether that row was actually a sentinel (separator/placeholder)
rather than a real message. Fixed to walk backwards over any trailing
sentinel rows.

ConversationsPanel is a wx.Panel and cannot be instantiated without a
running wx.App — exercised against a small stub, same approach as
tests/test_unread_separator_reuse.py.
"""

from ui.conversations import ConversationsPanel


class _FakeMessagesList:
    def __init__(self, focused=-1):
        self._focused = focused
        self.selected = None
        self.ensured_visible = None
        self.focus_set = False

    def HasFocus(self):
        return self.focus_set

    def SetFocus(self):
        self.focus_set = True

    def Select(self, idx, on=True):
        self.selected = idx

    def EnsureVisible(self, idx):
        self.ensured_visible = idx


def _msg(mid):
    return {"key": {"id": mid, "fromMe": True}, "messageType": "conversation"}


def _sep():
    return {"_type": "unread_separator", "count": 1}


class _Stub:
    _on_accel_jump_last = ConversationsPanel._on_accel_jump_last
    _is_separator = ConversationsPanel._is_separator

    def __init__(self, sorted_messages):
        self._sorted_messages = sorted_messages
        self.messages_list = _FakeMessagesList()


class TestJumpToLastMessage:
    def test_last_row_is_a_real_message(self):
        stub = _Stub([_msg("a"), _msg("b"), _msg("c")])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.selected == 2

    def test_skips_a_trailing_unread_separator(self):
        """The exact reported bug: a separator ends up sitting at the very
        bottom of the list (e.g. right after being (re)placed for a message
        that just arrived) — Alt+2 must land on the real message before it,
        not the separator row itself."""
        stub = _Stub([_msg("a"), _msg("b"), _sep()])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.selected == 1

    def test_skips_multiple_trailing_sentinel_rows(self):
        stub = _Stub([_msg("a"), _sep(), {"_type": "empty_placeholder"}])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.selected == 0

    def test_empty_list_selects_nothing(self):
        stub = _Stub([])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.selected is None

    def test_a_list_of_only_sentinels_selects_nothing(self):
        stub = _Stub([_sep()])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.selected is None

    def test_ensures_the_selected_row_is_visible_and_focuses_the_list(self):
        stub = _Stub([_msg("a"), _msg("b")])
        stub._on_accel_jump_last(None)
        assert stub.messages_list.ensured_visible == 1
        assert stub.messages_list.focus_set is True
