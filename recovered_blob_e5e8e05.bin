"""
new_group.py — WinZapp "Novo grupo" dialog.

Lets the user create a new WhatsApp group with a name and a list of
participant phone numbers (comma-separated).  Calls the Evolution API
POST /group/create/{instance} endpoint.
"""

import re
import threading
import wx


class NewGroupDialog(wx.Dialog):
    """Dialog for creating a new WhatsApp group."""

    def __init__(self, main_window, parent=None):
        self._mw = main_window
        i18n = main_window.i18n
        super().__init__(
            parent or main_window,
            title=i18n.t("new_group_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._build_ui(i18n)
        self.SetMinSize((420, -1))
        self.Fit()
        self.CentreOnParent()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, i18n):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Group name
        sizer.Add(wx.StaticText(panel, label=i18n.t("group_name")), 0,
                  wx.LEFT | wx.TOP, 10)
        self._name_field = wx.TextCtrl(panel, style=wx.TE_DONTWRAP)
        sizer.Add(self._name_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Participants
        sizer.Add(wx.StaticText(panel, label=i18n.t("group_participants_label")), 0,
                  wx.LEFT | wx.TOP, 10)
        self._participants_field = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_DONTWRAP, size=(-1, 80)
        )
        sizer.Add(self._participants_field, 0,
                  wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Buttons
        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn     = wx.Button(panel, wx.ID_OK,     label=i18n.t("create_group"))
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 10)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)

        ok_btn.Bind(wx.EVT_BUTTON, self._on_create)
        self._name_field.SetFocus()

    # ── Create group ──────────────────────────────────────────────────────────

    def _on_create(self, event):
        i18n = self._mw.i18n
        name = self._name_field.GetValue().strip()
        if not name:
            wx.MessageBox(
                i18n.t("group_name"),
                i18n.t("app_name"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            self._name_field.SetFocus()
            return

        raw_parts = self._participants_field.GetValue()
        # Accept comma or newline separated numbers
        numbers = [
            re.sub(r"\D", "", p.strip())
            for p in re.split(r"[,\n]", raw_parts)
        ]
        numbers = [n for n in numbers if len(n) >= 7]

        if not numbers:
            wx.MessageBox(
                i18n.t("group_participants_label"),
                i18n.t("app_name"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            self._participants_field.SetFocus()
            return

        # Disable the OK button to prevent double-click
        self.FindWindow(wx.ID_OK).Disable()

        def _run():
            ok, result = self._mw.create_group(name, numbers)
            wx.CallAfter(self._on_create_done, ok, result)

        threading.Thread(target=_run, daemon=True).start()

    def _on_create_done(self, ok: bool, result: str):
        i18n = self._mw.i18n
        if ok:
            self.EndModal(wx.ID_OK)
            # Navigate to the new group if we have its JID
            if result and result.endswith("@g.us"):
                mw   = self._mw
                chat = mw.chats.get(result) or {"remoteJid": result}
                wx.CallAfter(mw.conversations_panel.navigate_to_conversation, chat)
        else:
            wx.MessageBox(
                i18n.t("create_group_error").format(error=result),
                i18n.t("app_name"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            btn = self.FindWindow(wx.ID_OK)
            if btn:
                btn.Enable()
