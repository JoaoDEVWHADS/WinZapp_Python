"""StatusViewerMixin — part of StatusPanel (see status_tab/__init__.py).

Moved verbatim out of status_panel.py. Methods run with ``self`` bound to
the StatusPanel instance, so every attribute set in StatusPanel.__init__/
init_UI is available here.
"""

import threading
import wx
from ui.media_viewer import MediaViewerDialog
from status_tab.status_dialogs import MyStatusDialog
from status_tab.status_rules import (
    _download_status_media,
    _status_content_label,
    _status_media_extension,
)
from core.utils import is_voice_message


class StatusViewerMixin:
    """Viewing statuses: my-status dialog, the media viewer, the legacy viewer,
    previous/next and viewed marks.
    """

    def _open_my_status_dialog(self):
        dlg    = MyStatusDialog(self.main_window, self._my_statuses)
        result = dlg.ShowModal()
        deleted = list(dlg.deleted_status_ids)
        dlg.Destroy()
        if deleted:
            # The dialog edited this same list: redraw the "My status" row.
            self._populate_list(self._my_statuses, self._status_contacts)
        if result == MyStatusDialog.RC_ADD_STATUS:
            # User wants to add a status — open the popup menu
            self._on_add_status(None)

    # ── Unified status media viewer ─────────────────────────────────────────

    def _open_status_media_viewer(self, contact_idx: int):
        if contact_idx < 0 or contact_idx >= len(self._status_contacts):
            return
        entry = self._status_contacts[contact_idx]
        statuses = entry.get("statuses", [])
        if not statuses:
            return

        items = [self._status_to_media_viewer_item(entry, status) for status in statuses]
        start_index = max(0, min(self._current_status_idx, len(items) - 1))
        dlg = MediaViewerDialog(
            self,
            self.main_window,
            items,
            start_index=start_index,
            on_item_opened=self._on_viewer_status_opened,
            is_liked=self._viewer_status_is_liked,
            on_like=self._viewer_like_status,
            on_reply=self._viewer_reply_status,
            describe_label=self._viewer_describe_label,
            on_describe=self._viewer_describe_status,
        )
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
            row = self._status_contact_row.get(contact_idx)
            if row is not None and 0 <= row < self._status_list.GetItemCount():
                try:
                    self._status_list.Focus(row)
                    self._status_list.Select(row)
                    self._status_list.SetFocus()
                except Exception:
                    pass

    def _status_to_media_viewer_item(self, entry: dict, status: dict) -> dict:
        i18n = self.main_window.i18n
        msg_type = status.get("messageType", "")
        msg_obj = status.get("message") or {}
        key = status.get("key", {})
        status_id = key.get("id", "")
        from_me = bool(key.get("fromMe", False))
        label = entry.get("name", "")

        item = {
            "status": status,
            "entry": entry,
            "status_id": status_id,
            "from_me": from_me,
            "label": label,
        }

        if msg_type in ("conversation", "extendedTextMessage"):
            if msg_type == "conversation":
                text = msg_obj.get("conversation", "")
            else:
                text = (msg_obj.get("extendedTextMessage") or {}).get("text", "")
            item.update(kind="text", text=text)
            return item

        vm_mode = (self.main_window.settings.get("user_interface", {}) if hasattr(self, "main_window") and self.main_window and hasattr(self.main_window, "settings") else {}).get("voice_message_mode", "voice_message")
        is_ptt = is_voice_message(msg_obj) or bool(isinstance(msg_obj, dict) and is_voice_message({"messageType": "audioMessage", "message": msg_obj}))
        audio_label_key = "message_type_voice_message" if (vm_mode == "voice_message" and is_ptt) else "message_type_audio"
        type_map = {
            "imageMessage": ("image", ".jpg", "photo"),
            "videoMessage": ("video", ".mp4", "video"),
            "audioMessage": ("audio", ".ogg", audio_label_key),
        }
        if msg_type in type_map:
            kind, default_ext, label_key = type_map[msg_type]
            inner = msg_obj.get(msg_type) or {}
            ext = _status_media_extension(inner.get("mimetype"), default_ext)
            caption = str(inner.get("caption") or "")

            def _loader(st=status):
                return _download_status_media(self.main_window, st)

            item.update(
                kind=kind,
                loader=_loader,
                extension=ext,
                filename=f"status{ext}",
                caption=caption,
                media_label=i18n.t(label_key),
                is_ptt=is_ptt,
            )
            return item

        # Documents, stickers, contacts and any future status type still open
        # in the same modal window as accessible read-only text rather than
        # silently doing nothing.
        item.update(kind="text", text=_status_content_label(msg_type, msg_obj, i18n, getattr(self.main_window, "settings", None)))
        return item

    def _on_viewer_status_opened(self, item: dict, index: int):
        """The ONLY place where another person's status becomes viewed."""
        self._current_status_idx = index
        self._current_status = item.get("status")
        self._current_status_entry = item.get("entry")
        status_id = item.get("status_id", "")
        if status_id and not item.get("from_me"):
            self._mark_status_viewed(status_id)
        self._update_focused_status_row_text()

    def _viewer_status_is_liked(self, item: dict) -> bool:
        return self._is_status_liked(item.get("status_id", ""))

    def _viewer_like_status(self, item: dict, done):
        """Toggle the native status reaction from the separate media viewer."""
        status = item.get("status") or {}
        entry = item.get("entry") or {}
        status_key = status.get("key", {})
        status_id = item.get("status_id", "")
        if not status_id:
            wx.CallAfter(done, False)
            return

        is_liked = self._is_status_liked(status_id)

        sender_jid = status_key.get("participant", "") or entry.get("jid", "")
        if not sender_jid:
            wx.CallAfter(done, False)
            return

        reaction_key = dict(status_key)
        reaction_key["remoteJid"] = "status@broadcast"
        if not reaction_key.get("participant"):
            reaction_key["participant"] = sender_jid

        mw = self.main_window

        def _send_like():
            try:
                ok = bool(mw.send_reaction(
                    "status@broadcast",
                    reaction_key,
                    "" if is_liked else "❤️",
                ))
            except Exception:
                ok = False
            if ok:
                wx.CallAfter(self._on_like_sent, status_id, not is_liked)
                wx.CallAfter(done, True)
            else:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_like_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
                wx.CallAfter(done, False)

        threading.Thread(target=_send_like, daemon=True).start()

    def _viewer_reply_status(self, item: dict, text: str, done):
        status = item.get("status") or {}
        entry = item.get("entry") or {}
        poster_jid = entry.get("jid", "")
        if not poster_jid or status.get("key", {}).get("fromMe"):
            wx.CallAfter(done, False)
            return

        def _send():
            try:
                result = self.main_window.send_text_message(
                    poster_jid, text, quoted=status
                )
                ok = bool(result) and not isinstance(result, dict)
            except Exception:
                ok = False
            wx.CallAfter(done, ok)

        threading.Thread(target=_send, daemon=True).start()

    # ── Status viewer ────────────────────────────────────────────────────────

    def _show_current_status(self, announce: bool = True):
        """Refresh the viewer for whatever status is currently selected.

        *announce* controls whether the "Nome — status X de Y: conteúdo"
        label is also spoken. Arrow-key navigation through the CONTACT list
        (_on_status_contact_selected) passes False for this: NVDA/JAWS
        already read the newly-focused list item on their own, so speaking
        it again here was pure redundant chatter on every single arrow
        press. Explicit status navigation — Ctrl+Left/Right between a
        contact's own statuses, and Space to open/activate the focused
        contact — still announces, since neither of those has an
        equivalent native readout to fall back on.
        """
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
        content  = _status_content_label(msg_type, msg_obj, i18n, getattr(self.main_window, "settings", None))

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
        # Undo whatever shrink-to-content _on_video_frame_size_known() did
        # for the video just left behind — otherwise the NEXT video's first
        # frame gets fitted against that leftover (often much smaller) box
        # instead of the real 320x240 baseline, compounding smaller and
        # smaller across consecutive status videos.
        self._video_bitmap.SetMinSize((320, 240))
        self._play_pause_btn.SetLabel(i18n.t("status_play_pause"))

        # Kept for the action handlers below (copy text, save media, open
        # video, reply) — all act on "whatever status is currently shown".
        self._current_status       = status
        self._current_status_entry = entry

        is_video = msg_type == "videoMessage"
        is_audio = msg_type == "audioMessage"
        is_image = msg_type == "imageMessage"
        self._play_pause_btn.Show(is_video or is_audio)
        self._save_media_btn.Show(is_video or is_image or is_audio)
        self._update_status_describe_button()

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
            # In dialog mode (the default), a status is marked viewed only
            # by MediaViewer's on_item_opened callback, after the user
            # explicitly activates it — see _on_viewer_status_opened().
            # _show_current_status() itself is now reachable only in
            # classic/inline mode (Settings > Interface do usuário >
            # "Mostrar os status em player separado" unchecked — see
            # _use_status_media_viewer_dialog()), where it is the ONLY
            # place a status ever gets marked viewed, exactly like before
            # that setting existed: arrowing to a contact there immediately
            # shows (and views) their status, same as it always did.
            if status_id:
                self._mark_status_viewed(status_id)
            is_liked  = self._is_status_liked(status_id)
            i18n2     = self.main_window.i18n
            self._like_btn.SetLabel(
                i18n2.t("status_unlike") if is_liked else i18n2.t("status_like")
            )
            self._like_btn.Show()
            self._reply_label.Show()
            self._reply_field.Show()
            self._reply_send_btn.Show(bool(self._reply_field.GetValue().strip()))
        else:
            self._like_btn.Hide()
            self._reply_label.Hide()
            self._reply_field.Hide()
            self._reply_send_btn.Hide()

        self._viewer_panel.Show()
        self.Layout()

        self._update_focused_status_row_text()

        if announce:
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
        # Wraps back around to the first status, mirroring _on_prev_status()
        # wrapping back to the last one.
        self._current_status_idx = (self._current_status_idx + 1) % len(statuses)
        self._show_current_status()

    # ── Viewed status tracking (drives the "Vistos" section) ────────────────

    # Same rationale/shape as _MAX_REMEMBERED_LIKES right below: WPPConnect
    # exposes no server-side "mark status as seen" API to call (see this
    # module's own docstring — the whole status list is built from live
    # status@broadcast events, nothing is ever queried on demand), so
    # "viewed" is tracked purely locally and never shrinks on its own.
    _MAX_REMEMBERED_VIEWED = 2000

    def _mark_status_viewed(self, status_id: str):
        """Remember that this status has been opened, persisted the same
        way _on_like_sent() remembers a like — read back by _parse_statuses()
        to decide whether a contact's whole set of current statuses counts
        as fully "viewed" (see its own "viewed_all" comment) for the
        Recentes/Vistos split in _populate_list().
        """
        mw = self.main_window
        section = mw.settings.setdefault("status_panel", {})
        remembered = section.setdefault("viewed_status_ids", [])
        if status_id not in remembered:
            remembered.append(status_id)
            if len(remembered) > self._MAX_REMEMBERED_VIEWED:
                del remembered[:len(remembered) - self._MAX_REMEMBERED_VIEWED]
            mw.save_settings()
