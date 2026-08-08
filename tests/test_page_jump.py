"""Regression test: Page Up/Page Down in messages_list and conversations_list
(both plain wx.ListCtrl) only moved focus by a single row — functionally
indistinguishable from Up/Down — instead of paging by a screenful.

ConversationsPanel._page_jump_target() is the pure clamping logic behind the
fix; the wx.ListCtrl-touching wrapper (_jump_list_by) isn't unit-testable
without a running wx.App, per the project's convention (see
tests/test_reported_bugfixes.py) of extracting the pure decision instead.
"""

from ui.conversations import ConversationsPanel

target = ConversationsPanel._page_jump_target


class TestPageJumpTarget:
    def test_page_down_from_the_top_lands_15_rows_in(self):
        assert target(count=100, focused_idx=0, delta=15) == 15

    def test_page_up_from_row_20_lands_5_rows_in(self):
        assert target(count=100, focused_idx=20, delta=-15) == 5

    def test_page_up_clamps_at_the_first_row(self):
        assert target(count=100, focused_idx=10, delta=-15) == 0

    def test_page_down_clamps_at_the_last_row(self):
        assert target(count=20, focused_idx=10, delta=15) == 19

    def test_nothing_focused_treats_it_as_row_zero(self):
        assert target(count=100, focused_idx=-1, delta=15) == 15

    def test_empty_list_has_no_target(self):
        assert target(count=0, focused_idx=-1, delta=15) == -1

    def test_short_list_page_down_still_clamps(self):
        assert target(count=5, focused_idx=2, delta=15) == 4
