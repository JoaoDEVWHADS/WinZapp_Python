"""
new_group.py — WinZapp "Novo grupo" dialog.

Lets the user create a new WhatsApp group by:
  1. Choosing a group name.
  2. Selecting participants from a saved-contact checklist.
  3. Optionally adding an extra phone number not in the contacts list.

Calls the Evolution API POST /group/create/{instance} endpoint.
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
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._contact_jids: list = []
        self._build_ui(i18n)
        self.SetMinSize((440, 400))
        self.SetSize((460, 520))
        self.CentreOnParent()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self, i18n):
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Group name
        sizer.Add(
            wx.StaticText(panel, label=i18n.t("group_name")),
            0, wx.LEFT | wx.TOP, 10,
        )
        self._name_field = wx.TextCtrl(panel, style=wx.TE_DONTWRAP)
        sizer.Add(self._name_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        # Participants checklist from saved contacts
        sizer.Add(
            wx.StaticText(panel, label=i18n.t("group_contacts_label")),
            0, wx.LEFT | wx.TOP, 10,
        )

        contacts = self._mw.contacts
        contact_labels = []
        self._contact_jids = []
        for jid, contact in contacts.items():
            name = (
                contact.get("name") or contact.get("fullName")
                or contact.get("verifiedName") or contact.get("pushName")
                or jid
            )
            contact_labels.append(name)
            self._contact_jids.append(jid)

        if contact_labels:
            self._contacts_listbox = wx.CheckListBox(
                panel, choices=contact_labels, style=wx.LB_NEEDED_SB,
            )
            sizer.Add(
                self._contacts_listbox, 1,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10,
            )
        else:
            no_contacts_label = wx.StaticText(
                panel, label=i18n.t("group_no_contacts")
            )
            sizer.Add(no_contacts_label, 0, wx.LEFT | wx.TOP, 10)
            self._contacts_listbox = None

        # Extra phone number (for numbers not in contacts)
        sizer.Add(
            wx.StaticText(panel, label=i18n.t("group_extra_number_label")),
            0, wx.LEFT | wx.TOP, 10,
        )
        self._extra_number_field = wx.TextCtrl(panel, style=wx.TE_DONTWRAP)
        sizer.Add(
            self._extra_number_field, 0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10,
        )

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

        # Gather checked contacts
        numbers: list = []
        if self._contacts_listbox is not None:
            for idx in range(self._contacts_listbox.GetCount()):
                if self._contacts_listbox.IsChecked(idx):
                    jid = self._contact_jids[idx]
                    digits = re.sub(r"\D", "", jid.split("@")[0])
                    if digits:
                        numbers.append(digits)

        # Gather extra number field
        extra_raw = self._extra_number_field.GetValue()
        for part in re.split(r"[,\n]", extra_raw):
            digits = re.sub(r"\D", "", part.strip())
            if len(digits) >= 7:
                numbers.append(digits)

        # Deduplicate while preserving order
        seen: set = set()
        unique_numbers = []
        for n in numbers:
            if n not in seen:
                seen.add(n)
                unique_numbers.append(n)

        if not unique_numbers:
            wx.MessageBox(
                i18n.t("group_participants_label"),
                i18n.t("app_name"),
                wx.OK | wx.ICON_WARNING,
                self,
            )
            if self._contacts_listbox is not None:
                self._contacts_listbox.SetFocus()
            else:
                self._extra_number_field.SetFocus()
            return

        # Disable OK to prevent double-click
        self.FindWindow(wx.ID_OK).Disable()

        def _run():
            ok, result = self._mw.create_group(name, unique_numbers)
            wx.CallAfter(self._on_create_done, ok, result)

        threading.Thread(target=_run, daemon=True).start()

    def _on_create_done(self, ok: bool, result: str):
        i18n = self._mw.i18n
        if ok:
            self.EndModal(wx.ID_OK)
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
