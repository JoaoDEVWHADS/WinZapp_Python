"""Tests for where the unread separator is placed and when it goes away.

Two separate reports, both about the same row:

1. "Mensagens próprias contam como não lidas" — messages sent from the phone or
   another linked device were being announced as unread when the conversation
   was opened in WinZapp. WhatsApp's ``unreadCount`` only ever counts messages
   you *received*, but the separator was placed at ``len(displayable) -
   unread_count``, which counts your own messages too. See first_unread_index().

2. The separator vanished on a 2-second timer armed as soon as focus reached it,
   so it disappeared while the user was still sitting on it. It now goes away
   only once focus actually moves past it. See
   ConversationsPanel._should_dismiss_unread_separator().

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the method under test is exercised as a plain function — same
approach as tests/test_message_bookmarks.py.
"""

import pytest

from core.utils import first_unread_index, paginated_window, db_fetch_limit
from ui.conversations import ConversationsPanel


def _msg(mid, from_me=False):
    return {"key": {"id": mid, "fromMe": from_me}}


# ── Where the separator goes ────────────────────────────────────────────────


class TestFirstUnreadIndex:
    def test_no_unread_means_no_separator(self):
        assert first_unread_index([_msg("a"), _msg("b")], 0) == -1
        assert first_unread_index([_msg("a")], -3) == -1

    def test_all_incoming_behaves_like_the_old_arithmetic(self):
        msgs = [_msg("a"), _msg("b"), _msg("c"), _msg("d")]
        assert first_unread_index(msgs, 2) == 2

    def test_own_trailing_messages_are_not_counted_as_unread(self):
        """The reported case: two unread messages arrived, then the user replied
        twice from their phone. The separator must sit above the two *received*
        messages, not above their own replies."""
        msgs = [
            _msg("old"),
            _msg("unread-1"),
            _msg("unread-2"),
            _msg("mine-1", from_me=True),
            _msg("mine-2", from_me=True),
        ]
        idx = first_unread_index(msgs, 2)
        assert idx == 1
        assert msgs[idx]["key"]["id"] == "unread-1"
        # The old formula would have landed on the user's own first reply.
        assert len(msgs) - 2 == 3 and msgs[3]["key"]["fromMe"] is True

    def test_own_messages_interleaved_are_skipped(self):
        msgs = [
            _msg("old"),
            _msg("unread-1"),
            _msg("mine", from_me=True),
            _msg("unread-2"),
        ]
        assert first_unread_index(msgs, 2) == 1

    def test_a_conversation_of_only_own_messages_has_no_anchor(self):
        msgs = [_msg("a", from_me=True), _msg("b", from_me=True)]
        assert first_unread_index(msgs, 1) == -1

    def test_more_unread_than_loaded_history_has_no_anchor(self):
        assert first_unread_index([_msg("a"), _msg("b")], 5) == -1

    def test_non_dict_rows_are_ignored(self):
        """`displayable` can carry sentinels (separator/placeholder) that are
        dicts without a key, and defensive code elsewhere tolerates non-dicts."""
        msgs = [None, _msg("a"), {"_type": "unread_separator"}, _msg("b")]
        assert first_unread_index(msgs, 1) == 3
        assert first_unread_index(msgs, 2) == 2, "keyless sentinel counts as incoming"


# ── Pagination window vs. a large unread backlog ────────────────────────────


class TestPaginatedWindow:
    def test_short_history_is_never_paginated(self):
        assert paginated_window(total_len=50, limit=200, unread_sep_idx=-1) == (0, -1)

    def test_a_fully_read_conversation_respects_the_configured_limit(self):
        """No separator (-1) means nothing unread to protect — cut exactly at
        the configured page size, same as before this fix existed."""
        offset, sep = paginated_window(total_len=500, limit=200, unread_sep_idx=-1)
        assert offset == 300
        assert sep == -1

    def test_the_reported_case_230_unread_against_a_200_limit(self):
        """The separator sits 230 messages from the end — inside a plain
        200-message cut that would have dropped it (and every unread message
        after it) entirely. The window must widen to keep it."""
        total = 300
        sep_idx = total - 230  # 230 messages, including the separator, follow
        offset, sep = paginated_window(total_len=total, limit=200, unread_sep_idx=sep_idx)
        assert offset <= sep_idx, "the separator must stay inside the window"
        assert sep == sep_idx - offset
        assert sep >= 0

    def test_unread_backlog_smaller_than_the_limit_changes_nothing(self):
        """15 unread against a 200 limit — the old, unwidened cut already
        keeps the separator, so behaviour must be identical to before."""
        total = 500
        sep_idx = total - 15
        offset, sep = paginated_window(total_len=total, limit=200, unread_sep_idx=sep_idx)
        assert offset == total - 200
        assert sep == sep_idx - offset

    def test_unread_backlog_exactly_at_the_limit_is_the_boundary(self):
        total = 400
        sep_idx = total - 200
        offset, sep = paginated_window(total_len=total, limit=200, unread_sep_idx=sep_idx)
        assert offset == sep_idx
        assert sep == 0

    def test_widening_still_caps_at_the_full_history(self):
        """More unread than history even holds — the window can't widen past
        what actually exists."""
        offset, sep = paginated_window(total_len=100, limit=50, unread_sep_idx=0)
        assert offset == 0
        assert sep == 0


# ── How much history navigate_to_conversation() pulls from the DB ──────────


class TestDbFetchLimit:
    def test_unread_within_the_page_size_uses_the_configured_limit(self):
        assert db_fetch_limit(configured_limit=200, unread_count=15) == 250

    def test_zero_unread_uses_the_configured_limit(self):
        assert db_fetch_limit(configured_limit=200, unread_count=0) == 250

    def test_unread_beyond_the_page_size_widens_the_fetch(self):
        """The reported case: 350 unread against a 200-message page size —
        the plain limit would leave first_unread_index() unable to find the
        separator at all."""
        assert db_fetch_limit(configured_limit=200, unread_count=350) == 400

    def test_widened_fetch_is_capped(self):
        assert db_fetch_limit(configured_limit=200, unread_count=50000, cap=2000) == 2000

    def test_unread_exactly_at_the_page_size_changes_nothing(self):
        assert db_fetch_limit(configured_limit=200, unread_count=200) == 250


# ── When the separator goes away ────────────────────────────────────────────


class TestShouldDismissUnreadSeparator:
    dismiss = staticmethod(ConversationsPanel._should_dismiss_unread_separator)

    def test_no_separator_means_nothing_to_dismiss(self):
        assert self.dismiss(4, -1) is False

    def test_focus_above_the_separator_keeps_it(self):
        assert self.dismiss(1, 3) is False

    def test_landing_on_the_separator_itself_keeps_it(self):
        """populate_messages() parks focus exactly here when the conversation is
        opened — before the user has read anything."""
        assert self.dismiss(3, 3) is False

    def test_moving_one_past_the_separator_dismisses_it(self):
        assert self.dismiss(4, 3) is True

    def test_moving_far_past_the_separator_dismisses_it(self):
        assert self.dismiss(40, 3) is True

    def test_an_unfocused_list_never_dismisses(self):
        """GetFocusedItem() returns -1 when nothing is focused."""
        assert self.dismiss(-1, 3) is False

    def test_separator_at_row_zero(self):
        assert self.dismiss(0, 0) is False
        assert self.dismiss(1, 0) is True
