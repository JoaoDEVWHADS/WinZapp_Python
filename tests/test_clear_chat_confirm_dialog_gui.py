"""Builds the real ClearChatConfirmDialog and checks what a screen-reader user
depends on — the parts the fake in test_clear_chat_confirm_dialog.py cannot see.

The dialog replaced wx.RichMessageDialog.ShowCheckBox(), whose TaskDialog
checkbox NVDA read as "not checked, read only". So: a real, ticked
wx.CheckBox; Tab order text -> checkbox -> Yes -> No; Esc answers No; Enter
answers Yes, as the wx.MessageBox before it did.
"""

import pytest
import wx

from tests.conftest import hidden_frame
from ui.dialogs.clear_chat_confirm import ClearChatConfirmDialog

# Creates a REAL top-level wx dialog - see the wxgui marker in pytest.ini.
pytestmark = pytest.mark.wxgui


def _build():
    frame = hidden_frame()
    dlg = ClearChatConfirmDialog(frame, "msg", "title", "keep", "&Sim", "&Não")
    return frame, dlg


def test_controls_are_plain_and_in_tab_order(wx_app):
    frame, dlg = _build()
    try:
        children = list(dlg.GetChildren())
        assert isinstance(children[0], wx.StaticText)
        assert isinstance(children[1], wx.CheckBox)
        assert isinstance(children[2], wx.Button) and children[2].GetId() == wx.ID_YES
        assert isinstance(children[3], wx.Button) and children[3].GetId() == wx.ID_NO
        assert children[1].IsEnabled()
    finally:
        dlg.Destroy()
        frame.Destroy()


def test_keep_starred_starts_ticked(wx_app):
    frame, dlg = _build()
    try:
        assert dlg.keep_starred() is True
    finally:
        dlg.Destroy()
        frame.Destroy()


def test_escape_answers_no_and_enter_answers_yes(wx_app):
    frame, dlg = _build()
    try:
        assert dlg.GetEscapeId() == wx.ID_NO
        assert dlg.GetDefaultItem().GetId() == wx.ID_YES
    finally:
        dlg.Destroy()
        frame.Destroy()
