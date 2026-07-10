"""
WinZapp – Conversation / Group Data Dialog
==========================================
Opens a modal dialog showing WhatsApp-style information about a chat.

* For personal chats  → a read-only text control with profile data.
* For groups          → a wx.Notebook with three tabs:
    – Overview        (name, description, creation date, size)
    – Participants    (wx.ListCtrl with name / phone / admin flag)
    – Media           (count of locally-stored media files)

Profile / group data is fetched from the Evolution API in a background
thread after the dialog opens; the controls are updated via wx.CallAfter.
Screen-reader accessibility is achieved through standard wxPython controls
and proper label association — no visual-only information is presented.
"""

import os
import threading
from datetime import datetime
import wx
import wx.adv
from core.utils import format_number
from app_paths import data_path


def _fmt_ts(ts, i18n):
    """Format a Unix timestamp to a localised date string."""
    if not ts:
        return ""
    try:
        dt = datetime.fromtimestamp(int(ts))
        return dt.strftime(i18n.t("datetime_fmt"))
    except Exception:
        return str(ts)


class ConversationDataDialog(wx.Dialog):
    """
    Shows conversation or group metadata in an accessible modal dialog.

    Parameters
    ----------
    main_window : MainWindow
    chat        : dict  – the chat entry from main_window.chats
    """

    def __init__(self, main_window, chat):
        self._mw   = main_window
        self._chat = chat
        self._i18n = main_window.i18n

        jid  = chat.get("remoteJid", "")
        name = (
            main_window._resolve_contact_name(chat)
            or main_window.find_name_through_messages(chat)
            or chat.get("pushName", "")
            or format_number(jid)
        )
        self._jid    = jid
        self._name   = name
        self._is_group = jid.endswith("@g.us")

        title_key  = "group_data" if self._is_group else "conversation_data"
        dlg_title  = f"{name} | {self._i18n.t(title_key)}"

        super().__init__(
            main_window, title=dlg_title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui()
        self.SetSize((500, 480))
        self.CentreOnParent()

        # Fetch data in background after the dialog is shown.
        threading.Thread(target=self._fetch_data, daemon=True).start()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        # Back / Close button (at the top, as the user requested)
        back_btn = wx.Button(panel, label=self._i18n.t("back_btn"))
        back_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        outer.Add(back_btn, 0, wx.ALL, 8)

        if self._is_group:
            self._build_group_ui(panel, outer)
        else:
            self._build_personal_ui(panel, outer)

        panel.SetSizer(outer)
        dlg_sizer = wx.BoxSizer(wx.VERTICAL)
        dlg_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(dlg_sizer)

    def _build_personal_ui(self, panel, outer):
        """Single read-only TextCtrl with profile lines."""
        info_label = wx.StaticText(
            panel, label=self._i18n.t("conversation_data")
        )
        outer.Add(info_label, 0, wx.LEFT | wx.BOTTOM, 8)

        self._info_ctrl = wx.TextCtrl(
            panel,
            value=self._i18n.t("loading"),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        outer.Add(self._info_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        add_to_group_btn = wx.Button(panel, label=self._i18n.t("select_group"))
        add_to_group_btn.Bind(wx.EVT_BUTTON, self._on_add_to_group)
        outer.Add(add_to_group_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    def _build_group_ui(self, panel, outer):
        """wx.Notebook with three accessible tabs."""
        self._notebook = wx.Notebook(panel)

        # ── Overview tab ─────────────────────────────────────────────────────
        overview_page = wx.Panel(self._notebook)
        ov_sizer = wx.BoxSizer(wx.VERTICAL)
        self._overview_ctrl = wx.TextCtrl(
            overview_page,
            value=self._i18n.t("loading"),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        ov_sizer.Add(self._overview_ctrl, 1, wx.EXPAND | wx.ALL, 8)
        overview_page.SetSizer(ov_sizer)
        self._notebook.AddPage(overview_page, self._i18n.t("group_overview_tab"))

        # ── Participants tab ──────────────────────────────────────────────────
        part_page = wx.Panel(self._notebook)
        pt_sizer = wx.BoxSizer(wx.VERTICAL)
        self._part_list = wx.ListCtrl(
            part_page, style=wx.LC_REPORT | wx.LC_SINGLE_SEL
        )
        self._part_list.InsertColumn(0, self._i18n.t("conversations"), width=200)
        self._part_list.InsertColumn(1, self._i18n.t("phone_label"),   width=160)
        self._part_list.InsertColumn(2, self._i18n.t("group_admin"),   width=80)
        pt_sizer.Add(self._part_list, 1, wx.EXPAND | wx.ALL, 8)
        self._add_members_btn = wx.Button(part_page, label=self._i18n.t("add_member"))
        self._add_members_btn.Disable()   # enabled after we confirm user is admin
        self._add_members_btn.Bind(wx.EVT_BUTTON, self._on_add_members)
        pt_sizer.Add(self._add_members_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        part_page.SetSizer(pt_sizer)
        self._notebook.AddPage(part_page, self._i18n.t("group_participants_tab"))

        # ── Media tab ────────────────────────────────────────────────────────
        media_page = wx.Panel(self._notebook)
        md_sizer = wx.BoxSizer(wx.VERTICAL)
        self._media_label = wx.StaticText(
            media_page, label=self._i18n.t("loading")
        )
        md_sizer.Add(self._media_label, 0, wx.ALL, 8)
        media_page.SetSizer(md_sizer)
        self._notebook.AddPage(media_page, self._i18n.t("group_media_tab"))

        outer.Add(self._notebook, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

    # ── Data fetch (background thread) ───────────────────────────────────────

    def _fetch_data(self):
        if self._is_group:
            data = self._mw.get_group_info(self._jid)
            wx.CallAfter(self._populate_group, data)
        else:
            data = self._mw.get_contact_profile(self._jid)
            wx.CallAfter(self._populate_personal, data)

    def _populate_personal(self, data: dict):
        """Fill the personal-chat TextCtrl (called on main thread)."""
        if not self.IsShown():
            return
        lines = []
        name  = data.get("name") or self._name
        phone = format_number(self._jid)

        lines.append(f"{self._i18n.t('conversations')}: {name}")
        if phone:
            lines.append(f"{self._i18n.t('phone_label')}: {phone}")

        self._info_ctrl.SetValue("\n".join(lines))
        self._info_ctrl.SetFocus()

    def _populate_group(self, data: dict):
        """Fill the group Notebook tabs (called on main thread)."""
        if not self.IsShown():
            return

        i18n = self._i18n

        # ── Overview ─────────────────────────────────────────────────────────
        subject  = data.get("subject") or self._name
        desc     = data.get("desc") or ""
        creation = _fmt_ts(data.get("creation"), i18n)
        size     = data.get("size", 0)

        ov_lines = [
            f"{i18n.t('conversations')}: {subject}",
        ]
        if desc:
            ov_lines.append(f"{i18n.t('about_label')}: {desc}")
        if creation:
            ov_lines.append(f"{i18n.t('created_at').format(date=creation)}")
        ov_lines.append(f"{i18n.t('group_size').format(count=size)}")
        self._overview_ctrl.SetValue("\n".join(ov_lines))

        # ── Participants ──────────────────────────────────────────────────────
        self._part_list.DeleteAllItems()
        participants = data.get("participants", [])
        my_jid = getattr(self._mw, "my_jid", "") or ""
        user_is_admin = False
        for p in participants:
            if not isinstance(p, dict):
                continue
            p_jid   = p.get("id", "")
            p_phone = format_number(p_jid)
            # Try to resolve a name from contacts
            contact = self._mw.contacts.get(p_jid, {})
            p_name  = contact.get("pushName") or p_phone
            is_admin = "admin" if p.get("admin") else ""
            if is_admin and my_jid and (p_jid == my_jid or p_jid.split("@")[0] == my_jid.split("@")[0]):
                user_is_admin = True
            idx = self._part_list.GetItemCount()
            self._part_list.InsertItem(idx, p_name)
            self._part_list.SetItem(idx, 1, p_phone)
            self._part_list.SetItem(idx, 2, is_admin)

        # Enable "Add members" button only if current user is a group admin.
        # If we cannot determine my_jid, enable it anyway (API will reject if not admin).
        if user_is_admin or not my_jid:
            self._add_members_btn.Enable()

        # ── Media ─────────────────────────────────────────────────────────────
        media_dir  = data_path("media")
        jid_prefix = self._jid.split("@")[0]
        # Count media files associated with messages in this group
        records = (
            self._chat.get("messages", {})
                      .get("messages", {})
                      .get("records", [])
        )
        media_count = sum(
            1 for m in records
            if m.get("messageType", "") in
               {"imageMessage", "videoMessage", "documentMessage", "stickerMessage"}
            and os.path.isfile(data_path("media", f"{m.get('key',{}).get('id','')}.wzmedia"))
        )
        self._media_label.SetLabel(
            i18n.t("media_count").format(count=media_count)
        )

    # ── Action handlers ───────────────────────────────────────────────────────

    def _on_add_members(self, event):
        """Open AddMemberDialog to pick contacts to add to this group."""
        from ui.dialogs.add_member_dialog import AddMemberDialog
        dlg = AddMemberDialog(self._mw, self._jid)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_add_to_group(self, event):
        """Open SelectGroupDialog to pick a group to add this contact to."""
        from ui.dialogs.add_member_dialog import SelectGroupDialog
        dlg = SelectGroupDialog(self._mw, self._jid, self._name)
        dlg.ShowModal()
        dlg.Destroy()
