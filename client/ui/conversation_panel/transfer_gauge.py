"""The media transfer gauge that keeps screen-reader focus while it moves.

Moved verbatim out of ui/conversations.py, which re-exports every name.
"""

import wx


class _FocusedTransferGaugeAccessible(wx.Accessible):
    """Expose value changes to screen readers only while the gauge has focus."""

    def __init__(self, gauge):
        super().__init__()
        self._gauge = gauge

    def GetState(self, childId):
        state = wx.ACC_STATE_SYSTEM_FOCUSABLE
        if self._gauge.HasFocus():
            state |= wx.ACC_STATE_SYSTEM_FOCUSED
        else:
            # NVDA's native ProgressBar handler deliberately ignores value
            # changes carrying INVISIBLE/OFFSCREEN. The gauge remains visible
            # on screen; only unsolicited accessibility updates are suppressed.
            state |= wx.ACC_STATE_SYSTEM_INVISIBLE
        return (wx.ACC_OK, state)


class _FocusedTransferGauge(wx.Gauge):
    """Native gauge reachable by Tab, with focus-scoped NVDA progress output."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.SetAccessible(_FocusedTransferGaugeAccessible(self))
        self.Bind(wx.EVT_LEFT_DOWN, self._focus_from_mouse)

    def AcceptsFocus(self):
        return True

    def AcceptsFocusFromKeyboard(self):
        return True

    def _focus_from_mouse(self, event):
        self.SetFocus()
        event.Skip()
