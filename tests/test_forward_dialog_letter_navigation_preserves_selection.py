"""Regression test for letter/digit type-ahead inside
ConversationsPanel._on_menu_forward()'s contact picker.

Reported live: pressing a letter to jump to a contact by name broke the
existing multi-selection and dropped whatever had been Ctrl+Space-selected
before, and never applied the "selecionado" text marker to the row it
landed on. Root cause: unhandled letter keys fell through to event.Skip(),
letting native wx.LB_EXTENDED handle the keystroke — and native type-ahead
in an extended-selection listbox moves focus AND collapses the selection to
just that one row, the identical root cause the arrow-key handling right
above it in the same method was already fixed for (see
test_forward_dialog_arrow_selection_sound.py). Letters now move the caret
by hand, the same LB_SETCARETINDEX-only path arrows use, and never fall
through to native handling — so the selection is never touched by letter
navigation at all, matching the reported ideal directly rather than trying
to patch native selection changes after the fact.

Source inspection test, same reasoning as the arrow-key one: driving the
picker end-to-end needs a live modal wx.Dialog/wx.ListBox interaction.
"""

import inspect

from ui.conversations import ConversationsPanel


def _forward_dialog_source():
    return inspect.getsource(ConversationsPanel._on_menu_forward)


class TestLetterNavigationNeverTouchesSelection:
    def _letter_branch(self):
        src = _forward_dialog_source()
        start = src.index("if not ctrl and 32 < key < 127:")
        end = src.index("event.Skip()  # Ctrl+Arrow, everything else: native behavior")
        return src[start:end]

    def test_the_letter_branch_only_moves_the_caret(self):
        branch = self._letter_branch()
        assert "_lst_set_caret(idx)" in branch
        # Never calls the selection-mutating helper — this is the whole point.
        assert "_lst_set_selected(" not in branch

    def test_the_letter_branch_never_falls_through_to_native_handling(self):
        """A bare `return` (not `event.Skip()`) regardless of whether a
        match was found — letting it fall through to native type-ahead is
        exactly the collapsed-selection bug being fixed."""
        branch = self._letter_branch()
        assert "event.Skip()" not in branch
        assert branch.rstrip().endswith("return  # suppressed regardless of a match — never fall through to native")

    def test_matching_is_done_against_the_clean_name_not_the_marked_up_display_text(self):
        """_filtered_names holds plain contact names; the "selecionado"
        marker is only ever applied to what's shown in the listbox
        (_row_text/_refresh_row), never mixed back into _filtered_names —
        matching against the marked-up text would break type-ahead for any
        already-selected contact whose name doesn't start with the marker
        word."""
        branch = self._letter_branch()
        assert "_filtered_names[idx].lower().startswith(char)" in branch
