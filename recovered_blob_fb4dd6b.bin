"""
WinZapp – Conversation / Group Data Dialog
==========================================
Opens a modal dialog showing WhatsApp-style information about a chat.

* For personal chats  → a read-only text control with profile data.
* For groups          → a wx.Notebook with three tabs:
    – Overview        (name, description, creation date, size)
    – Participants    (wx.ListCtrl with name / phone / admin flag)
    – Media           (count of locally-stored media files)

Profile / group data is fetched from the WPPConnect Server in a background
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
        is_group = jid.endswith("@g.us")
        if is_group:
            # _resolve_contact_name() always returns None for groups (no
            # address-book entry) and pushName is never populated for group
            # chats — the real group name lives in chat["name"]/["subject"].
            # Without checking those first, the title fell through to
            # format_number(jid), which read the raw group JID digits aloud
            # via NVDA instead of the group's name.
            name = (
                chat.get("name")
                or chat.get("subject")
                or main_window.find_name_through_messages(chat)
                or main_window.i18n.t("unknown_group")
            )
        else:
            name = (
                main_window._resolve_contact_name(chat)
                or main_window.find_name_through_messages(chat)
                or chat.get("pushName", "")
                or format_number(jid)
            )
        self._jid    = jid
        self._name   = name
        self._is_group = is_group
        # Parallel list of participant JIDs, populated by _populate_group().
        # Index matches the row index in _part_list.
        self._participant_jids: list = []

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

        # wx.ID_CANCEL makes Esc close the dialog via the standard wx mechanism.
        back_btn = wx.Button(panel, wx.ID_CANCEL, label=self._i18n.t("back_btn"))
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

        # "Add contact" — always shown for non-group chats.
        jid = self._jid
        if not jid.endswith("@g.us"):
            add_contact_btn = wx.Button(panel, label=self._i18n.t("add_contact"))
            add_contact_btn.Bind(wx.EVT_BUTTON, self._on_add_contact)
            outer.Add(add_contact_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

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
        self._part_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_participant_activated)
        self._part_list.Bind(wx.EVT_KEY_DOWN, self._on_part_list_key_down)
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
            participants = data.get("participants", [])
            lid_jids_to_resolve = []
            lid_to_phone = getattr(self._mw, "_lid_to_phone", {})
            for p in participants:
                if not isinstance(p, dict):
                    continue
                p_jid = p.get("id", "")
                if p_jid and p_jid.endswith("@lid") and p_jid not in lid_to_phone:
                    lid_jids_to_resolve.append(p_jid)
            if lid_jids_to_resolve:
                try:
                    self._mw.resolve_lid_jids_via_api(lid_jids_to_resolve)
                except Exception:
                    pass
            wx.CallAfter(self._populate_group, data)
        else:
            if self._jid.endswith("@lid") and self._jid not in getattr(self._mw, "_lid_to_phone", {}):
                try:
                    self._mw.resolve_lid_jids_via_api([self._jid])
                except Exception:
                    pass
            data = self._mw.get_contact_profile(self._jid)
            wx.CallAfter(self._populate_personal, data)

    def _populate_personal(self, data: dict):
        """Fill the personal-chat TextCtrl (called on main thread)."""
        if not self.IsShown():
            return
        i18n  = self._i18n
        lines = []
        # The API wraps the contact under "response"; the top-level "status" is
        # the request result ("success"), not profile data — read from response.
        cdata = data.get("response") if isinstance(data.get("response"), dict) else {}
        name  = cdata.get("name") or cdata.get("formattedName") or data.get("name") or self._name

        # Resolve phone number: @lid JIDs are opaque device IDs, not phone
        # numbers — bridge them to the real phone JID via the reverse cache.
        jid = self._jid
        lid_to_phone = getattr(self._mw, "_lid_to_phone", {})
        if jid.endswith("@lid"):
            phone_jid = lid_to_phone.get(jid, "")
            if phone_jid:
                jid = phone_jid
        canonical = jid
        phone = format_number(jid) if not jid.endswith("@lid") else ""

        lines.append(f"{i18n.t('conversations')}: {name}")
        if phone:
            lines.append(f"{i18n.t('phone_label')}: {phone}")

        # About/bio text comes from the dedicated profile-status endpoint
        # (exposed as "aboutText"). Never use the top-level "status", which is
        # the API result word ("success").
        about = str(data.get("aboutText") or "").strip()
        if about:
            lines.append(f"{i18n.t('about_label')}: {about}")

        # Online / last-seen: prefer the live presence cache (populated by
        # presence.update events); fall back to the last-seen fetched directly
        # from the API (data["lastSeenTs"]) since presence events may not have
        # arrived yet.
        canonical = self._mw._normalize_jid(canonical)
        presence  = getattr(self._mw, "_presence_cache", {}).get(canonical, {})
        lkp       = presence.get("lastKnownPresence", "")
        last_seen = presence.get("lastSeen") or data.get("lastSeenTs")
        from ui.conversations import _fmt_last_seen
        if lkp in ("available", "composing", "recording"):
            lines.append(i18n.t("online_status"))
        elif last_seen:
            ls_str = _fmt_last_seen(last_seen, i18n)
            if ls_str:
                lines.append(ls_str)

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
        self._participant_jids = []
        participants = data.get("participants", [])
        my_jid = getattr(self._mw, "my_jid", "") or ""
        user_is_admin = False
        lid_to_phone  = getattr(self._mw, "_lid_to_phone", {})
        for p in participants:
            if not isinstance(p, dict):
                continue
            p_jid   = p.get("id", "")
            
            # Bridge @lid JIDs to phone-number JIDs via the reverse cache for correct phone display
            display_phone_jid = p_jid
            if p_jid.endswith("@lid"):
                phone_jid = lid_to_phone.get(p_jid, "")
                if phone_jid:
                    display_phone_jid = phone_jid
            
            p_phone = format_number(display_phone_jid) if not display_phone_jid.endswith("@lid") else display_phone_jid.rsplit("@", 1)[0]
            # Resolve name: use the robust display name resolution method from MainWindow
            # which checks contacts, chats, presence pushNames, and messages.
            p_name = self._mw._resolve_jid_name(p_jid)
            if not p_name or p_name == p_phone or p_name.isdigit() or p_name.replace("+", "").replace("-", "").replace(" ", "").isdigit():
                p_name = p_phone
            is_admin = "admin" if p.get("admin") else ""
            if is_admin and my_jid and (p_jid == my_jid or p_jid.split("@")[0] == my_jid.split("@")[0]):
                user_is_admin = True
            idx = self._part_list.GetItemCount()
            self._part_list.InsertItem(idx, p_name)
            self._part_list.SetItem(idx, 1, p_phone)
            self._part_list.SetItem(idx, 2, is_admin)
            # Store the best available JID for conversation navigation
            resolved_jid = lid_to_phone.get(p_jid, p_jid) if p_jid.endswith("@lid") else p_jid
            self._participant_jids.append(resolved_jid)

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
        def _has_media(m):
            mid = m.get('key',{}).get('id','')
            if "_" in mid:
                parts = mid.split("_")
                mid = parts[2] if len(parts) > 2 else parts[-1]
            return os.path.isfile(data_path("media", f"{mid}.wzmedia"))

        media_count = sum(
            1 for m in records
            if m.get("messageType", "") in
               {"imageMessage", "videoMessage", "documentMessage", "stickerMessage"}
            and _has_media(m)
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

    def _on_add_contact(self, event):
        """Open NewContactDialog pre-filled with phone and name from this chat."""
        from ui.dialogs.new_contact import NewContactDialog
        # Split the display name into first / surname for the dialog fields.
        parts   = self._name.split(None, 1) if self._name else []
        p_name  = parts[0] if parts else ""
        p_sur   = parts[1] if len(parts) > 1 else ""
        # Resolve phone: use the phone JID even if this chat is indexed by LID.
        jid = self._jid
        lid_to_phone = getattr(self._mw, "_lid_to_phone", {})
        if jid.endswith("@lid") and jid in lid_to_phone:
            jid = lid_to_phone[jid]
        dlg = NewContactDialog(
            self._mw, self,
            prefill_phone=format_number(jid),
            prefill_name=p_name,
            prefill_surname=p_sur,
        )
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == wx.ID_OK:
            # Refresh the info panel so the new name is visible.
            threading.Thread(target=self._fetch_data, daemon=True).start()

    def _on_add_to_group(self, event):
        """Open SelectGroupDialog to pick a group to add this contact to."""
        from ui.dialogs.add_member_dialog import SelectGroupDialog
        dlg = SelectGroupDialog(self._mw, self._jid, self._name)
        dlg.ShowModal()
        dlg.Destroy()

    def _on_participant_activated(self, event):
        """Enter / double-click on a participant row: open a private conversation."""
        idx = event.GetIndex()
        if idx < 0 or idx >= len(self._participant_jids):
            return
        jid = self._participant_jids[idx]
        # Skip groups and @lid participants that could not be resolved to a phone.
        if not jid or jid.endswith("@g.us") or jid.endswith("@lid"):
            return
        # Schedule navigation after the dialog closes so the main window is
        # the active window when navigate_to_conversation_jid runs.
        wx.CallAfter(self._mw.navigate_to_conversation_jid, jid)
        self.EndModal(wx.ID_CANCEL)

    def _on_part_list_key_down(self, event):
        """Space on the participants list also activates the item (like Enter)."""
        kc = event.GetKeyCode()
        if kc == wx.WXK_SPACE:
            idx = self._part_list.GetFocusedItem()
            if idx >= 0:
                self._part_list.Select(idx)
                class _E:
                    def GetIndex(self): return idx
                self._on_participant_activated(_E())
        else:
            event.Skip()
