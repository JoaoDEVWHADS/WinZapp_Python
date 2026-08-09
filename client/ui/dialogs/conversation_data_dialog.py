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

import logging
import os
import threading
from datetime import datetime
import wx
import wx.adv
from core.utils import format_number
from core.locale_format import get_datetime_format
from app_paths import data_path
from core.sound_system import (
    ALERT_TONE_COUNT, alert_tone_choice_keys, resolve_alert_tone_path, AlertPreviewController,
)


def _fmt_ts(ts, i18n):
    """Format a Unix timestamp to a localised date string."""
    if not ts:
        return ""
    try:
        ts_val = int(ts)
        if ts_val > 1_000_000_000_000:
            ts_val //= 1000
        dt = datetime.fromtimestamp(ts_val)
        return dt.strftime(get_datetime_format(i18n.t("datetime_fmt")))
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
        # Parallel lists describing each participant row, populated by
        # _populate_group(). Index matches the row index in _part_list.
        self._participant_jids: list = []
        self._participant_names: list = []
        self._participant_is_admin: list = []
        # False until _populate_group() confirms the current user is a
        # group admin — the context menu / edit buttons stay hidden/disabled
        # until then, so a click landing before the background fetch
        # finishes can't reach an action that isn't actually available.
        self._user_is_admin = False
        self._group_subject     = name if is_group else ""
        self._group_description = ""

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

    def _on_back_button(self, event):
        if hasattr(self, "_sound_preview"):
            self._sound_preview.stop()
        event.Skip()

    def _on_dialog_char_hook(self, event):
        if event.GetKeyCode() == wx.WXK_ESCAPE and hasattr(self, "_sound_preview"):
            self._sound_preview.stop()
        event.Skip()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        panel = wx.Panel(self)
        outer = wx.BoxSizer(wx.VERTICAL)

        # wx.ID_CANCEL makes Esc close the dialog via the standard wx mechanism.
        back_btn = wx.Button(panel, wx.ID_CANCEL, label=self._i18n.t("back_btn"))
        outer.Add(back_btn, 0, wx.ALL, 8)
        # wx's built-in Esc-to-cancel calls EndModal directly — it never goes
        # through this button's click event — so stop any playing sound
        # preview via a char hook too, not just the button handler.
        back_btn.Bind(wx.EVT_BUTTON, self._on_back_button)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_char_hook)

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

        self._build_sound_picker(panel, outer)

    def _build_sound_picker(self, panel, sizer):
        """Per-conversation notification sound override: a combobox (Default
        + Alert 1..N + Custom) plus a custom-path field shown only when
        "Custom" is selected. "Default" here means "use the private/group
        default from Settings > Alert Tones", unlike the same word on that
        settings tab (which means the bundled message_background.ogg).
        """
        i18n = self._i18n
        self._sound_label = wx.StaticText(panel, label=i18n.t("conversation_sound_label"))
        sizer.Add(self._sound_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)

        self._sound_choice_keys = alert_tone_choice_keys()
        sound_choice_labels = [i18n.t("alert_tone_default")] + [
            i18n.t("alert_tone_item").format(n=n) for n in range(1, ALERT_TONE_COUNT + 1)
        ] + [i18n.t("alert_tone_custom")]
        self._sound_combo = wx.ComboBox(
            panel, style=wx.CB_READONLY, choices=sound_choice_labels
        )
        sizer.Add(self._sound_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._sound_preview_btn = wx.Button(panel, label=i18n.t("preview_sound_play"))
        sizer.Add(self._sound_preview_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._sound_preview = AlertPreviewController(
            self._mw, self._sound_preview_btn, self._resolve_conv_sound_preview_path,
        )

        self._sound_custom_label = wx.StaticText(
            panel, label=i18n.t("conversation_sound_custom_path_label")
        )
        sizer.Add(self._sound_custom_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._sound_custom_field = wx.TextCtrl(panel, style=wx.TE_DONTWRAP)
        sizer.Add(self._sound_custom_field, 0, wx.EXPAND | wx.ALL, 8)

        conv_cfg = self._mw.settings.get("conversation_sounds", {}).get(self._jid) or {}
        try:
            idx = self._sound_choice_keys.index(conv_cfg.get("choice", "default"))
        except ValueError:
            idx = 0
        self._sound_combo.SetSelection(idx)
        self._sound_custom_field.SetValue(conv_cfg.get("custom_path", ""))
        self._update_sound_custom_field_state()

        self._sound_combo.Bind(wx.EVT_COMBOBOX, self._on_conv_sound_changed)
        self._sound_custom_field.Bind(wx.EVT_TEXT, self._on_conv_sound_custom_path_changed)

    def _resolve_conv_sound_preview_path(self) -> str:
        """Resolve whatever the sound combo currently has selected to an
        absolute path, for the preview button. "Padrão" resolves through the
        private/group Alert Tones default — same as what would actually play
        — not literally message_background.ogg."""
        idx = self._sound_combo.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._sound_choice_keys):
            return ""
        choice = self._sound_choice_keys[idx]
        active_pack = self._mw.get_active_sound_pack()
        default_pack = self._mw._default_sound_pack
        if choice == "default":
            is_group = self._jid.endswith("@g.us")
            tones = self._mw.settings.get("alert_tones", {})
            type_key = "group" if is_group else "private"
            type_choice = tones.get(type_key, "default")
            type_custom = tones.get(f"{type_key}_custom_path", "")
            return resolve_alert_tone_path(active_pack, default_pack, type_choice, type_custom)
        return resolve_alert_tone_path(active_pack, default_pack, choice, self._sound_custom_field.GetValue().strip())

    def _update_sound_custom_field_state(self):
        is_custom = self._sound_combo.GetSelection() == len(self._sound_choice_keys) - 1
        self._sound_custom_label.Show(is_custom)
        self._sound_custom_field.Show(is_custom)
        self._sound_custom_label.GetParent().Layout()

    def _save_conv_sound(self):
        """Persist the per-conversation sound override immediately.

        Unlike the Settings dialog, this never blocks or validates the
        custom path — an invalid path just falls back to the type default
        at playback time (see MainWindow._resolve_background_sound_path).
        """
        choice = self._sound_choice_keys[self._sound_combo.GetSelection()]
        custom_path = self._sound_custom_field.GetValue().strip()
        self._mw.settings.setdefault("conversation_sounds", {})[self._jid] = {
            "choice": choice,
            "custom_path": custom_path,
        }
        cache = getattr(self._mw, "_notification_sound_cache", None)
        if cache is not None:
            cache.clear()

    def _on_conv_sound_changed(self, event):
        self._update_sound_custom_field_state()
        self._save_conv_sound()
        self._mw._schedule_save_settings()
        # Changing the selection invalidates whatever was previewing.
        self._sound_preview.stop()

    def _on_conv_sound_custom_path_changed(self, event):
        self._save_conv_sound()
        self._mw._schedule_save_settings()

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
        # Admin-only group-editing buttons — hidden entirely (not just
        # disabled) until we confirm the current user is a group admin.
        self._edit_name_btn = wx.Button(overview_page, label=self._i18n.t("edit_group_name"))
        self._edit_name_btn.Hide()
        self._edit_name_btn.Bind(wx.EVT_BUTTON, self._on_edit_group_name)
        ov_sizer.Add(self._edit_name_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._edit_desc_btn = wx.Button(overview_page, label=self._i18n.t("edit_group_description"))
        self._edit_desc_btn.Hide()
        self._edit_desc_btn.Bind(wx.EVT_BUTTON, self._on_edit_group_description)
        ov_sizer.Add(self._edit_desc_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._add_members_btn_overview = wx.Button(overview_page, label=self._i18n.t("add_member"))
        self._add_members_btn_overview.Disable()   # enabled after we confirm user is admin
        self._add_members_btn_overview.Bind(wx.EVT_BUTTON, self._on_add_members)
        ov_sizer.Add(self._add_members_btn_overview, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self._build_sound_picker(overview_page, ov_sizer)
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
        self._part_list.Bind(wx.EVT_CONTEXT_MENU, self._on_participant_context_menu)
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
        # This runs on a background thread with no caller to report failures
        # to — an uncaught exception here just kills the thread silently (in
        # a compiled windowed build, its traceback goes nowhere), leaving the
        # dialog showing "loading" forever with no way to know why. Wrap the
        # whole thing so a real bug still logs a traceback and still clears
        # the "loading" placeholders instead of leaving them stuck.
        try:
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
        except Exception:
            logging.exception("[ConversationDataDialog] _fetch_data failed for %s", self._jid)
            if self._is_group:
                wx.CallAfter(self._populate_group, {})
            else:
                wx.CallAfter(self._populate_personal, {})

    def _populate_personal(self, data: dict):
        """Fill the personal-chat TextCtrl (called on main thread)."""
        # _fetch_data()'s background thread starts in __init__, before the
        # caller has called ShowModal() — a fast local WPPConnect response
        # routinely won this race and got here while IsShown() was still
        # False (ShowModal() hadn't finished entering its modal loop yet),
        # so this used to bail out silently every time, leaving every tab on
        # "loading" forever. The widgets themselves are already built by
        # _build_ui() before the thread ever starts, so there is nothing to
        # wait for here — the only real risk is the dialog having been
        # destroyed (closed) before the data arrived, which self.IsShown()
        # doesn't reliably guard anyway once the wx C++ object is gone.
        try:
            self._populate_personal_unsafe(data)
        except RuntimeError:
            pass  # dialog was closed/destroyed before data arrived
        except Exception:
            # See _populate_group()'s equivalent guard.
            logging.exception("[ConversationDataDialog] _populate_personal failed for %s", self._jid)

    def _populate_personal_unsafe(self, data: dict):
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
        # See _populate_personal()'s identical comment: the IsShown() gate
        # this used to have lost a race against _fetch_data()'s background
        # thread on every single group (a local WPPConnect group-info call
        # is fast enough to consistently return before ShowModal() finishes
        # entering its modal loop), so Overview/Participants/Media never
        # populated for ANY group — always stuck on "loading".
        try:
            self._populate_group_unsafe(data)
        except RuntimeError:
            pass  # dialog was closed/destroyed before data arrived
        except Exception:
            # See _fetch_data(): this runs from a wx.CallAfter callback, so an
            # uncaught exception here is swallowed by wx's event loop with no
            # visible trace — the three tabs simply stay on "loading" forever
            # with no clue why. get_group_info()'s real response field names
            # (description/createdAt/isAdmin, no top-level "size") didn't
            # match what this method originally read (desc/creation/admin/
            # size), so real data always kept the Overview tab wrong or
            # (depending on exactly which field access failed) never reached
            # SetValue() at all. Fixed those below, but keep this guard too:
            # any other unexpected shape from the API should log instead of
            # silently hanging the dialog.
            logging.exception("[ConversationDataDialog] _populate_group failed for %s", self._jid)

    def _populate_group_unsafe(self, data: dict):
        i18n = self._i18n

        # ── Overview ─────────────────────────────────────────────────────────
        subject  = data.get("subject") or self._name
        # get_group_info() (main.py) returns the raw group-info response,
        # whose real field names are "description" and "createdAt" — this
        # used to read "desc"/"creation", which don't exist in that response,
        # so the description and creation date silently never showed.
        desc     = data.get("description") or data.get("desc") or ""
        creation = _fmt_ts(data.get("createdAt") or data.get("creation"), i18n)
        participants_list = data.get("participants") or []
        # The API response has no top-level "size" field at all — it must be
        # derived from the participants list.
        size     = data.get("size") or len(participants_list)

        ov_lines = [
            f"{i18n.t('conversations')}: {subject}",
        ]
        if desc:
            ov_lines.append(f"{i18n.t('about_label')}: {desc}")
        if creation:
            ov_lines.append(f"{i18n.t('created_at').format(date=creation)}")
        ov_lines.append(f"{i18n.t('group_size').format(count=size)}")
        self._overview_ctrl.SetValue("\n".join(ov_lines))
        # Kept for the "edit name/description" dialogs below, pre-filled
        # with whatever is currently set (blank string if the group has no
        # description).
        self._group_subject     = subject
        self._group_description = desc

        # ── Participants ──────────────────────────────────────────────────────
        self._part_list.DeleteAllItems()
        self._participant_jids = []
        self._participant_names: list = []
        self._participant_is_admin: list = []
        participants = data.get("participants", [])
        my_jid = getattr(self._mw, "my_jid", "") or ""
        my_lid = getattr(self._mw, "my_lid", "") or ""
        my_digits = {j.split("@")[0] for j in (my_jid, my_lid) if j}
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
            # get_group_info()'s real participant shape is {"id", "isAdmin"}
            # — "admin" doesn't exist on it, so this always read False.
            is_admin_bool = bool(p.get("isAdmin") or p.get("admin"))
            if is_admin_bool and my_digits and p_jid.split("@")[0] in my_digits:
                user_is_admin = True
            idx = self._part_list.GetItemCount()
            # Append the admin status directly onto the row's own text (not
            # just a separate column) so a screen reader always announces it
            # when arrowing through the list, regardless of whether it's
            # configured to report every column of a report-view ListCtrl.
            row_label = (
                f"{p_name}, {i18n.t('group_admin_suffix')}" if is_admin_bool else p_name
            )
            self._part_list.InsertItem(idx, row_label)
            self._part_list.SetItem(idx, 1, p_phone)
            self._part_list.SetItem(idx, 2, i18n.t("group_admin") if is_admin_bool else "")
            # Store the best available JID for conversation navigation
            resolved_jid = lid_to_phone.get(p_jid, p_jid) if p_jid.endswith("@lid") else p_jid
            self._participant_jids.append(resolved_jid)
            self._participant_names.append(p_name)
            self._participant_is_admin.append(is_admin_bool)

        # Enable "Add members" buttons, and show the admin-only group-editing
        # buttons, only if the current user is a group admin. If we cannot
        # determine my_jid, enable them anyway (the API will reject the
        # request if the user turns out not to be an admin).
        self._user_is_admin = bool(user_is_admin or not my_digits)
        if self._user_is_admin:
            self._add_members_btn.Enable()
            self._add_members_btn_overview.Enable()
            self._edit_name_btn.Show()
            self._edit_desc_btn.Show()
        else:
            self._edit_name_btn.Hide()
            self._edit_desc_btn.Hide()
        self._edit_name_btn.GetParent().Layout()

        # A pre-populated list must never leave focus/selection pointing at
        # nothing — mirrors the conversation list's own convention (see
        # conversations.py's Focus(0)/Select(0) usage).
        if self._part_list.GetItemCount() > 0:
            self._part_list.Focus(0)
            self._part_list.Select(0)

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

    # ── Participant context menu (admin-only actions) ──────────────────────────

    def _on_participant_context_menu(self, event):
        """Right-click / Menu key / Shift+F10 on a participant row.

        Remove/promote/demote are admin-only server-side actions — the menu
        items are left out entirely (not just disabled) when the current
        user isn't a group admin, rather than showing options that would
        just fail.
        """
        idx = self._part_list.GetFirstSelected()
        if idx < 0:
            idx = self._part_list.GetFocusedItem()
        if idx < 0 or idx >= len(self._participant_jids):
            return
        if not self._user_is_admin:
            return
        jid       = self._participant_jids[idx]
        name      = self._participant_names[idx] if idx < len(self._participant_names) else jid
        is_admin  = self._participant_is_admin[idx] if idx < len(self._participant_is_admin) else False
        i18n      = self._i18n

        menu = wx.Menu()
        remove_item = menu.Append(wx.ID_ANY, i18n.t("remove_member"))
        self.Bind(wx.EVT_MENU, lambda e, j=jid, n=name: self._on_remove_member(j, n), remove_item)

        if is_admin:
            demote_item = menu.Append(wx.ID_ANY, i18n.t("demote_from_admin"))
            self.Bind(wx.EVT_MENU, lambda e, j=jid, n=name: self._on_demote_member(j, n), demote_item)
        else:
            promote_item = menu.Append(wx.ID_ANY, i18n.t("promote_to_admin"))
            self.Bind(wx.EVT_MENU, lambda e, j=jid, n=name: self._on_promote_member(j, n), promote_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def _show_group_action_error(self, message: str):
        wx.MessageBox(
            message,
            self._i18n.t("error").format(app_name=self._mw.app_name),
            wx.OK | wx.ICON_ERROR,
            self,
        )

    def _run_group_participant_action(self, api_fn, jid: str, name: str, fail_key: str):
        """Call a remove/promote/demote API method on a background thread
        and refresh the participants tab on success, or surface the error
        on failure — including a genuine permission rejection from the
        server (the client-side is-admin check above is only a best-effort
        guard against showing options that can't work; the server is the
        real authority)."""
        ok, err = api_fn(self._jid, [jid])

        def _done():
            if ok:
                threading.Thread(target=self._fetch_data, daemon=True).start()
            else:
                self._show_group_action_error(
                    self._i18n.t(fail_key).format(name=name, error=err or "?")
                )
        wx.CallAfter(_done)

    def _on_remove_member(self, jid: str, name: str):
        if not self._user_is_admin:
            self._show_group_action_error(self._i18n.t("group_action_no_permission"))
            return
        i18n = self._i18n
        confirmed = wx.MessageBox(
            i18n.t("remove_member_confirm").format(name=name),
            i18n.t("remove_member"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirmed != wx.YES:
            return
        threading.Thread(
            target=self._run_group_participant_action,
            args=(self._mw.remove_group_members, jid, name, "remove_member_failed"),
            daemon=True,
        ).start()

    def _on_promote_member(self, jid: str, name: str):
        if not self._user_is_admin:
            self._show_group_action_error(self._i18n.t("group_action_no_permission"))
            return
        i18n = self._i18n
        confirmed = wx.MessageBox(
            i18n.t("promote_confirm").format(name=name),
            i18n.t("promote_to_admin"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirmed != wx.YES:
            return
        threading.Thread(
            target=self._run_group_participant_action,
            args=(self._mw.promote_group_members, jid, name, "promote_failed"),
            daemon=True,
        ).start()

    def _on_demote_member(self, jid: str, name: str):
        if not self._user_is_admin:
            self._show_group_action_error(self._i18n.t("group_action_no_permission"))
            return
        i18n = self._i18n
        confirmed = wx.MessageBox(
            i18n.t("demote_confirm").format(name=name),
            i18n.t("demote_from_admin"),
            wx.YES_NO | wx.ICON_QUESTION,
            self,
        )
        if confirmed != wx.YES:
            return
        threading.Thread(
            target=self._run_group_participant_action,
            args=(self._mw.demote_group_members, jid, name, "demote_failed"),
            daemon=True,
        ).start()

    # ── Admin-only group name/description editing ───────────────────────────────

    def _prompt_text_edit(self, title: str, label: str, initial: str, multiline: bool = False):
        """Small Save/Cancel dialog pre-filled with *initial*. Returns the
        new text on Save, or None on Cancel/close."""
        dlg = wx.Dialog(self, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer(wx.VERTICAL)

        lbl = wx.StaticText(dlg, label=label)
        sizer.Add(lbl, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)

        style = wx.TE_MULTILINE if multiline else 0
        field = wx.TextCtrl(dlg, value=initial or "", style=style)
        sizer.Add(field, 1 if multiline else 0, wx.EXPAND | wx.ALL, 8)

        btn_sizer = wx.StdDialogButtonSizer()
        save_btn = wx.Button(dlg, wx.ID_OK, label=self._i18n.t("save_btn"))
        cancel_btn = wx.Button(dlg, wx.ID_CANCEL, label=self._i18n.t("cancel"))
        btn_sizer.AddButton(save_btn)
        btn_sizer.AddButton(cancel_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 8)

        dlg.SetSizer(sizer)
        dlg.SetSize((420, 260 if multiline else 150))
        save_btn.SetDefault()
        field.SetFocus()
        field.SetInsertionPointEnd()

        result = dlg.ShowModal()
        value = field.GetValue() if result == wx.ID_OK else None
        dlg.Destroy()
        return value

    def _run_group_edit(self, api_fn, new_value: str, fail_key: str):
        ok, err = api_fn(self._jid, new_value)

        def _done():
            if ok:
                threading.Thread(target=self._fetch_data, daemon=True).start()
            else:
                self._show_group_action_error(self._i18n.t(fail_key).format(error=err or "?"))
        wx.CallAfter(_done)

    def _on_edit_group_name(self, event):
        if not self._user_is_admin:
            self._show_group_action_error(self._i18n.t("group_action_no_permission"))
            return
        new_name = self._prompt_text_edit(
            self._i18n.t("edit_group_name"),
            self._i18n.t("group_name_label"),
            self._group_subject,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name or new_name == (self._group_subject or ""):
            return
        threading.Thread(
            target=self._run_group_edit,
            args=(self._mw.set_group_subject, new_name, "edit_group_name_failed"),
            daemon=True,
        ).start()

    def _on_edit_group_description(self, event):
        if not self._user_is_admin:
            self._show_group_action_error(self._i18n.t("group_action_no_permission"))
            return
        new_desc = self._prompt_text_edit(
            self._i18n.t("edit_group_description"),
            self._i18n.t("group_description_label"),
            self._group_description,
            multiline=True,
        )
        if new_desc is None:
            return
        new_desc = new_desc.strip()
        if new_desc == (self._group_description or "").strip():
            return
        threading.Thread(
            target=self._run_group_edit,
            args=(self._mw.set_group_description, new_desc, "edit_group_description_failed"),
            daemon=True,
        ).start()
