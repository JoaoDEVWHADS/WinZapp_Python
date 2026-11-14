"""StatusMediaMixin — part of StatusPanel (see status_tab/__init__.py).

Moved verbatim out of status_panel.py. Methods run with ``self`` bound to
the StatusPanel instance, so every attribute set in StatusPanel.__init__/
init_UI is available here.
"""

import logging
import os
import tempfile
import threading
import wx
from status_tab.status_rules import (
    _download_status_media,
    _status_media_save_info,
)
from core.save_location import resolve_save_dialog_folder
from core.save_dialog_selection import schedule_deselect_extension


class StatusMediaMixin:
    """A status's media: video playback, copying the text and saving the file.
    """

    # ── Play/pause video status (in-app: audio via BASS, frames via ffmpeg) ──
    #
    # See core/video_player.py's module docstring for the full explanation:
    # BASS alone is audio-only and can't decode WhatsApp's .mp4 either way,
    # so the video's audio is extracted to WAV (bundled ffmpeg) for BASS,
    # and its picture is decoded by that same ffmpeg binary as a capped-rate
    # JPEG frame sequence drawn into self._video_bitmap.

    def _on_video_frame_size_known(self, width: int, height: int):
        """VideoPlayer callback (see core/video_player.py's own comment):
        fires once per playback with the first frame's actual on-screen
        size, so the fixed 320x240 placeholder box can shrink-wrap to it —
        same as a still photo is sized to its own content, instead of
        leaving a blank gap around a video whose aspect ratio doesn't match
        that box (reported live as the video "not showing completely" even
        once it was no longer literally clipped)."""
        self._video_bitmap.SetMinSize((width, height))
        self.Layout()

    def _on_play_pause_video(self, event):
        """Play/pause the current status's media — video (picture + audio)
        or audio-only. Named for video since that's what this predates, but
        VideoPlayer already plays an audio-only file just fine on its own
        (BASS decodes it directly; ffmpeg's frame pipe just produces nothing
        for a file with no video stream) — the only thing missing for audio
        statuses was ever showing this button at all (see _show_current_status())."""
        if self._current_status is None:
            return
        msg_type = self._current_status.get("messageType")
        if msg_type not in ("videoMessage", "audioMessage"):
            return
        if self._video_player.is_playing:
            self._video_player.toggle_pause()
            self._update_play_pause_label()
            return
        status_id = self._current_status.get("key", {}).get("id", "")
        if self._video_local_path and self._video_download_status_id == status_id:
            # Already downloaded (e.g. finished playing once) — replay
            # without hitting the network again.
            if msg_type == "videoMessage":
                self._video_bitmap.Show()
                self.Layout()
            self._video_player.load_and_play(self._video_local_path)
            self._update_play_pause_label()
            return
        threading.Thread(
            target=self._download_and_play_video,
            args=(self._current_status, status_id, msg_type),
            daemon=True,
        ).start()

    def _download_and_play_video(self, status, status_id: str, msg_type: str = "videoMessage"):
        mw = self.main_window
        # Audio statuses arrive as Opus/OGG (same as voice messages), never
        # .mp4 — the suffix only matters for BASS's own format sniffing
        # fallback and for a sensible temp filename, not correctness.
        suffix = ".mp4" if msg_type == "videoMessage" else ".ogg"
        try:
            content = _download_status_media(mw, status)
            if not bool(self):
                return
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(content)
            tmp.close()
            if not bool(self):
                try:
                    os.unlink(tmp.name)
                except Exception:
                    pass
                return
            wx.CallAfter(self._start_downloaded_video, tmp.name, status_id, msg_type)
        except Exception:
            if not bool(self):
                return
            wx.CallAfter(
                wx.MessageBox,
                mw.i18n.t("status_video_open_error"),
                mw.app_name,
                wx.OK | wx.ICON_ERROR,
            )

    def _start_downloaded_video(self, path: str, status_id: str, msg_type: str = "videoMessage"):
        if not bool(self):
            try:
                os.unlink(path)
            except Exception:
                pass
            return
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
        try:
            if msg_type == "videoMessage":
                self._video_bitmap.Show()
                self.Layout()
            self._video_player.load_and_play(path)
            self._update_play_pause_label()
        except (RuntimeError, wx.wxAssertionError, Exception) as exc:
            logging.warning("[StatusPanel] _start_downloaded_video error: %s", exc)

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
        mw = self.main_window
        save_info = _status_media_save_info(msg_type, status.get("message", {}), mw.i18n)
        if save_info is None:
            return
        ext, wildcard = save_info

        with wx.FileDialog(
            self, mw.i18n.t("status_save_media"),
            defaultDir=resolve_save_dialog_folder(mw.settings),
            # No ext here: the native Save dialog selects the whole suggested
            # name for editing, extension included, so renaming it loses the
            # extension unless retyped by hand — Windows re-appends it from
            # wildcard's first filter (built from this same ext) when nothing
            # is typed, so this changes nothing about what gets saved.
            defaultFile="status",
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dlg:
            # Belt and suspenders: Windows still visually selects the
            # extension it auto-completes into the box regardless of the
            # above — see core/save_dialog_selection.py for why and how.
            schedule_deselect_extension("status")
            if dlg.ShowModal() != wx.ID_OK:
                return
            save_path = dlg.GetPath()
        mw.remember_save_folder(save_path)

        threading.Thread(
            target=self._save_status_media_bg,
            args=(status, save_path),
            daemon=True,
        ).start()

    def _save_status_media_bg(self, status, save_path: str):
        mw = self.main_window
        try:
            content = _download_status_media(mw, status)
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
