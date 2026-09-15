"""Confirmation shown before clearing one or more conversations.

WhatsApp Web asks "clear this chat?" together with a "keep starred messages"
checkbox, ticked by default. WinZapp used to ask a bare yes/no and always kept
the starred ones; the choice now belongs to the user, same as on WhatsApp Web.

Built from plain wx controls on purpose. `wx.RichMessageDialog.ShowCheckBox()`
was tried first: on Windows it is the TaskDialog's verification checkbox, and
NVDA read it as "caixa de seleção, não marcado, somente leitura" — wrong state
and not operable. A real `wx.CheckBox` is read and toggled like any other.
"""

import wx


class ClearChatConfirmDialog(wx.Dialog):
    def __init__(self, parent, message, title, keep_starred_label, yes_label, no_label):
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE)
        sizer = wx.BoxSizer(wx.VERTICAL)

        text = wx.StaticText(self, label=message)
        text.Wrap(self.FromDIP(380))
        sizer.Add(text, 0, wx.ALL, 12)

        self._keep_starred = wx.CheckBox(self, label=keep_starred_label)
        self._keep_starred.SetValue(True)
        sizer.Add(self._keep_starred, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        yes_btn = wx.Button(self, wx.ID_YES, label=yes_label)
        no_btn = wx.Button(self, wx.ID_NO, label=no_label)
        btn_sizer.Add(yes_btn, 0, wx.RIGHT, 4)
        btn_sizer.Add(no_btn, 0)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)
        self.SetSizer(sizer)

        yes_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_YES))
        no_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_NO))
        # Esc / Alt+F4 answer "no", as the wx.MessageBox this replaces did.
        self.SetEscapeId(wx.ID_NO)
        # Yes stays the Enter default, also as wx.MessageBox's YES_NO did, so
        # a user who confirms with Enter keeps working exactly as before.
        yes_btn.SetDefault()
        # Focus starts on Yes, not on the checkbox wx would pick by creation
        # order. On the checkbox, a user who confirms message boxes with Space
        # out of habit would untick "keep starred" and then Enter would clear
        # them on the phone too — the one irreversible outcome here. On Yes,
        # Enter and Space both behave exactly as the old wx.MessageBox did,
        # and the option is one Tab away (Tab order: checkbox, Yes, No).
        yes_btn.SetFocus()

        self.Fit()
        self.Centre()

    def keep_starred(self) -> bool:
        return bool(self._keep_starred.GetValue())


def confirm_clear_chat(parent, message: str, title: str, keep_starred_label: str,
                       *, yes_label: str, no_label: str):
    """Ask whether to clear, and whether to keep the starred messages.

    Returns `(confirmed, keep_starred)`. `keep_starred` is only meaningful
    when `confirmed` is True.
    """
    dlg = ClearChatConfirmDialog(parent, message, title, keep_starred_label, yes_label, no_label)
    try:
        confirmed = dlg.ShowModal() == wx.ID_YES
        keep_starred = dlg.keep_starred()
    finally:
        dlg.Destroy()
    return confirmed, keep_starred
