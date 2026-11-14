"""The transcription result window, built for real.

Construction is the part the stub tests cannot see: where the focus starts,
whether the caveats field exists only when there are caveats, and that Escape
reaches the Close button. Builds a real wx.Dialog, so it carries the `wxgui`
marker and runs only where that is allowed (CI) — never on the machine of the
blind developers who maintain this, where a dialog taking focus has crashed
the screen reader.
"""

import pytest
import wx

from tests.conftest import destroy_now, hidden_frame
from ui.dialogs.transcription_result import TranscriptionResultDialog

# Creates a REAL top-level wx dialog - see the wxgui marker in pytest.ini.
pytestmark = pytest.mark.wxgui


class _I18n:
    def t(self, key):
        return key


class _Speech:
    def output(self, text, interrupt=False):
        pass


def _main_window():
    window = hidden_frame()
    window.i18n = _I18n()
    window.speak_output = _Speech()
    window.settings = {}
    return window


def test_the_fields_are_read_only_and_escape_is_close(wx_app):
    window = _main_window()
    try:
        dialog = TranscriptionResultDialog(window, window, "t", "texto", notes=["aviso"])
        try:
            assert dialog._text_field.IsEditable() is False
            assert dialog._close_btn.GetId() == wx.ID_CANCEL
            assert dialog._notes_field is not None
            assert dialog._notes_field.GetValue() == "aviso"
            assert dialog._notes_field.IsEditable() is False
        finally:
            dialog.Destroy()
    finally:
        destroy_now(window)


def test_no_notes_field_without_notes(wx_app):
    window = _main_window()
    try:
        dialog = TranscriptionResultDialog(window, window, "t", "texto")
        try:
            assert dialog._notes_field is None
            assert dialog._text_field.GetValue() == "texto"
        finally:
            dialog.Destroy()
    finally:
        destroy_now(window)


def test_the_focus_starts_on_the_text_at_its_first_character(wx_app, monkeypatch):
    """Where the focus starts, as the module docstring promises to check.

    Asked of SetFocus() itself rather than of wx.Window.FindFocus(): this
    dialog is never shown here (it is built on an off-screen parent and
    destroyed unshown), and which control Windows reports as focused inside a
    window that was never activated depends on the desktop, not on the code.
    What the code decides is which control it hands the focus to, last — and
    that it is the text, not the caveats above it, with the caret at the
    start so the screen reader reads the first line.
    """
    focused = []
    real_set_focus = wx.TextCtrl.SetFocus

    def _recording_set_focus(self):
        focused.append(self.GetId())
        return real_set_focus(self)

    monkeypatch.setattr(wx.TextCtrl, "SetFocus", _recording_set_focus)
    window = _main_window()
    try:
        dialog = TranscriptionResultDialog(window, window, "t", "texto", notes=["aviso"])
        try:
            assert focused and focused[-1] == dialog._text_field.GetId()
            assert dialog._notes_field.GetId() not in focused
            assert dialog._text_field.GetInsertionPoint() == 0
        finally:
            dialog.Destroy()
    finally:
        destroy_now(window)
