"""
WinZapp – Add Member to Group Dialog
=====================================
Lets the user select one or more contacts to add to a group.
"""

import threading
import wx
from core.utils import format_number


class AddMemberDialog(wx.Dialog):
    """
    Shows a list of all contacts. The user selects one or more and clicks
    "Add" to add them to the specified group.
    """

    def __init__(self, main_window, group_jid: str):
        self._mw       = main_window
        self._i18n     = main_window.i18n
        self._group_jid = group_jid

        super().__init__(
            main_window,
            title=self._i18n.t("add_member_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self._populate_contacts()
        self.SetMinSize((360, 400))
        self.SetSize((420, 500))
        self.CentreOnParent()

    def _build_ui(self):
        i18n  = self._i18n
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, label=i18n.t("add_member_title"))
        sizer.Add(label, 0, wx.ALL, 8)

        self._list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_HRULES
        )
        self._list.InsertColumn(0, i18n.t("conversations"), width=220)
        self._list.InsertColumn(1, i18n.t("phone_label"),   width=140)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        self._ok_btn  = wx.Button(self, wx.ID_OK,     label=i18n.t("add_member"))
        cancel_btn    = wx.Button(self, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._ok_btn.Bind(wx.EVT_BUTTON, self._on_add)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

    def _populate_contacts(self):
        """Fill the list with all available contacts."""
        self._contact_jids = []  # parallel list of JIDs
        for jid, contact in self._mw.contacts.items():
            if not jid or jid.endswith("@g.us"):
                continue
            name = contact.get("pushName") or format_number(jid)
            phone = format_number(jid)
            idx = self._list.GetItemCount()
            self._list.InsertItem(idx, name)
            self._list.SetItem(idx, 1, phone)
            self._contact_jids.append(jid)

    def _on_add(self, event):
        """Collect selected contacts and call the API."""
        selected_jids = []
        idx = -1
        while True:
            idx = self._list.GetNextItem(idx, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)
            if idx == -1:
                break
            if idx < len(self._contact_jids):
                selected_jids.append(self._contact_jids[idx])

        if not selected_jids:
            self.EndModal(wx.ID_CANCEL)
            return

        self._ok_btn.Disable()
        threading.Thread(
            target=self._do_add, args=(selected_jids,), daemon=True
        ).start()

    def _do_add(self, jids: list):
        ok, err = self._mw.add_group_members(self._group_jid, jids)
        wx.CallAfter(self._finish, ok, err)

    def _finish(self, ok: bool, err: str):
        i18n = self._i18n
        if ok:
            wx.MessageBox(
                i18n.t("add_member_success"),
                i18n.t("add_member_title"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.EndModal(wx.ID_OK)
        else:
            wx.MessageBox(
                i18n.t("add_member_error").format(error=err),
                i18n.t("add_member_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._ok_btn.Enable()


class SelectGroupDialog(wx.Dialog):
    """
    Shows a list of all group chats the user belongs to.
    The user picks one group to add a specific contact to.
    """

    def __init__(self, main_window, contact_jid: str, contact_name: str):
        self._mw           = main_window
        self._i18n         = main_window.i18n
        self._contact_jid  = contact_jid
        self._contact_name = contact_name

        super().__init__(
            main_window,
            title=self._i18n.t("select_group_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self._populate_groups()
        self.SetMinSize((360, 320))
        self.SetSize((400, 400))
        self.CentreOnParent()

    def _build_ui(self):
        i18n  = self._i18n
        sizer = wx.BoxSizer(wx.VERTICAL)

        label = wx.StaticText(self, label=i18n.t("select_group_title"))
        sizer.Add(label, 0, wx.ALL, 8)

        self._list = wx.ListCtrl(
            self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES
        )
        self._list.InsertColumn(0, i18n.t("conversations"), width=340)
        sizer.Add(self._list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        self._ok_btn = wx.Button(self, wx.ID_OK,     label=i18n.t("select_group"))
        cancel_btn   = wx.Button(self, wx.ID_CANCEL, label=i18n.t("cancel"))
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self._ok_btn.Bind(wx.EVT_BUTTON, self._on_select)
        cancel_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))

    def _populate_groups(self):
        """Fill the list with all group chats."""
        self._group_jids = []
        deleted = set(self._mw.settings.get("deleted_chats", []))
        for jid, chat in self._mw.chats.items():
            if not jid.endswith("@g.us") or jid in deleted:
                continue
            name = (
                self._mw._resolve_contact_name(chat)
                or self._mw.find_name_through_messages(chat)
                or chat.get("pushName", "")
                or jid.split("@")[0]
            )
            idx = self._list.GetItemCount()
            self._list.InsertItem(idx, name)
            self._group_jids.append(jid)

        if not self._group_jids:
            self._list.InsertItem(0, self._i18n.t("no_groups_available"))
            self._ok_btn.Disable()

    def _on_select(self, event):
        idx = self._list.GetFirstSelected()
        if idx == -1 or idx >= len(self._group_jids):
            return
        group_jid = self._group_jids[idx]
        self._ok_btn.Disable()
        threading.Thread(
            target=self._do_add, args=(group_jid,), daemon=True
        ).start()

    def _do_add(self, group_jid: str):
        ok, err = self._mw.add_group_members(group_jid, [self._contact_jid])
        wx.CallAfter(self._finish, ok, err)

    def _finish(self, ok: bool, err: str):
        i18n = self._i18n
        if ok:
            wx.MessageBox(
                i18n.t("add_member_success"),
                i18n.t("select_group_title"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            self.EndModal(wx.ID_OK)
        else:
            wx.MessageBox(
                i18n.t("add_member_error").format(error=err),
                i18n.t("select_group_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._ok_btn.Enable()
