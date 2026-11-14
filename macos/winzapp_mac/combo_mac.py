"""Read-only combo boxes become pop-up buttons, as on every Mac app.

WinZapp uses wx.ComboBox(style=wx.CB_READONLY) for pick-from-a-list
controls (language, country, audio devices, sound pack...). On macOS that is
an NSComboBox — an editable text field with a list — which VoiceOver
announces as a combo box and which does not behave like the Mac's
pick-from-a-list control, the pop-up button (NSPopUpButton = wx.Choice).

MacPopupCombo is a wx.Choice that answers the wx.ComboBox calls WinZapp
makes (GetValue/SetValue/...) and emits the events a read-only combo box
emits on a user's choice (EVT_COMBOBOX, then EVT_TEXT), so handlers bound
to those keep working. Editable combo boxes stay combo boxes.
"""

import wx

_OrigComboBox = wx.ComboBox


class MacPopupCombo(wx.Choice):
    def __init__(self, parent, id=wx.ID_ANY, value="", pos=wx.DefaultPosition,
                 size=wx.DefaultSize, choices=(), style=0,
                 validator=wx.DefaultValidator, name="comboBox"):
        super().__init__(parent, id, pos, size, list(choices or []),
                         style & wx.CB_SORT and wx.CB_SORT or 0, validator, name)
        if value:
            self.SetStringSelection(value)
        self.Bind(wx.EVT_CHOICE, self._relay)

    def _relay(self, evt):
        for etype in (wx.wxEVT_COMBOBOX, wx.wxEVT_TEXT):
            e = wx.CommandEvent(etype, self.GetId())
            e.SetEventObject(self)
            e.SetInt(self.GetSelection())
            e.SetString(self.GetStringSelection())
            self.GetEventHandler().ProcessEvent(e)
        evt.Skip()

    # --- wx.ComboBox / wx.TextEntry surface --------------------------------
    def GetValue(self):
        return self.GetStringSelection()

    def SetValue(self, value):
        if not self.SetStringSelection(value) and value == "":
            self.SetSelection(wx.NOT_FOUND)

    ChangeValue = SetValue

    def IsEditable(self):
        return False

    def SetEditable(self, editable):
        pass

    def SelectAll(self):
        pass

    def SetInsertionPoint(self, pos):
        pass

    def SetInsertionPointEnd(self):
        pass

    def GetInsertionPoint(self):
        return 0

    def SetHint(self, hint):
        return False

    def AutoComplete(self, *a, **k):
        return False

    def Popup(self):
        pass

    def Dismiss(self):
        pass

    def IsListEmpty(self):
        return self.GetCount() == 0

    def IsTextEmpty(self):
        return not self.GetStringSelection()


class _ComboBoxFactory(type):
    """wx.ComboBox(...) hands back a MacPopupCombo for read-only styles."""

    def __call__(cls, parent, id=wx.ID_ANY, value="", pos=wx.DefaultPosition,
                 size=wx.DefaultSize, choices=(), style=0,
                 validator=wx.DefaultValidator, name="comboBox"):
        if style & wx.CB_READONLY:
            return MacPopupCombo(parent, id, value, pos, size, choices, style, validator, name)
        return _OrigComboBox(parent, id, value, pos, size, list(choices or []), style, validator, name)

    def __instancecheck__(cls, obj):
        return isinstance(obj, (_OrigComboBox, MacPopupCombo))


class ComboBox(metaclass=_ComboBoxFactory):
    pass


def install():
    wx.ComboBox = ComboBox
