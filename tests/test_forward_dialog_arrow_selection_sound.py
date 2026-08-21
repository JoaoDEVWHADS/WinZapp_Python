"""Regression test for the arrow-key handling inside
ConversationsPanel._on_menu_forward()'s contact picker.

Reported live: arrowing through the forward dialog's contact list gave no
audible cue for which contacts were already part of the multi-selection.
Root cause: plain Up/Down is remapped onto the raw Win32 LB_SETCARETINDEX
message so the native wx.LB_EXTENDED behavior (Up/Down both moves focus AND
collapses the selection) doesn't kick in — but that remap moves the caret
without touching the listbox's own selection state at all, so it never
fires the selection-changed accessibility event NVDA would otherwise say
"selected" from. The messages/conversations lists play selection_sound
whenever a row enters the selection; this dialog's arrow handling needs the
same cue when arrowing lands on an ALREADY-selected row, since nothing else
signals that.

_on_menu_forward() builds this whole picker (including the key handler) as
a deeply nested closure inside a live wx.Dialog/wx.ListBox interaction —
driving it end-to-end needs a running modal dialog, which is impractical to
unit test (same reasoning already applied to the dialog's other keyboard
logic). This is a source inspection test instead, pinning the actual fix:
selection_sound.play() gated on the landed-on row being selected, inside
the arrow-key branch specifically.
"""

import inspect

from ui.conversations import ConversationsPanel


def _forward_dialog_source():
    return inspect.getsource(ConversationsPanel._on_menu_forward)


class TestArrowKeyPlaysSelectionSoundOnAnAlreadySelectedRow:
    def test_the_arrow_branch_checks_is_selected_before_playing_the_sound(self):
        src = _forward_dialog_source()
        arrow_branch_at = src.index("wx.WXK_NUMPAD_DOWN)\n                    and not ctrl and not shift):")
        next_branch_at = src.index("if shift and key in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN):")
        arrow_branch = src[arrow_branch_at:next_branch_at]

        assert "_lst_is_selected(new_caret)" in arrow_branch
        assert "self.selection_sound.play()" in arrow_branch

    def test_the_sound_call_is_conditional_not_unconditional(self):
        """Playing it on every arrow press (selected or not) would be just
        as unhelpful as never playing it — it has to distinguish."""
        src = _forward_dialog_source()
        arrow_branch_at = src.index("wx.WXK_NUMPAD_DOWN)\n                    and not ctrl and not shift):")
        next_branch_at = src.index("if shift and key in (wx.WXK_DOWN, wx.WXK_NUMPAD_DOWN):")
        arrow_branch = src[arrow_branch_at:next_branch_at]

        guard_at = arrow_branch.index("if _lst_is_selected(new_caret):")
        play_at = arrow_branch.index("self.selection_sound.play()")
        assert guard_at < play_at
