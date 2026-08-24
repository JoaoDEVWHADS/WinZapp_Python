"""Regression test for ConversationsPanel._on_menu_forward()'s contact
picker switching from a native multi-select wx.LB_EXTENDED listbox to a
single-select wx.LB_SINGLE one, with the actual multi-select tracked
entirely in application code (selected_jids), same as everywhere else in
the app (self.selected_messages/self.selected_chats).

Reported live: an earlier version kept wx.LB_EXTENDED and drove its own
native multi-selection by hand through raw Win32 messages (LB_SETSEL/
LB_GETSEL/LB_SETCARETINDEX/LB_GETCARETINDEX), remapping arrow keys and
letter type-ahead so they wouldn't trigger the native "Up/Down/type-ahead
collapses an extended selection to one row" behavior. That meant two
independent copies of "what's selected" — the native LB_GETSEL state and
this dialog's own bookkeeping — that could drift out of sync with each
other ("comportamentos estranhos"). Two follow-up bug reports (arrows
giving no selection-sound cue, then letter navigation silently dropping the
selection) were both symptoms of that same two-selections problem, not
independent bugs each needing their own fix.

LB_SINGLE removes the native multi-select outright: native selection is
only ever "which row has keyboard focus" (same concept as messages_list/
conversations_list's GetFocusedItem()), so arrows and letter type-ahead are
simply left at their default native behavior — there is nothing left for
them to collide with, and nothing to keep in sync.

_on_menu_forward() builds this whole picker as a deeply nested closure
inside a live wx.Dialog/wx.ListBox interaction — driving it end-to-end
needs a running modal dialog, impractical to unit test (same reasoning
already applied to this dialog's other keyboard logic in this codebase).
This is a source inspection test instead, pinning down that the redesign
actually landed: only ONE selection mechanism exists in the method.
"""

import inspect

from ui.conversations import ConversationsPanel


def _forward_dialog_source():
    return inspect.getsource(ConversationsPanel._on_menu_forward)


class TestOnlyOneSelectionMechanismExists:
    def test_the_listbox_is_single_selection(self):
        src = _forward_dialog_source()
        assert "style=wx.LB_SINGLE" in src
        assert "style=wx.LB_EXTENDED" not in src

    def test_no_raw_win32_listbox_messages_remain(self):
        """The whole reason for the raw LB_SETSEL/LB_GETSEL/LB_SETCARETINDEX/
        LB_GETCARETINDEX machinery was keeping a second, hand-rolled
        selection in sync with the native one — gone along with LB_EXTENDED,
        there's nothing left needing ctypes/SendMessageW at all."""
        src = _forward_dialog_source()
        assert "ctypes" not in src
        assert "SendMessageW" not in src
        assert "LB_SETSEL" not in src
        assert "LB_SETCARETINDEX" not in src

    def test_arrow_keys_and_letters_are_not_intercepted(self):
        """Both used to be remapped by hand specifically to avoid colliding
        with the native extended-selection widget; with LB_SINGLE there's no
        longer anything to avoid colliding with, so they're left native."""
        src = _forward_dialog_source()
        assert "wx.WXK_UP" not in src
        assert "wx.WXK_NUMPAD_UP" not in src

    def test_multiselect_is_tracked_by_jid_identity_in_one_place(self):
        src = _forward_dialog_source()
        assert "selected_jids = set()" in src
        # Only Ctrl+Space / Ctrl+Shift+Space / Shift+Down / Shift+Home /
        # Shift+End still intercept a key at all — native handling covers
        # everything else via a bare event.Skip() at the end of the handler.
        start = src.index("def _on_list_key_down(event):")
        end = src.index("lst.Bind(wx.EVT_KEY_DOWN, _on_list_key_down)")
        key_handler = src[start:end]
        assert key_handler.count("event.Skip()") == 1
        assert key_handler.rstrip().endswith("event.Skip()  # Arrows, letter type-ahead, everything else: native behavior")


class TestLandingOnAnAlreadySelectedRowStillCuesTheUser:
    """The accessibility need behind the arrow-key follow-up fix (audible
    cue when navigation lands on a selected row) is preserved — just moved
    onto the native wx.EVT_LISTBOX event, which fires for every native focus
    change (arrow keys, letter type-ahead, mouse click) without this dialog
    having to reimplement any of that navigation by hand."""

    def test_a_listbox_select_handler_is_bound(self):
        src = _forward_dialog_source()
        assert "lst.Bind(wx.EVT_LISTBOX, _on_listbox_select)" in src

    def test_the_handler_checks_selected_jids_before_playing_the_sound(self):
        src = _forward_dialog_source()
        start = src.index("def _on_listbox_select(event):")
        end = src.index("lst.Bind(wx.EVT_LISTBOX, _on_listbox_select)")
        handler = src[start:end]
        assert "jid in selected_jids" in handler
        assert "self.selection_sound.play()" in handler
        # Must not swallow the event — native focus movement still has to
        # actually happen.
        assert "event.Skip()" in handler


class TestSelectionSurvivesSearchFiltering:
    def test_on_search_rebuilds_from_row_text_not_a_bare_name_list(self):
        """lst.Set(_filtered_names) would silently drop every marker on the
        already-selected rows the moment the user typed anything — the
        rebuild has to run each name back through _row_text() (which
        consults selected_jids) instead."""
        src = _forward_dialog_source()
        start = src.index("def _on_search(event):")
        end = src.index("search_field.Bind(wx.EVT_TEXT, _on_search)")
        search_fn = src[start:end]
        assert "lst.Set([_row_text(i) for i in range(len(_filtered_names))])" in search_fn
