"""Issue #69: the Emoji button used to bake its shortcut into the label
("Emoji (Ctrl+.)"), which NVDA's "report shortcut key" (Shift+Numpad2) reads
from the MSAA KeyboardShortcut property, not from the accessible name — so it
worked for Add Attachment/Record Voice Message (both already exposed via a
wx.Accessible subclass) but not Emoji. AccessibleEmojiButton closes that gap;
this pins the value it reports so a future edit can't silently drop it.
"""

from ui.accessible import AccessibleEmojiButton


def test_reports_ctrl_dot_as_the_shortcut():
    import wx

    acc = AccessibleEmojiButton()

    assert acc.GetKeyboardShortcut(0) == (wx.ACC_OK, "Ctrl+.")
