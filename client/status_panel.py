import base64
import mimetypes
import os
import tempfile
import threading
import wx
import requests
from ui.accessible import AccessibleStatusPrev, AccessibleStatusNext
from core.utils import format_number, get_downloads_folder
from core.video_player import VideoPlayer


# ── My Status dialog ─────────────────────────────────────────────────────────

class MyStatusDialog(wx.Dialog):
    """
    Modal dialog for viewing the user's own posted statuses and adding new ones.

    Return codes
    ------------
    RC_ADD_STATUS  – user clicked "Add status"; caller should open the add-flow.
    wx.ID_CANCEL   – user closed the dialog without requesting an action.
    """

    RC_ADD_STATUS = wx.ID_HIGHEST + 100

    def __init__(self, main_window, my_statuses: list):
        i18n = main_window.i18n
        super().__init__(
            None,
            title=i18n.t("my_status"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._mw       = main_window
        self._statuses = my_statuses
        self._current  = 0
        self._init_ui()

    # ── UI build ──────────────────────────────────────────────────────────

    def _init_ui(self):
        i18n  = self._mw.i18n
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Add-status button — always visible
        self._add_btn = wx.Button(panel, label=i18n.t("status_add"))
        self._add_btn.Bind(wx.EVT_BUTTON, self._on_add_status)
        sizer.Add(self._add_btn, 0, wx.ALL, 8)

        # Viewer section — only when the user already has statuses
        if self._statuses:
            self._content_lbl = wx.StaticText(panel, label="")
            sizer.Add(self._content_lbl, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

            nav_sizer = wx.BoxSizer(wx.HORIZONTAL)

            self._prev_btn = wx.Button(panel, label=i18n.t("status_prev"))
            self._prev_btn.SetAccessible(AccessibleStatusPrev(i18n.t("accessible_ctrl_left")))
            self._prev_btn.Bind(wx.EVT_BUTTON, self._on_prev)
            nav_sizer.Add(self._prev_btn, 0, wx.RIGHT, 5)

            self._next_btn = wx.Button(panel, label=i18n.t("status_next"))
            self._next_btn.SetAccessible(AccessibleStatusNext(i18n.t("accessible_ctrl_right")))
            self._next_btn.Bind(wx.EVT_BUTTON, self._on_next)
            nav_sizer.Add(self._next_btn, 0)

            sizer.Add(nav_sizer, 0, wx.LEFT | wx.BOTTOM, 8)

            self._update_content()

        # Close button
        btn_sizer = wx.StdDialogButtonSizer()
        close_btn = wx.Button(panel, wx.ID_CANCEL, i18n.t("close"))
        btn_sizer.AddButton(close_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 8)

        panel.SetSizer(sizer)
        sizer.Fit(panel)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(outer)
        outer.Fit(self)
        self.CenterOnScreen()

        self._add_btn.SetFocus()

    # ── Content display ───────────────────────────────────────────────────

    def _update_content(self):
        if not self._statuses:
            return
        i18n   = self._mw.i18n
        total  = len(self._statuses)
        status = self._statuses[self._current]

        msg_type = status.get("messageType", "")
        msg_obj  = status.get("message") or {}
        if msg_type == "conversation":
            content = msg_obj.get("conversation", "")
        elif msg_type == "extendedTextMessage":
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        elif msg_type == "imageMessage":
            img     = msg_obj.get("imageMessage") or {}
            caption = (img.get("caption") or "").strip()
            content = f"{i18n.t('photo')}: {caption}" if caption else i18n.t("photo")
        elif msg_type == "videoMessage":
            video   = msg_obj.get("videoMessage") or {}
            caption = (video.get("caption") or "").strip()
            content = f"{i18n.t('video')}: {caption}" if caption else i18n.t("video")
        else:
            content = msg_type or "?"

        nav_info = i18n.t("status_of").format(current=self._current + 1, total=total)
        label    = f"{nav_info}: {content}"
        self._content_lbl.SetLabel(label)
        self._mw.output(label, interrupt=True)

    # ── Navigation ────────────────────────────────────────────────────────

    def _on_prev(self, event):
        if not self._statuses:
            return
        self._current = (self._current - 1) % len(self._statuses)
        self._update_content()

    def _on_next(self, event):
        if not self._statuses:
            return
        self._current = (self._current + 1) % len(self._statuses)
        self._update_content()

    # ── Actions ───────────────────────────────────────────────────────────

    def _on_add_status(self, event):
        """Close the dialog signalling that the caller should open the add-flow."""
        self.EndModal(MyStatusDialog.RC_ADD_STATUS)


# ── Main status panel ────────────────────────────────────────────────────────

class StatusPanel(wx.Panel):
    def __init__(self, main_window, parent):
        super().__init__(parent)
        self.main_window = main_window
        self.parent = parent

        # List of status contacts (other people): [{"name", "jid", "statuses": [...]}]
        self._status_contacts = []
        # Own posted statuses: [status_dict, ...]
        self._my_statuses = []
        # Whether the list is currently showing the loading placeholder
        self._list_is_loading = False
        # Index of selected contact in _status_contacts (-1 = none / My Status selected)
        self._selected_contact_idx = -1
        # Index of current status within the selected contact's statuses
        self._current_status_idx = 0
        # The actual status dict/contact entry/copy-text currently shown in
        # the viewer — set by _show_current_status(), read by the action
        # buttons (copy text, save media, open video, reply).
        self._current_status       = None
        self._current_status_entry = None
        self._current_status_text  = ""

        # Liked status tracking: status_id → bool
        self._liked_statuses: dict = {}

        # Local path of the currently downloaded video status, if any (kept
        # so re-pressing Play/Pause doesn't re-download the same file).
        self._video_local_path = None
        self._video_download_status_id = None

        self.init_UI()
        self._create_accelerators()

        self._video_player = VideoPlayer(main_window, self._video_bitmap)
        # Stop playback (audio + frame decoding) whenever this panel is
        # hidden — Alt+1/Alt+4 switching away from the Status tab, or the
        # window closing — regardless of which of the several call sites in
        # main.py does the hiding. Without this a video kept playing (audio
        # audible, ffmpeg still decoding) in the background indefinitely.
        self.Bind(wx.EVT_SHOW, self._on_panel_show)

    # ── UI ───────────────────────────────────────────────────────────────────

    def init_UI(self):
        i18n  = self.main_window.i18n
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Header buttons ────────────────────────────────────────────────
        self._add_status_btn = wx.Button(self, label=i18n.t("status_add"))
        self._add_status_btn.Bind(wx.EVT_BUTTON, self._on_add_status)
        sizer.Add(self._add_status_btn, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        # ── Status contacts list ──────────────────────────────────────────
        self._list_label = wx.StaticText(self, label=i18n.t("status"))
        sizer.Add(self._list_label, 0, wx.LEFT | wx.TOP, 5)

        self._status_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        self._status_list.InsertColumn(0, i18n.t("status"), width=360)
        self._status_list.Bind(wx.EVT_LIST_ITEM_SELECTED,  self._on_status_contact_selected)
        self._status_list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_status_contact_activated)
        self._status_list.Bind(wx.EVT_KEY_DOWN, self._on_status_list_key_down)
        sizer.Add(self._status_list, 1, wx.EXPAND | wx.ALL, 5)

        # ── Status viewer panel (hidden until a contact is selected) ──────
        self._viewer_panel = wx.Panel(self)
        viewer_sizer = wx.BoxSizer(wx.VERTICAL)

        self._status_content_label = wx.StaticText(self._viewer_panel, label="")
        viewer_sizer.Add(self._status_content_label, 0, wx.ALL, 5)

        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._prev_status_btn = wx.Button(self._viewer_panel, label=i18n.t("status_prev"))
        self._prev_status_btn.SetAccessible(AccessibleStatusPrev(i18n.t("accessible_ctrl_left")))
        self._prev_status_btn.Bind(wx.EVT_BUTTON, self._on_prev_status)
        nav_sizer.Add(self._prev_status_btn, 0, wx.RIGHT, 5)

        self._next_status_btn = wx.Button(self._viewer_panel, label=i18n.t("status_next"))
        self._next_status_btn.SetAccessible(AccessibleStatusNext(i18n.t("accessible_ctrl_right")))
        self._next_status_btn.Bind(wx.EVT_BUTTON, self._on_next_status)
        nav_sizer.Add(self._next_status_btn, 0, wx.RIGHT, 5)

        viewer_sizer.Add(nav_sizer, 0, wx.LEFT | wx.BOTTOM, 5)

        # Video statuses: audio plays through BASS (as everywhere else in
        # WinZapp); the picture is decoded by the bundled ffmpeg binary as a
        # capped-rate JPEG frame sequence and drawn into this bitmap — see
        # core/video_player.py's module docstring for why (BASS alone can't
        # decode WhatsApp's AAC track or render video at all).
        self._video_bitmap = wx.StaticBitmap(self._viewer_panel, size=(320, 240))
        viewer_sizer.Add(self._video_bitmap, 0, wx.LEFT | wx.BOTTOM, 5)
        self._video_bitmap.Hide()

        self._play_pause_btn = wx.Button(self._viewer_panel, label=i18n.t("status_play_pause"))
        self._play_pause_btn.Bind(wx.EVT_BUTTON, self._on_play_pause_video)
        viewer_sizer.Add(self._play_pause_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._play_pause_btn.Hide()

        self._like_btn = wx.Button(self._viewer_panel, label=i18n.t("status_like"))
        self._like_btn.Bind(wx.EVT_BUTTON, self._on_like_status)
        viewer_sizer.Add(self._like_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._like_btn.Hide()

        self._copy_text_btn = wx.Button(self._viewer_panel, label=i18n.t("status_copy_text"))
        self._copy_text_btn.Bind(wx.EVT_BUTTON, self._on_copy_status_text)
        viewer_sizer.Add(self._copy_text_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._copy_text_btn.Hide()

        self._save_media_btn = wx.Button(self._viewer_panel, label=i18n.t("status_save_media"))
        self._save_media_btn.Bind(wx.EVT_BUTTON, self._on_save_status_media)
        viewer_sizer.Add(self._save_media_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._save_media_btn.Hide()

        # ── Reply to the currently viewed status ────────────────────────────
        self._reply_label = wx.StaticText(self._viewer_panel, label=i18n.t("status_reply_label"))
        viewer_sizer.Add(self._reply_label, 0, wx.LEFT | wx.TOP, 5)
        self._reply_field = wx.TextCtrl(self._viewer_panel, style=wx.TE_PROCESS_ENTER)
        self._reply_field.Bind(wx.EVT_TEXT_ENTER, self._on_send_status_reply)
        viewer_sizer.Add(self._reply_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self._reply_send_btn = wx.Button(self._viewer_panel, label=i18n.t("status_reply_send"))
        self._reply_send_btn.Bind(wx.EVT_BUTTON, self._on_send_status_reply)
        viewer_sizer.Add(self._reply_send_btn, 0, wx.LEFT | wx.BOTTOM, 5)
        self._reply_label.Hide()
        self._reply_field.Hide()
        self._reply_send_btn.Hide()

        self._viewer_panel.SetSizer(viewer_sizer)
        self._viewer_panel.Hide()
        sizer.Add(self._viewer_panel, 0, wx.EXPAND | wx.ALL, 5)

        # ── Post text status panel (hidden) ───────────────────────────────
        self._post_panel = wx.Panel(self)
        post_sizer = wx.BoxSizer(wx.VERTICAL)

        self._post_close_btn = wx.Button(self._post_panel, label=i18n.t("close"))
        self._post_close_btn.Bind(wx.EVT_BUTTON, self._on_close_post_panel)
        post_sizer.Add(self._post_close_btn, 0, wx.ALL, 5)

        self._post_text_label = wx.StaticText(self._post_panel, label=i18n.t("status_text_label"))
        post_sizer.Add(self._post_text_label, 0, wx.LEFT | wx.TOP, 5)

        self._post_text_field = wx.TextCtrl(
            self._post_panel,
            style=wx.TE_MULTILINE | wx.TE_DONTWRAP,
        )
        post_sizer.Add(self._post_text_field, 0, wx.EXPAND | wx.ALL, 5)

        self._caption_label = wx.StaticText(self._post_panel, label=i18n.t("status_caption_hint"))
        post_sizer.Add(self._caption_label, 0, wx.LEFT, 5)

        self._caption_field = wx.TextCtrl(self._post_panel, style=wx.TE_DONTWRAP)
        self._caption_field.SetHint(i18n.t("status_caption_hint"))
        post_sizer.Add(self._caption_field, 0, wx.EXPAND | wx.ALL, 5)

        self._post_send_btn = wx.Button(self._post_panel, label=i18n.t("status_send"))
        self._post_send_btn.Bind(wx.EVT_BUTTON, self._on_send_text_status)
        post_sizer.Add(self._post_send_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._post_panel.SetSizer(post_sizer)
        self._post_panel.Hide()
        sizer.Add(self._post_panel, 0, wx.EXPAND | wx.ALL, 5)

        # ── Post media status panel (hidden) ──────────────────────────────
        self._media_post_panel = wx.Panel(self)
        media_sizer = wx.BoxSizer(wx.VERTICAL)

        self._media_close_btn = wx.Button(self._media_post_panel, label=i18n.t("close"))
        self._media_close_btn.Bind(wx.EVT_BUTTON, self._on_close_media_panel)
        media_sizer.Add(self._media_close_btn, 0, wx.ALL, 5)

        # Dynamic list of "Remover anexo <filename>" buttons, rebuilt on every change
        self._media_attachments_list_panel = wx.Panel(self._media_post_panel)
        self._media_attachments_list_sizer = wx.BoxSizer(wx.VERTICAL)
        self._media_attachments_list_panel.SetSizer(self._media_attachments_list_sizer)
        media_sizer.Add(self._media_attachments_list_panel, 0, wx.EXPAND | wx.LEFT | wx.TOP, 5)

        self._media_add_more_btn = wx.Button(self._media_post_panel, label=i18n.t("add_more_files"))
        self._media_add_more_btn.Bind(wx.EVT_BUTTON, self._on_add_more_media_files)
        media_sizer.Add(self._media_add_more_btn, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        self._media_caption_label = wx.StaticText(self._media_post_panel, label=i18n.t("status_caption_hint"))
        media_sizer.Add(self._media_caption_label, 0, wx.LEFT, 5)

        self._media_caption_field = wx.TextCtrl(self._media_post_panel, style=wx.TE_DONTWRAP)
        self._media_caption_field.SetHint(i18n.t("status_caption_hint"))
        media_sizer.Add(self._media_caption_field, 0, wx.EXPAND | wx.ALL, 5)

        self._media_send_btn = wx.Button(self._media_post_panel, label=i18n.t("status_send"))
        self._media_send_btn.Bind(wx.EVT_BUTTON, self._on_send_media_status)
        media_sizer.Add(self._media_send_btn, 0, wx.LEFT | wx.BOTTOM, 5)

        self._media_post_panel.SetSizer(media_sizer)
        self._media_post_panel.Hide()
        sizer.Add(self._media_post_panel, 0, wx.EXPAND | wx.ALL, 5)

        self._selected_media_paths: list = []

        self.SetSizer(sizer)

    def _create_accelerators(self):
        self.ID_CTRL_LEFT  = wx.NewIdRef()
        self.ID_CTRL_RIGHT = wx.NewIdRef()
        accel_tbl = wx.AcceleratorTable([
            (wx.ACCEL_CTRL, wx.WXK_LEFT,  self.ID_CTRL_LEFT),
            (wx.ACCEL_CTRL, wx.WXK_RIGHT, self.ID_CTRL_RIGHT),
        ])
        self.SetAcceleratorTable(accel_tbl)
        self.Bind(wx.EVT_MENU, self._on_prev_status, id=self.ID_CTRL_LEFT)
        self.Bind(wx.EVT_MENU, self._on_next_status, id=self.ID_CTRL_RIGHT)

    # ── Refresh / load statuses ──────────────────────────────────────────────

    def on_show(self):
        """Called when the panel becomes visible — refresh the status list."""
        threading.Thread(target=self._load_statuses, daemon=True).start()

    def _on_panel_show(self, event):
        """Stop any playing video the moment this panel is hidden (Alt+1/
        Alt+4 switching away, window close, ...) — regardless of which of
        main.py's several `status_panel.Hide()` call sites did it. Without
        this a video's audio kept playing (and ffmpeg kept decoding) in the
        background indefinitely after leaving the Status tab."""
        if not event.IsShown():
            self._video_player.stop()
        event.Skip()

    def _load_statuses(self):
        """
        Build the status list from status updates received via WebSocket.

        WPPConnect does not expose a REST endpoint to query other users' statuses,
        so we rely on the in-memory _status_updates dict that is populated by
        MainWindow._store_status_update() whenever a status@broadcast message
        arrives over the Socket.IO connection.
        """
        mw   = self.main_window
        i18n = mw.i18n
        wx.CallAfter(self._set_list_loading)
        status_updates = getattr(mw, "_status_updates", {})
        records = []
        for participant, msgs in list(status_updates.items()):
            for msg in msgs:
                records.append(msg)
        my_statuses, contacts = self._parse_statuses(records, i18n)
        wx.CallAfter(self._populate_list, my_statuses, contacts)

    def _parse_statuses(self, items, i18n) -> tuple:
        """
        Separate own statuses from other people's.

        Returns
        -------
        (my_statuses, contacts)
            my_statuses : list of status dicts where key.fromMe == True
            contacts    : list of {"name", "jid", "statuses"} for other people
        """
        my_statuses = []
        contacts    = []

        if not isinstance(items, list):
            return my_statuses, contacts

        # Group by participant JID (use participant over remoteJid for
        # status@broadcast entries, which is how WhatsApp encodes them).
        grouped: dict = {}
        for item in items:
            key = item.get("key", {})
            if key.get("fromMe", False):
                my_statuses.append(item)
                continue
            remote_jid  = key.get("remoteJid", "")
            # key.participant is the canonical sender field for status messages,
            # but may be null/missing if the Baileys WAMessage had participant
            # at the top level instead of inside the key.  Fall back to the
            # top-level participant column that Prisma also exposes.
            participant = (key.get("participant") or item.get("participant") or "")
            # status@broadcast is the channel; real sender is in participant
            if remote_jid == "status@broadcast" and participant:
                jid = participant
            else:
                jid = remote_jid or participant
            if not jid or jid == "status@broadcast":
                continue
            name = self._resolve_name(jid) or format_number(jid)
            if jid not in grouped:
                grouped[jid] = {"name": name, "jid": jid, "statuses": []}
            grouped[jid]["statuses"].append(item)

        for entry in grouped.values():
            contacts.append(entry)

        return my_statuses, contacts

    def _resolve_name(self, jid: str) -> str:
        mw      = self.main_window
        contact = mw.contacts.get(jid)
        if contact:
            name = contact.get("pushName") or ""
            if name:
                return name
        return ""

    def _set_list_loading(self):
        self._list_is_loading = True
        i18n = self.main_window.i18n
        self._status_list.DeleteAllItems()
        self._status_list.Append((i18n.t("status_loading"),))

    @staticmethod
    def _latest_ts(entry: dict) -> int:
        """Return the highest messageTimestamp among a contact's statuses."""
        return max(
            (int(s.get("messageTimestamp", 0) or 0) for s in entry.get("statuses", [])),
            default=0,
        )

    def _status_preview(self, status: dict, i18n) -> str:
        """Return a short human-readable preview of a single status item."""
        msg_type = status.get("messageType", "")
        msg_obj  = status.get("message") or {}
        if msg_type == "conversation":
            return msg_obj.get("conversation", "")
        if msg_type == "extendedTextMessage":
            return (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        if msg_type == "imageMessage":
            cap = ((msg_obj.get("imageMessage") or {}).get("caption") or "").strip()
            return f"{i18n.t('photo')}: {cap}" if cap else i18n.t("photo")
        if msg_type == "videoMessage":
            cap = ((msg_obj.get("videoMessage") or {}).get("caption") or "").strip()
            return f"{i18n.t('video')}: {cap}" if cap else i18n.t("video")
        return msg_type or ""

    def _populate_list(self, my_statuses: list, contacts: list):
        i18n = self.main_window.i18n

        # Sort contacts by most-recent status timestamp (newest first)
        contacts = sorted(contacts, key=self._latest_ts, reverse=True)
        # Within each contact keep statuses newest-first too
        for entry in contacts:
            entry["statuses"] = sorted(
                entry.get("statuses", []),
                key=lambda s: int(s.get("messageTimestamp", 0) or 0),
                reverse=True,
            )

        self._my_statuses          = my_statuses
        self._status_contacts      = contacts
        self._selected_contact_idx = -1
        self._list_is_loading      = False
        self._viewer_panel.Hide()
        self._status_list.DeleteAllItems()

        # ── Row 0: always "My Status" ─────────────────────────────────────
        self._status_list.Append((self._my_status_label(i18n),))

        # ── Rows 1+: one row per contact showing their latest status ──────
        for entry in contacts:
            name     = entry.get("name", "")
            statuses = entry.get("statuses", [])
            if statuses:
                preview  = self._status_preview(statuses[0], i18n)
                row_text = f"{name}: {preview}" if preview else name
            else:
                row_text = name
            self._status_list.Append((row_text,))

        if self._status_list.GetItemCount() > 0:
            self._status_list.Focus(0)
            self._status_list.Select(0)
        self.Layout()

    def _my_status_label(self, i18n) -> str:
        if self._my_statuses:
            suffix = i18n.t("my_status_update")
        else:
            suffix = i18n.t("my_status_none")
        return f"{i18n.t('my_status')}: {suffix}"

    def _on_status_list_key_down(self, event):
        """Make Space activate the focused status item (same as Enter).

        Select() below fires EVT_LIST_ITEM_SELECTED -> _on_status_contact_
        selected() too, which is where the actual reset-position decision
        lives — see its own comment. This handler never resets
        _current_status_idx itself, so whichever of the two paths runs
        first still leaves the user's position intact.
        """
        if event.GetKeyCode() == wx.WXK_SPACE:
            idx = self._status_list.GetFocusedItem()
            if idx >= 0:
                self._status_list.Select(idx)
                if idx == 0:
                    self._open_my_status_dialog()
                else:
                    contact_idx = idx - 1
                    if 0 <= contact_idx < len(self._status_contacts):
                        self._selected_contact_idx = contact_idx
                        self._show_current_status()
        else:
            event.Skip()

    def _on_refresh(self, event):
        threading.Thread(target=self._load_statuses, daemon=True).start()

    # ── Status list selection / activation ───────────────────────────────────

    def _on_status_contact_selected(self, event):
        idx = event.GetIndex()
        if idx == 0:
            # My Status row selected — hide the inline viewer; dialog opens on activate
            self._selected_contact_idx = -1
            self._viewer_panel.Hide()
            self.Layout()
            return

        contact_idx = idx - 1          # offset: row 0 is My Status
        if contact_idx < 0 or contact_idx >= len(self._status_contacts):
            self._viewer_panel.Hide()
            self.Layout()
            return

        # Only jump back to the FIRST status when selecting a genuinely
        # different contact. This event also fires from Select() calls
        # elsewhere (e.g. Space re-activating the row the list already has
        # focused, while the user has since moved forward within the viewer
        # via Ctrl+Left/Right) — resetting unconditionally meant pressing
        # Space while sitting on "status 3 de 5" silently snapped it back to
        # "1 de 5" for no reason.
        if contact_idx != self._selected_contact_idx:
            self._current_status_idx = 0
        self._selected_contact_idx = contact_idx
        self._show_current_status()

    def _on_status_contact_activated(self, event):
        idx = event.GetIndex()
        if idx == 0:
            self._open_my_status_dialog()
        else:
            self._on_status_contact_selected(event)

    def _open_my_status_dialog(self):
        dlg    = MyStatusDialog(self.main_window, self._my_statuses)
        result = dlg.ShowModal()
        dlg.Destroy()
        if result == MyStatusDialog.RC_ADD_STATUS:
            # User wants to add a status — open the popup menu
            self._on_add_status(None)

    # ── Status viewer ────────────────────────────────────────────────────────

    def _show_current_status(self):
        if self._selected_contact_idx < 0:
            return
        entry    = self._status_contacts[self._selected_contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return

        i18n    = self.main_window.i18n
        total   = len(statuses)
        current = self._current_status_idx
        status  = statuses[current]

        msg_type = status.get("messageType", "")
        msg_obj  = status.get("message") or {}
        if msg_type == "conversation":
            content = msg_obj.get("conversation", "")
        elif msg_type == "extendedTextMessage":
            content = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
        elif msg_type == "imageMessage":
            img     = msg_obj.get("imageMessage") or {}
            caption = (img.get("caption") or "").strip()
            content = f"{i18n.t('photo')}: {caption}" if caption else i18n.t("photo")
        elif msg_type == "videoMessage":
            video   = msg_obj.get("videoMessage") or {}
            caption = (video.get("caption") or "").strip()
            content = f"{i18n.t('video')}: {caption}" if caption else i18n.t("video")
        else:
            content = msg_type or "?"

        nav_info = i18n.t("status_of").format(current=current + 1, total=total)
        label    = f"{entry.get('name', '')} — {nav_info}: {content}"
        self._status_content_label.SetLabel(label)

        # Switching to a (possibly different) status always stops whatever
        # video was playing — resuming stale audio/frames for a status the
        # user has since navigated away from would be actively wrong, not
        # just unhelpful.
        self._video_player.stop()
        self._video_local_path = None
        self._video_download_status_id = None
        self._video_bitmap.Hide()
        self._play_pause_btn.SetLabel(i18n.t("status_play_pause"))

        # Kept for the action handlers below (copy text, save media, open
        # video, reply) — all act on "whatever status is currently shown".
        self._current_status       = status
        self._current_status_entry = entry

        is_video = msg_type == "videoMessage"
        is_image = msg_type == "imageMessage"
        self._play_pause_btn.Show(is_video)
        self._save_media_btn.Show(is_video or is_image)

        # Copy-text applies to the actual text content: the full text for a
        # text status, or just the caption (not the "Foto:"/"Vídeo:" label
        # prefix _show_current_status() built above) for a media status.
        if msg_type in ("conversation", "extendedTextMessage"):
            copy_text = content
        elif msg_type == "imageMessage":
            copy_text = (msg_obj.get("imageMessage") or {}).get("caption", "").strip()
        elif msg_type == "videoMessage":
            copy_text = (msg_obj.get("videoMessage") or {}).get("caption", "").strip()
        else:
            copy_text = ""
        self._current_status_text = copy_text
        self._copy_text_btn.Show(bool(copy_text))

        # ── Like / reply — only for other people's statuses ────────────────
        status_key  = status.get("key", {})
        from_me     = status_key.get("fromMe", False)
        if not from_me:
            status_id = status_key.get("id", "")
            is_liked  = self._liked_statuses.get(status_id, False)
            i18n2     = self.main_window.i18n
            self._like_btn.SetLabel(
                i18n2.t("status_unlike") if is_liked else i18n2.t("status_like")
            )
            self._like_btn.Show()
            self._reply_label.Show()
            self._reply_field.Show()
            self._reply_send_btn.Show()
        else:
            self._like_btn.Hide()
            self._reply_label.Hide()
            self._reply_field.Hide()
            self._reply_send_btn.Hide()

        self._viewer_panel.Show()
        self.Layout()

        self.main_window.output(label, interrupt=True)

    # ── Status navigation (Ctrl+Left / Ctrl+Right) ───────────────────────────

    def _on_prev_status(self, event):
        if self._selected_contact_idx < 0:
            return
        entry    = self._status_contacts[self._selected_contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return
        self._current_status_idx = (self._current_status_idx - 1) % len(statuses)
        self._show_current_status()

    def _on_next_status(self, event):
        if self._selected_contact_idx < 0:
            return
        entry    = self._status_contacts[self._selected_contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return
        self._current_status_idx = (self._current_status_idx + 1) % len(statuses)
        self._show_current_status()

    # ── Like / unlike status ─────────────────────────────────────────────────

    def _on_like_status(self, event):
        """Toggle like/unlike on the currently displayed status."""
        if self._selected_contact_idx < 0:
            return
        entry    = self._status_contacts[self._selected_contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return
        status     = statuses[self._current_status_idx]
        status_key = status.get("key", {})
        status_id  = status_key.get("id", "")
        if not status_id:
            return

        is_liked = self._liked_statuses.get(status_id, False)
        emoji    = "" if is_liked else "❤️"

        # Build the reaction key for status@broadcast
        sender_jid = (
            status_key.get("participant", "")
            or entry.get("jid", "")
        )
        reaction_key = {
            "remoteJid":  "status@broadcast",
            "fromMe":     False,
            "id":         status_id,
            "participant": sender_jid,
        }

        mw = self.main_window
        ok = mw.send_reaction("status@broadcast", reaction_key, emoji)
        if ok:
            self._liked_statuses[status_id] = not is_liked
            i18n = mw.i18n
            new_label = i18n.t("status_unlike") if not is_liked else i18n.t("status_like")
            self._like_btn.SetLabel(new_label)
        else:
            wx.MessageBox(
                mw.i18n.t("status_like_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    # ── Play/pause video status (in-app: audio via BASS, frames via ffmpeg) ──
    #
    # See core/video_player.py's module docstring for the full explanation:
    # BASS alone is audio-only and can't decode WhatsApp's .mp4 either way,
    # so the video's audio is extracted to WAV (bundled ffmpeg) for BASS,
    # and its picture is decoded by that same ffmpeg binary as a capped-rate
    # JPEG frame sequence drawn into self._video_bitmap.

    def _on_play_pause_video(self, event):
        if self._current_status is None:
            return
        if self._current_status.get("messageType") != "videoMessage":
            return
        if self._video_player.is_playing:
            self._video_player.toggle_pause()
            self._update_play_pause_label()
            return
        status_id = self._current_status.get("key", {}).get("id", "")
        if self._video_local_path and self._video_download_status_id == status_id:
            # Already downloaded (e.g. finished playing once) — replay
            # without hitting the network again.
            self._video_bitmap.Show()
            self.Layout()
            self._video_player.load_and_play(self._video_local_path)
            self._update_play_pause_label()
            return
        threading.Thread(
            target=self._download_and_play_video,
            args=(self._current_status, status_id),
            daemon=True,
        ).start()

    def _download_and_play_video(self, status, status_id: str):
        mw = self.main_window
        try:
            b64 = mw.get_base64_from_media(status)
            if not b64:
                raise ValueError("empty media response")
            content = base64.b64decode(b64)
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(content)
            tmp.close()
            wx.CallAfter(self._start_downloaded_video, tmp.name, status_id)
        except Exception:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_video_open_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _start_downloaded_video(self, path: str, status_id: str):
        # The user may have navigated to a different status while this was
        # downloading — don't start playback for a status that isn't the
        # one currently shown.
        current_id = (self._current_status or {}).get("key", {}).get("id", "")
        if current_id != status_id:
            try:
                os.unlink(path)
            except Exception:
                pass
            return
        self._video_local_path = path
        self._video_download_status_id = status_id
        self._video_bitmap.Show()
        self.Layout()
        self._video_player.load_and_play(path)
        self._update_play_pause_label()

    def _update_play_pause_label(self):
        # Single toggle label ("Reproduzir/Pausar status"), same convention
        # this button already used before video playback existed at all —
        # its pressed/not-pressed meaning is announced via the state change
        # itself, not a swapping label.
        self._play_pause_btn.SetLabel(self.main_window.i18n.t("status_play_pause"))

    # ── Copy status text ──────────────────────────────────────────────────────

    def _on_copy_status_text(self, event):
        text = self._current_status_text
        mw   = self.main_window
        if not text:
            mw.output(mw.i18n.t("status_copy_error"))
            return
        import pyperclip
        try:
            pyperclip.copy(text)
            mw.output(mw.i18n.t("status_text_copied"))
        except Exception:
            wx.MessageBox(
                mw.i18n.t("status_copy_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    # ── Save status media (photo/video) ──────────────────────────────────────

    def _on_save_status_media(self, event):
        status = self._current_status
        if status is None:
            return
        msg_type = status.get("messageType", "")
        if msg_type not in ("imageMessage", "videoMessage"):
            return
        mw = self.main_window
        if msg_type == "imageMessage":
            mimetype = (status.get("message", {}).get("imageMessage") or {}).get("mimetype", "image/jpeg")
            ext = "." + (mimetype.split("/")[-1] if "/" in mimetype else "jpg")
            wildcard = f"{mw.i18n.t('photo')} (*{ext})|*{ext}|*.*|*.*"
        else:
            mimetype = (status.get("message", {}).get("videoMessage") or {}).get("mimetype", "video/mp4")
            ext = "." + (mimetype.split("/")[-1] if "/" in mimetype else "mp4")
            wildcard = f"{mw.i18n.t('video')} (*{ext})|*{ext}|*.*|*.*"

        with wx.FileDialog(
            self, mw.i18n.t("status_save_media"),
            defaultDir=get_downloads_folder(),
            defaultFile=f"status{ext}",
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            if dlg.ShowModal() != wx.ID_OK:
                return
            save_path = dlg.GetPath()

        threading.Thread(
            target=self._save_status_media_bg,
            args=(status, save_path),
            daemon=True,
        ).start()

    def _save_status_media_bg(self, status, save_path: str):
        mw = self.main_window
        try:
            b64 = mw.get_base64_from_media(status)
            if not b64:
                raise ValueError("empty media response")
            content = base64.b64decode(b64)
            with open(save_path, "wb") as fh:
                fh.write(content)
            wx.CallAfter(mw.output, mw.i18n.t("status_media_saved"))
        except Exception:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_media_save_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    # ── Reply to the currently viewed status ─────────────────────────────────

    def _on_send_status_reply(self, event):
        status = self._current_status
        entry  = self._current_status_entry
        if status is None or entry is None:
            return
        if status.get("key", {}).get("fromMe"):
            return  # no reply UI for own statuses — see _show_current_status()
        text = self._reply_field.GetValue().strip()
        if not text:
            return
        poster_jid = entry.get("jid", "")
        if not poster_jid:
            return
        threading.Thread(
            target=self._send_status_reply_bg,
            args=(poster_jid, text, status),
            daemon=True,
        ).start()

    def _send_status_reply_bg(self, poster_jid: str, text: str, status: dict):
        mw = self.main_window
        try:
            result = mw.send_text_message(poster_jid, text, quoted=status)
        except Exception:
            result = None
        # send_text_message() returns a message-id string or True on success,
        # or a dict ({"ok": False, ...}) on a definite failure.
        ok = bool(result) and not isinstance(result, dict)
        if ok:
            wx.CallAfter(self._on_status_reply_sent)
        else:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_reply_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _on_status_reply_sent(self):
        self._reply_field.SetValue("")
        self.main_window.output(self.main_window.i18n.t("status_reply_sent"))

    # ── Add status (PopupMenu) ───────────────────────────────────────────────

    def _on_add_status(self, event):
        i18n     = self.main_window.i18n
        menu     = wx.Menu()
        id_text  = wx.NewIdRef()
        id_media = wx.NewIdRef()
        menu.Append(id_text,  i18n.t("status_text"))
        menu.Append(id_media, i18n.t("status_photos_videos"))
        menu.Bind(wx.EVT_MENU, self._on_choose_text_status,  id=id_text)
        menu.Bind(wx.EVT_MENU, self._on_choose_media_status, id=id_media)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_choose_text_status(self, event):
        self._hide_post_panels()
        self._post_panel.Show()
        self._post_text_field.SetValue("")
        self._caption_field.SetValue("")
        self.Layout()
        self._post_text_field.SetFocus()

    def _on_choose_media_status(self, event):
        i18n = self.main_window.i18n
        wildcard = (
            f"{i18n.t('status_photos_videos')} "
            "(*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv)"
            "|*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv"
            f"|{i18n.t('attachment_document')} (*.*)|*.*"
        )
        dlg = wx.FileDialog(
            self,
            message=i18n.t("status_photos_videos"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._selected_media_paths = dlg.GetPaths()
            dlg.Destroy()
            self._hide_post_panels()
            self._media_post_panel.Show()
            self._media_caption_field.SetValue("")
            self._rebuild_media_attachment_list()
            self.Layout()
            self._media_caption_field.SetFocus()
        else:
            dlg.Destroy()

    def _on_close_post_panel(self, event):
        self._post_panel.Hide()
        self.Layout()
        self._status_list.SetFocus()

    def _on_close_media_panel(self, event):
        self._selected_media_paths = []
        self._media_post_panel.Hide()
        self.Layout()
        self._status_list.SetFocus()

    def _hide_post_panels(self):
        self._post_panel.Hide()
        self._media_post_panel.Hide()

    # ── Send text status ─────────────────────────────────────────────────────

    def _on_send_text_status(self, event):
        text    = self._post_text_field.GetValue().strip()
        caption = self._caption_field.GetValue().strip()
        if not text and not caption:
            return
        content = text or caption
        threading.Thread(
            target=self._send_text_status_bg,
            args=(content,),
            daemon=True,
        ).start()

    def _send_text_status_bg(self, text: str):
        """POST /api/{session}/send-text-storie (WPPConnect Server)."""
        mw  = self.main_window
        url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/send-text-storie"
        headers = {"Authorization": f"Bearer {mw.token}", "Content-Type": "application/json"}
        payload = {
            "text": text,
            "options": {
                "backgroundColor": "#25D366",
                "font": 2,
            }
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
            ok   = resp.status_code in (200, 201)
        except Exception:
            ok = False
        if ok:
            wx.CallAfter(self._on_status_sent)
        else:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _on_status_sent(self):
        self._post_panel.Hide()
        self._media_post_panel.Hide()
        self.Layout()
        self._status_list.SetFocus()
        self.main_window.output(self.main_window.i18n.t("status_posted"))
        threading.Thread(target=self._load_statuses, daemon=True).start()

    # ── Send media status ────────────────────────────────────────────────────

    def _on_add_more_media_files(self, event):
        i18n = self.main_window.i18n
        wildcard = (
            f"{i18n.t('status_photos_videos')} "
            "(*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv)"
            "|*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv"
            f"|{i18n.t('attachment_document')} (*.*)|*.*"
        )
        dlg = wx.FileDialog(
            self,
            message=i18n.t("status_photos_videos"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._selected_media_paths.extend(dlg.GetPaths())
            self._rebuild_media_attachment_list()
            self.Layout()
        dlg.Destroy()

    def _rebuild_media_attachment_list(self):
        """Rebuild the per-file remove-buttons to match _selected_media_paths."""
        i18n  = self.main_window.i18n
        panel = self._media_attachments_list_panel
        sizer = self._media_attachments_list_sizer
        for child in list(panel.GetChildren()):
            child.Destroy()
        sizer.Clear()
        for path in self._selected_media_paths:
            filename = os.path.basename(path)
            btn = wx.Button(
                panel,
                label=f"{i18n.t('remove_attachment')} {filename}",
            )
            btn.Bind(
                wx.EVT_BUTTON,
                lambda evt, p=path: self._on_remove_media_attachment(p),
            )
            sizer.Add(btn, 0, wx.BOTTOM, 3)
        panel.Layout()
        if self._media_post_panel.IsShown():
            self._media_post_panel.Layout()
            self.Layout()

    def _on_remove_media_attachment(self, path: str):
        """Remove one selected file and rebuild the list (or close the panel)."""
        self._selected_media_paths = [
            p for p in self._selected_media_paths if p != path
        ]
        if not self._selected_media_paths:
            self._on_close_media_panel(None)
        else:
            self._rebuild_media_attachment_list()

    def _on_send_media_status(self, event):
        if not self._selected_media_paths:
            return
        caption = self._media_caption_field.GetValue().strip()
        paths = list(self._selected_media_paths)
        threading.Thread(
            target=self._send_all_media_statuses_bg,
            args=(paths, caption),
            daemon=True,
        ).start()

    def _send_all_media_statuses_bg(self, paths: list, caption: str):
        for path in paths:
            self._send_media_status_bg(path, caption)

    def _send_media_status_bg(self, path: str, caption: str):
        mw = self.main_window
        try:
            with open(path, "rb") as fh:
                data_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )
            return
        ext      = os.path.splitext(path)[1].lower()
        mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ext in (".mp4", ".mov", ".avi", ".mkv"):
            media_type = "video"
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            media_type = "image"
        else:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )
            return

        endpoint = "send-image-storie" if media_type == "image" else "send-video-storie"
        url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/{endpoint}"
        headers = {"Authorization": f"Bearer {mw.token}", "Content-Type": "application/json"}
        payload = {
            "base64": f"data:{mimetype};base64,{data_b64}",
            "caption": caption,
        }
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=30)
            ok   = resp.status_code in (200, 201)
        except Exception:
            ok = False
        if ok:
            wx.CallAfter(self._on_status_sent)
        else:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    # ── Labels refresh ───────────────────────────────────────────────────────

    def refresh_labels(self):
        i18n = self.main_window.i18n

        self._list_label.SetLabel(i18n.t("status"))
        col = wx.ListItem()
        col.SetText(i18n.t("status"))
        self._status_list.SetColumn(0, col)

        self._add_status_btn.SetLabel(i18n.t("status_add"))
        self._prev_status_btn.SetLabel(i18n.t("status_prev"))
        self._next_status_btn.SetLabel(i18n.t("status_next"))
        self._play_pause_btn.SetLabel(i18n.t("status_play_pause"))
        self._copy_text_btn.SetLabel(i18n.t("status_copy_text"))
        self._save_media_btn.SetLabel(i18n.t("status_save_media"))
        self._reply_label.SetLabel(i18n.t("status_reply_label"))
        self._reply_send_btn.SetLabel(i18n.t("status_reply_send"))
        # Like button label depends on current state; only refresh if visible
        if self._like_btn.IsShown():
            if self._selected_contact_idx >= 0:
                entry    = self._status_contacts[self._selected_contact_idx]
                statuses = entry.get("statuses", [])
                if statuses and self._current_status_idx < len(statuses):
                    status_id = statuses[self._current_status_idx].get("key", {}).get("id", "")
                    is_liked  = self._liked_statuses.get(status_id, False)
                    self._like_btn.SetLabel(
                        i18n.t("status_unlike") if is_liked else i18n.t("status_like")
                    )
        self._post_send_btn.SetLabel(i18n.t("status_send"))
        self._post_text_label.SetLabel(i18n.t("status_text_label"))
        self._media_send_btn.SetLabel(i18n.t("status_send"))
        self._media_add_more_btn.SetLabel(i18n.t("add_more_files"))
        self._post_close_btn.SetLabel(i18n.t("close"))
        self._media_close_btn.SetLabel(i18n.t("close"))

        # Refresh the "My Status" row (index 0) if the list is populated
        if not self._list_is_loading and self._status_list.GetItemCount() > 0:
            self._status_list.SetItemText(0, self._my_status_label(i18n))
