"""StatusComposerMixin — part of StatusPanel (see status_tab/__init__.py).

Moved verbatim out of status_panel.py. Methods run with ``self`` bound to
the StatusPanel instance, so every attribute set in StatusPanel.__init__/
init_UI is available here.
"""

import base64
import logging
import mimetypes
import os
import threading
import requests
import wx
from status_tab.status_rules import (
    STATUS_POST_UNCONFIRMED,
    _post_was_rejected,
    status_upload_timeout,
)
from status_tab.unsent_status import FAILED, MEDIA, TEXT, UNCONFIRMED, unsent_post
from core.api_client import (
    api_post,
    redact_api_url,
)
from ui.dialogs.emoji_picker import choose_and_insert_emoji
from core.utils import normalize_line_separators


class StatusComposerMixin:
    """Posting a status: the composer panels and sending text and media statuses.
    """

    # ── Add status (PopupMenu) ───────────────────────────────────────────────

    def _on_add_status(self, event):
        i18n     = self.main_window.i18n
        menu     = wx.Menu()
        id_text  = wx.NewIdRef()
        id_media = wx.NewIdRef()
        id_voice = wx.NewIdRef()
        menu.Append(id_text,  i18n.t("status_text"))
        menu.Append(id_media, i18n.t("status_photos_videos"))
        menu.Append(id_voice, i18n.t("status_audio"))
        menu.Bind(wx.EVT_MENU, self._on_choose_text_status,  id=id_text)
        menu.Bind(wx.EVT_MENU, self._on_choose_media_status, id=id_media)
        menu.Bind(wx.EVT_MENU, self._on_choose_voice_status, id=id_voice)
        self.PopupMenu(menu)
        menu.Destroy()

    def _on_choose_text_status(self, event):
        self._enter_status_composer(self._post_panel)
        self._post_text_field.SetValue("")
        self._caption_field.SetValue("")
        self._post_text_field.SetFocus()

    def _on_open_post_emoji_picker(self, event):
        """Open the shared picker while composing a text status."""
        if not self._post_panel.IsShown() or not self._post_text_field.IsEnabled():
            return
        choose_and_insert_emoji(self, self._post_text_field, self.main_window.i18n)

    def _on_choose_media_status(self, event):
        i18n = self.main_window.i18n
        wildcard = (
            f"{i18n.t('status_photos_videos_audio')} "
            "(*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv;"
            "*.mp3;*.ogg;*.wav;*.m4a;*.aac)"
            "|*.jpg;*.jpeg;*.png;*.gif;*.webp;*.mp4;*.avi;*.mov;*.mkv;"
            "*.mp3;*.ogg;*.wav;*.m4a;*.aac"
            f"|{i18n.t('attachment_document')} (*.*)|*.*"
        )
        dlg = wx.FileDialog(
            self,
            message=i18n.t("status_photos_videos_audio"),
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_MULTIPLE | wx.FD_FILE_MUST_EXIST,
        )
        if dlg.ShowModal() == wx.ID_OK:
            self._selected_media_paths = dlg.GetPaths()
            dlg.Destroy()
            self._enter_status_composer(self._media_post_panel)
            self._media_caption_field.SetValue("")
            self._rebuild_media_attachment_list()
            self._media_caption_field.SetFocus()
        else:
            dlg.Destroy()

    def _on_close_post_panel(self, event):
        self._leave_status_composer()

    def _on_close_media_panel(self, event):
        self._selected_media_paths = []
        self._leave_status_composer()

    def _hide_post_panels(self):
        # Disable as well as hide, so controls from the two inactive choices
        # cannot remain keyboard-focusable or exposed as enabled actions in
        # the Windows/MSAA accessibility tree while another composer is open.
        for panel in (
            self._post_panel,
            self._media_post_panel,
            self._voice_post_panel,
        ):
            panel.Disable()
            panel.Hide()

    def _is_status_composer_open(self) -> bool:
        return any(
            panel.IsShown()
            for panel in (
                self._post_panel,
                self._media_post_panel,
                self._voice_post_panel,
            )
        )

    def _enter_status_composer(self, panel):
        """Show only the selected Add Status flow.

        The status browser and every other composer are deliberately hidden:
        recording controls and their shortcuts belong to Audio, attachment
        controls belong to Media, and text controls belong to Text. Keeping
        them beside the status list made the main screen needlessly crowded.
        """
        self._hide_post_panels()
        self._hide_status_viewer()
        self._video_player.stop()
        for widget in (
            self._add_status_btn,
            self._refresh_status_btn,
            self._list_label,
            self._status_list,
        ):
            widget.Hide()
        panel.Enable()
        panel.Show()
        self.Layout()

    def _leave_status_composer(self):
        """Return from any Add Status flow to the clean status browser."""
        self._hide_post_panels()
        for widget in (
            self._add_status_btn,
            self._refresh_status_btn,
            self._list_label,
            self._status_list,
        ):
            widget.Show()
        self.Layout()
        self._status_list.SetFocus()
        if getattr(self, "_unsent_redraw_pending", False):
            # A post that failed while composing waited for the list
            # (status_tab/unsent_status.py).
            wx.CallAfter(self._flush_unsent_redraw)

    # ── Record & post voice status ───────────────────────────────────────────

    def _on_choose_voice_status(self, event):
        """Open the voice status post panel in prepared state (NOT recording yet).
        User can click Record or press Ctrl+R to start recording."""
        self._enter_status_composer(self._voice_post_panel)

        self._is_recording = False
        self._recording_paused = False
        self._recording_frames = []
        self._stop_recorded_audio_preview()
        self._stop_recording_stream()

        i18n = self.main_window.i18n
        self._voice_status_lbl.SetLabel(i18n.t("recording_in_progress"))
        self._voice_start_btn.SetLabel(i18n.t("record_voice_message"))
        self._voice_start_btn.Show()
        self._voice_pause_btn.Hide()
        self._voice_play_btn.Hide()
        self._voice_send_btn.Hide()
        # Audio is a self-contained flow. Before capture starts this is the
        # Close action; once recording starts _on_stream_opened relabels the
        # same control to Discard, exactly like the conversation recorder.
        self._voice_close_btn.SetLabel(i18n.t("close"))
        self._voice_close_btn.Show()

        self._voice_start_btn.SetFocus()

    # ── One post at a time ───────────────────────────────────────────────────
    #
    # Post sends in the background and the composer stays open until it ends:
    # a video takes a while to upload, and a second press of Post (or Enter)
    # started a second upload, so the status went out twice. Every post press
    # goes through _begin_status_post(); the post ends in _end_status_post(),
    # whatever its outcome.

    def _begin_status_post(self) -> bool:
        i18n = self.main_window.i18n
        if getattr(self, "_status_post_in_flight", False):
            self.main_window.output(i18n.t("status_post_in_progress"), interrupt=True)
            return False
        self._status_post_in_flight = True
        self.main_window.output(i18n.t("status_posting"), interrupt=True)
        return True

    def _end_status_post(self):
        self._status_post_in_flight = False

    # ── Send text status ─────────────────────────────────────────────────────

    def _on_send_text_status(self, event):
        text    = normalize_line_separators(self._post_text_field.GetValue()).strip()
        caption = normalize_line_separators(self._caption_field.GetValue()).strip()
        if not text and not caption:
            return
        if not self._begin_status_post():
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
        unconfirmed = False
        try:
            resp = api_post(url, json=payload, headers=headers, timeout=60)
            ok   = resp.status_code in (200, 201)
            logging.info(
                "[status_post] POST %s -> HTTP %s, body=%.300s",
                redact_api_url(url), resp.status_code, (resp.text or "")[:300],
            )
            if ok:
                # Guard against the false-success path: with the status.layer.js
                # async patch the server now surfaces the real post result, and
                # a rejected status arrives as HTTP 201 wrapping
                # sendMsgResult.messageSendResult = "ERROR_UNKNOWN" (ack stays
                # 0 — WhatsApp never accepted it). Any of those must be
                # reported as an error instead of "posted".
                try:
                    if _post_was_rejected(resp.json()):
                        ok = False
                except Exception:
                    pass
        except requests.exceptions.Timeout as exc:
            ok = False
            # Sent, and no answer: it may be up (see _send_media_status_bg()).
            unconfirmed = not isinstance(exc, requests.exceptions.ConnectTimeout)
            logging.warning("[status_post] POST %s for %s", "unconfirmed" if unconfirmed
                            else "failed", redact_api_url(url))
        except Exception as exc:
            ok = False
            logging.warning("[status_post] POST failed for %s: %s",
                            redact_api_url(url), exc)
        wx.CallAfter(self._end_status_post)
        if not ok:
            # Kept in the Status list to try again (status_tab/unsent_status.py).
            wx.CallAfter(self._remember_unsent_status, unsent_post(
                TEXT, UNCONFIRMED if unconfirmed else FAILED, text=text))
        if ok:
            wx.CallAfter(self._on_status_sent)
        elif unconfirmed:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_post_unconfirmed"),
                mw.app_name,
                wx.OK | wx.ICON_WARNING,
            )
        else:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _on_status_sent(self):
        self._leave_status_composer()
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
        if not self._begin_status_post():
            return
        caption = normalize_line_separators(self._media_caption_field.GetValue()).strip()
        paths = list(self._selected_media_paths)
        threading.Thread(
            target=self._send_all_media_statuses_bg,
            args=(paths, caption),
            daemon=True,
        ).start()

    def _send_all_media_statuses_bg(self, paths: list, caption: str):
        """Send every file in *paths* sequentially, then report once.

        Each per-file helper is called with report_result=False so a batch
        where several files fail doesn't stack one blocking MessageBox per
        failure — that used to flood the screen with "status_error" dialogs
        one after another. Failures are still logged individually by the
        helpers; only the popup is deferred to a single summary here.

        Every call is additionally wrapped: a helper that raises instead of
        returning False would otherwise tear out of this loop, skipping every
        remaining file AND the summary dialog below — the batch would just
        stop, silently, on a background thread. That really happened via
        _send_status_voice_bg()'s try/finally-with-no-except; it is fixed at
        the source too, but the loop shouldn't depend on each helper
        remembering to catch everything.
        """
        mw = self.main_window
        failures = unconfirmed = 0
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            try:
                if ext in (".mp3", ".ogg", ".wav", ".m4a", ".aac"):
                    # A picked audio file goes through the real voice-status
                    # path (transcodes to OGG/Opus via ffmpeg first) — same
                    # endpoint a recorded voice status uses, not the image/
                    # video one below, which has no audio branch at all. Voice
                    # notes don't carry a caption in the official client either,
                    # so it's intentionally dropped here.
                    ok = self._send_status_voice_bg(path, report_result=False)
                else:
                    ok = self._send_media_status_bg(path, caption, report_result=False)
            except Exception:
                logging.exception("[status] Unexpected failure sending %s as status", path)
                ok = False
            if ok == STATUS_POST_UNCONFIRMED:
                unconfirmed += 1
            elif ok is not True:
                failures += 1
            if ok is not True:
                # Kept in the Status list to try again (status_tab/unsent_status.py).
                wx.CallAfter(self._remember_unsent_status, unsent_post(
                    MEDIA, UNCONFIRMED if ok == STATUS_POST_UNCONFIRMED else FAILED,
                    path=path, caption=caption))
        wx.CallAfter(self._end_status_post)
        if unconfirmed:
            # It may be up already: look before posting again.
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_post_unconfirmed"),
                mw.app_name,
                wx.OK | wx.ICON_WARNING,
            )
        if failures:
            wx.CallAfter(
                wx.MessageBox,
                f"{mw.i18n.t('status_error')} ({failures}/{len(paths)})",
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _send_media_status_bg(self, path: str, caption: str, report_result: bool = True):
        mw = self.main_window
        ext      = os.path.splitext(path)[1].lower()
        mimetype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ext in (".mp4", ".mov", ".avi", ".mkv"):
            media_type = "video"
        elif ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            media_type = "image"
        else:
            logging.error("[status media] Unsupported file extension for status: %s", path)
            if report_result:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
            return False

        try:
            with open(path, "rb") as fh:
                data_b64 = base64.b64encode(fh.read()).decode("utf-8")
        except Exception as exc:
            logging.error("[status media] Failed to read/encode %s: %s", path, exc)
            if report_result:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
            return False

        endpoint = "send-image-storie" if media_type == "image" else "send-video-storie"
        url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/{endpoint}"
        headers = {"Authorization": f"Bearer {mw.token}", "Content-Type": "application/json"}
        # statusController.ts's sendImageStorie()/sendVideoStorie() (real,
        # unmodified upstream — `const { path } = req.body`) only ever read
        # a "path" field — it accepts either a real filesystem path or,
        # per sender.layer.js's sendImageStatus()/sendVideoStatus(), a full
        # `data:...;base64,...` URI interchangeably. This used to send the
        # payload under a "base64" key instead, which that handler never
        # reads at all — every status image/video post from the media
        # picker silently failed with pathFile undefined.
        payload = {
            "path": f"data:{mimetype};base64,{data_b64}",
            "caption": caption,
        }
        try:
            resp = api_post(url, json=payload, headers=headers,
                            timeout=status_upload_timeout(os.path.getsize(path)))
            ok   = resp.status_code in (200, 201)
            if not ok:
                logging.warning(
                    "[status media] %s failed: HTTP %s: %s",
                    endpoint, resp.status_code, (resp.text or "")[:200],
                )
        except requests.exceptions.Timeout as exc:
            if not isinstance(exc, requests.exceptions.ConnectTimeout):
                # Sent, and no answer: it may be up. Never reported as failed,
                # which invited posting the same status again.
                logging.warning("[status media] %s unconfirmed: timed out", endpoint)
                return STATUS_POST_UNCONFIRMED
            ok = False
            logging.warning("[status media] %s failed: %s", endpoint, type(exc).__name__)
        except Exception as exc:
            ok = False
            logging.warning("[status media] %s failed: %s", endpoint, exc)
        if ok:
            wx.CallAfter(self._on_status_sent)
        elif report_result:
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )
        return ok
