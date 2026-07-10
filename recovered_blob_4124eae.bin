"""
WinZapp – Attach Contact Dialog
================================
Modal dialog that lets the user select a contact from the contacts list
to attach to an outgoing message.

The dialog presents a two-column ListCtrl (name / phone) populated from
``main_window.contacts``.  On confirmation, :attr:`selected_contact` is
set to the chosen contact dict (keyed by remoteJid) and the dialog
returns ``wx.ID_OK``.
"""

import wx
from core.utils import format_number


class AttachContactDialog(wx.Dialog):
    """
    Shows the contacts list and returns the chosen contact on OK.

    Parameters
    ----------
    main_window : MainWindow
    """

    def __init__(self, main_window):
        self._mw = main_window
        i18n = main_window.i18n
        super().__init__(
            main_window,
            title=i18n.t("attach_contact_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.selected_contact: dict | None = None
        self._contacts_list: list = []   # parallel to list rows

        self._build_ui()
        self.SetSize((420, 440))
        self.CentreOnParent()

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        i18n = self._mw.i18n
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._list = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._list.InsertColumn(0, i18n.t("conversations"), width=200)
        self._list.InsertColumn(1, i18n.t("phone_label"), width=160)
        self._list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_activate)
        sizer.Add(self._list, 1, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        ok_btn = wx.Button(panel, wx.ID_OK, label=i18n.t("send_attachment"))
        ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.RIGHT | wx.BOTTOM, 8)

        panel.SetSizer(sizer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(dlg_sizer)

        # Populate
        contacts = self._mw.contacts
        if not contacts:
            self._list.Append((i18n.t("no_contacts"), ""))
        else:
            for jid, contact in contacts.items():
                name = contact.get("pushName") or format_number(jid)
                self._list.Append((name, format_number(jid)))
                self._contacts_list.append({**contact, "remoteJid": jid})
            if self._list.GetItemCount() > 0:
                self._list.Focus(0)
                self._list.Select(0)

    # ── Events ──────────────────────────────────────────────────────────────

    def _on_activate(self, event):
        self._on_ok(event)

    def _on_ok(self, event):
        idx = self._list.GetFirstSelected()
        if idx < 0 or idx >= len(self._contacts_list):
            return
        self.selected_contact = self._contacts_list[idx]
        self.EndModal(wx.ID_OK)
