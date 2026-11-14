"""StatusVoiceMixin — part of StatusPanel (see status_tab/__init__.py).

Moved verbatim out of status_panel.py. Methods run with ``self`` bound to
the StatusPanel instance, so every attribute set in StatusPanel.__init__/
init_UI is available here.
"""

import base64
import logging
import os
import sound_lib.stream as sl_stream
import tempfile
import threading
import wave
import wx
from core.audio_devices import (
    RECORDING_SAMPLE_CONFIGS,
    fallback_input_device_indices,
    find_input_device_index,
)
import requests

from core.api_client import api_post
from core.focus_cloak import cloak_panel_focus_fallback
from status_tab.status_rules import STATUS_POST_UNCONFIRMED, status_upload_timeout
try:
    import pyaudio
except ImportError:
    pyaudio = None


class StatusVoiceMixin:
    """Recording, previewing and posting a voice status.
    """

    def _on_ctrl_r_shortcut(self, event):
        """Ctrl+R shortcut handler for status panel.
        It belongs only to the Audio composer selected from Add Status: start
        if idle, or send if recording. It must not open Audio from the clean
        Status browser, otherwise audio controls leak outside their option."""
        if self._voice_post_panel.IsShown():
            if not self._is_recording:
                if not self._recording_starting:
                    self._start_voice_recording()
            else:
                self._on_send_voice_status(None)

    def _on_ctrl_shift_p_shortcut(self, event):
        """Ctrl+Shift+P shortcut handler to pause/resume voice recording."""
        if self._voice_post_panel.IsShown() and self._is_recording:
            self._toggle_pause_voice_recording(event)

    def _on_ctrl_p_shortcut(self, event):
        """Ctrl+P plays/stops the paused recording, matching conversations."""
        if (
            self._voice_post_panel.IsShown()
            and self._is_recording
            and self._recording_paused
        ):
            self._toggle_play_recorded_audio(event)

    def _on_ctrl_shift_d_shortcut(self, event):
        """Ctrl+Shift+D shortcut handler to discard voice recording/panel."""
        if self._voice_post_panel.IsShown():
            self._on_close_voice_panel(event)

    def _on_record_voice_button(self, event):
        if not self._is_recording:
            if not self._recording_starting:
                self._start_voice_recording()
        else:
            self._on_send_voice_status(event)

    def _start_voice_recording(self):
        """Start recording voice audio stream."""
        if pyaudio is None:
            self.main_window.output(self.main_window.i18n.t("voice_recording_unavailable"))
            return

        self._recording_frames = []
        self._recording_paused = False

        def _callback(in_data, frame_count, time_info, status):
            if not self._recording_paused:
                self._recording_frames.append(in_data)
            return (None, pyaudio.paContinue)

        if self._recording_pa is None:
            try:
                self._recording_pa = pyaudio.PyAudio()
            except Exception as exc:
                logging.error("[status audio] Failed to initialize PyAudio: %s", exc)
                return
        pa = self._recording_pa

        def _try_open(device_index):
            for rate, ch in RECORDING_SAMPLE_CONFIGS:
                try:
                    s = pa.open(
                        rate=rate, channels=ch, format=pyaudio.paInt16,
                        input=True, input_device_index=device_index,
                        frames_per_buffer=4096, stream_callback=_callback,
                    )
                    s.start_stream()
                    return s, rate, ch
                except Exception:
                    continue
            return None, None, None

        configured_name = getattr(self.main_window, "effective_input_device_name", "") or ""

        # Everything up to here is cheap. find_input_device_index() and
        # pa.open() are not: both talk to the audio driver and can block for
        # seconds, and they used to run right here on the wx thread — the
        # window (and the screen reader reading it) froze for the duration.
        self._recording_starting = True
        self._recording_open_token += 1
        my_token = self._recording_open_token

        def _bg_open_stream():
            # An exception escaping this function would die unseen in a daemon
            # thread and take the wx.CallAfter with it, leaving
            # _recording_starting stuck True — and both entry points
            # (_on_record_voice_button, _on_ctrl_r_shortcut) refuse to start
            # while it is, so the record control would go dead for the rest of
            # the session. _on_stream_opened() is the only thing that clears
            # the flag, so it is scheduled from a finally and runs either way.
            stream = rate = ch = None
            try:
                input_device_index = (
                    find_input_device_index(configured_name, pa) if configured_name else None
                )
                stream, rate, ch = _try_open(input_device_index)
                if stream is None and input_device_index is not None:
                    stream, rate, ch = _try_open(None)

                if stream is None:
                    # Same last resort as ConversationsPanel, and kept
                    # deliberately identical to it: _try_open(None) only
                    # covers the default host API's default device, so a
                    # microphone that refuses MME but answers on WASAPI is
                    # still reachable by index. Posting a voice status and
                    # sending a voice message have no reason to disagree
                    # about which microphones exist — this panel already
                    # drifted behind the other one once.
                    for idx in fallback_input_device_indices(pa, exclude=(input_device_index,)):
                        stream, rate, ch = _try_open(idx)
                        if stream is not None:
                            logging.info(
                                "[status audio] Default input device failed; recording via "
                                "enumerated device index %s instead.", idx,
                            )
                            break
            except Exception:
                logging.exception(
                    "[status audio] Failed to open the recording stream (device=%r).",
                    configured_name,
                )
            finally:
                wx.CallAfter(_on_stream_opened, stream, rate, ch)

        def _on_stream_opened(stream, rate, ch):
            # Discard the result if the panel was closed or the recording
            # discarded while the stream was still opening — otherwise a
            # stream nobody asked for any more starts capturing in silence.
            if my_token != self._recording_open_token:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                return

            self._recording_starting = False

            if stream is None:
                # voice_recording_unavailable means "PyAudio isn't installed"
                # (see the top of _start_voice_recording) — reused here it
                # pointed at the wrong cause entirely, since PyAudio is
                # plainly present if we got as far as trying to open a
                # stream. The device-specific message tells the user the one
                # thing that is actionable: check the mic and its Windows
                # permission.
                logging.warning(
                    "[status audio] No input stream could be opened — recording not started."
                )
                wx.MessageBox(
                    self.main_window.i18n.t("voice_recording_device_failed"),
                    self.main_window.app_name,
                    wx.OK | wx.ICON_WARNING, self,
                )
                return

            self._recording_stream   = stream
            self._recording_rate     = rate
            self._recording_channels = ch
            self._is_recording       = True

            if hasattr(self.main_window, "voicemsg_startrecording_sound"):
                self.main_window.voicemsg_startrecording_sound.play()

            i18n = self.main_window.i18n
            self._voice_status_lbl.SetLabel(i18n.t("recording_in_progress"))
            self._voice_close_btn.SetLabel(i18n.t("discard_voice_message"))
            self._voice_close_btn.Show()
            if self._voice_recording_focus_suppression_enabled():
                cloak_panel_focus_fallback(
                    self._voice_post_panel, self._voice_start_btn
                )
            self._voice_start_btn.Hide()
            self._voice_pause_btn.SetLabel(i18n.t("pause_recording"))
            self._voice_pause_btn.Show()
            self._voice_send_btn.SetLabel(i18n.t("send_voice_message"))
            self._voice_send_btn.Show()
            self.Layout()
            self._focus_recording_button_silently(self._voice_send_btn)

        threading.Thread(target=_bg_open_stream, daemon=True).start()

    def _voice_recording_silence_enabled(self):
        """Whether all WinZapp spoken content is muted during recording."""
        settings = getattr(self.main_window, "settings", None) or {}
        return bool(
            settings.get("speech_content", {}).get("silence_while_recording", False)
        )

    def _voice_recording_focus_suppression_enabled(self):
        """Whether WinZapp's automatic recording-button focus stays silent.

        The dedicated silence setting always enables this. Disabling extended
        screen-reader compatibility also suppresses only this native focus
        announcement, without muting unrelated screen-reader speech.
        """
        settings = getattr(self.main_window, "settings", None) or {}
        silence_recording = settings.get("speech_content", {}).get(
            "silence_while_recording", False
        )
        extended_enabled = settings.get("accessibility", {}).get(
            "extended_sr_compat_enabled", True
        )
        return bool(silence_recording or not extended_enabled)

    def _focus_recording_button_silently(self, button):
        """Apply recording focus without creating a suppressed focus event.

        See ConversationsPanel._focus_recording_button_silently: when silence
        is requested, the reliable cross-API solution is not to move focus to
        Send at all.  The status recording shortcuts remain available.
        """
        if self._voice_recording_focus_suppression_enabled():
            return False
        button.SetFocus()
        return True

    def _silence_send_voice_focus_if_enabled(self):
        """Cancel delayed speech from non-focus recording state changes."""
        if not self._voice_recording_focus_suppression_enabled():
            return
        speak_output = getattr(self.main_window, "speak_output", None)
        silence_focus = getattr(speak_output, "silence_screen_reader_focus", None)
        if not callable(silence_focus):
            return
        silence_all = (
            getattr(speak_output, "silence", None)
            if self._voice_recording_silence_enabled()
            else None
        )

        def _silence_now():
            silence_focus()
            if callable(silence_all):
                silence_all()

        _silence_now()
        wx.CallAfter(_silence_now)
        for delay_ms in (40, 90, 160, 260, 400):
            wx.CallLater(delay_ms, _silence_now)

    def _toggle_pause_voice_recording(self, event):
        if not self._is_recording:
            return
        self._recording_paused = not self._recording_paused
        if hasattr(self.main_window, "voicemsg_pauserecording_sound"):
            try:
                self.main_window.voicemsg_pauserecording_sound.play()
            except Exception:
                pass
        i18n = self.main_window.i18n
        if self._recording_paused:
            self._voice_pause_btn.SetLabel(i18n.t("resume_recording"))
            self._voice_status_lbl.SetLabel(i18n.t("recording_paused"))
            self._voice_play_btn.Show()
        else:
            self._stop_recorded_audio_preview()
            self._voice_play_btn.Hide()
            self._voice_pause_btn.SetLabel(i18n.t("pause_recording"))
            self._voice_status_lbl.SetLabel(i18n.t("recording_in_progress"))
        self.Layout()
        self._silence_send_voice_focus_if_enabled()

    def _toggle_play_recorded_audio(self, event):
        """Play or stop the stable snapshot captured before the pause."""
        if not self._is_recording or not self._recording_paused:
            return
        if self._recorded_audio_sound is not None:
            self._stop_recorded_audio_preview()
            return
        if not self._recording_frames:
            return

        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tmp.close()
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(self._recording_channels)
                wf.setsampwidth(2)  # capture is always 16-bit PCM
                wf.setframerate(self._recording_rate)
                wf.writeframes(b"".join(self._recording_frames))
            self._recorded_audio_temp_path = tmp.name
            sound = sl_stream.FileStream(file=tmp.name)
            sound.play()
        except Exception as exc:
            logging.warning("[status audio] Failed to preview recording: %s", exc)
            self._cleanup_recorded_audio_temp_file()
            return

        self._recorded_audio_sound = sound
        self._voice_play_btn.SetLabel(
            self.main_window.i18n.t("stop_recorded_audio_playback")
        )
        self._recorded_audio_timer.Start(300)

    def _on_recorded_audio_timer(self, event):
        if (
            self._recorded_audio_sound is None
            or not self._recorded_audio_sound.is_playing
        ):
            self._stop_recorded_audio_preview()

    def _stop_recorded_audio_preview(self):
        self._recorded_audio_timer.Stop()
        if self._recorded_audio_sound is not None:
            try:
                self._recorded_audio_sound.stop()
            except Exception:
                pass
            self._recorded_audio_sound = None
        self._cleanup_recorded_audio_temp_file()
        if hasattr(self, "_voice_play_btn"):
            self._voice_play_btn.SetLabel(
                self.main_window.i18n.t("play_recorded_audio")
            )

    def _cleanup_recorded_audio_temp_file(self):
        if self._recorded_audio_temp_path is not None:
            try:
                os.unlink(self._recorded_audio_temp_path)
            except Exception:
                pass
            self._recorded_audio_temp_path = None

    def _stop_recording_stream(self):
        if self._recording_stream is not None:
            try:
                self._recording_stream.stop_stream()
                self._recording_stream.close()
            except Exception:
                pass
            self._recording_stream = None

    def _on_close_voice_panel(self, event):
        # Bump the token so a stream still opening on a background thread (see
        # _start_voice_recording) is closed and discarded when it arrives,
        # instead of starting to capture into a panel the user just dismissed.
        self._recording_open_token += 1
        self._recording_starting = False
        if self._is_recording and hasattr(self.main_window, "voicemsg_discard_sound"):
            try:
                self.main_window.voicemsg_discard_sound.play()
            except Exception:
                pass
        self._stop_recorded_audio_preview()
        self._stop_recording_stream()
        self._recording_frames = []
        self._is_recording = False
        self._recording_paused = False
        self._leave_status_composer()

    def _on_send_voice_status(self, event):
        if not self._is_recording:
            return
        if hasattr(self.main_window, "voicemsg_send_sound"):
            try:
                self.main_window.voicemsg_send_sound.play()
            except Exception:
                pass
        self._stop_recorded_audio_preview()
        self._stop_recording_stream()
        self._is_recording = False
        self._recording_paused = False
        self._leave_status_composer()

        if not self._recording_frames:
            return

        pcm_data = b"".join(self._recording_frames)
        self._recording_frames = []

        fd, temp_wav = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with wave.open(temp_wav, "wb") as wf:
                wf.setnchannels(self._recording_channels)
                wf.setsampwidth(self._recording_pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(self._recording_rate)
                wf.writeframes(pcm_data)
        except Exception as exc:
            logging.error("[status audio] Failed to write recorded WAV: %s", exc)
            try:
                os.unlink(temp_wav)
            except Exception:
                pass
            return

        threading.Thread(
            target=self._send_status_voice_bg,
            args=(temp_wav,),
            kwargs={"is_temp_file": True},
            daemon=True,
        ).start()

    def _send_status_voice_bg(self, path: str, is_temp_file: bool = False, report_result: bool = True):
        """Background: convert *path* to OGG/Opus (WhatsApp's own voice-
        message codec — main_window._convert_wav_to_ogg() despite the name
        just runs it through ffmpeg, which reads the real container/codec
        rather than trusting the extension, so this also works for a
        picked .mp3/.m4a/.aac file from _on_choose_media_status(), not just
        a WAV recorded here) and post it as a voice status via
        /send-status-voice-base64 (see messageController.ts's
        sendStatusVoice64() — mirrors send_audio_message()'s own
        send-voice-base64 call in main.py).

        *is_temp_file* must only be True for a file WE created (the
        recorded WAV) — deleting *path* unconditionally used to also
        delete the user's own picked file (e.g. an .mp3 chosen from the
        media picker) right out from under them.

        *report_result* controls whether a failure pops its own MessageBox
        here. _send_all_media_statuses_bg() passes False and aggregates
        instead — one popup per file used to stack into a flood of blocking
        dialogs when several files in a batch failed at once (same failure
        mode already fixed for save_data(), see main.py's
        _SAVE_ERROR_DIALOG_COOLDOWN comment).

        True when posted, False when it failed, STATUS_POST_UNCONFIRMED when
        it was sent and no answer came in time (status_upload_timeout() of
        its size): it may be up, so it is never reported as failed, which
        invited posting it twice — as the image/video path does.
        """
        mw = self.main_window
        ogg_path = mw._convert_wav_to_ogg(path)
        if is_temp_file:
            try:
                os.unlink(path)
            except Exception:
                pass
        if not ogg_path or not os.path.isfile(ogg_path):
            logging.error("[status audio] Failed to convert %s to OGG/Opus", path)
            if report_result:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("audio_convert_failed"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
            return False
        try:
            with open(ogg_path, "rb") as fh:
                audio = fh.read()
            audio_b64 = base64.b64encode(audio).decode("utf-8")
        except Exception as exc:
            # try/finally with no except let this propagate. Harmless while
            # this method was a thread target on its own, but
            # _send_all_media_statuses_bg() now calls it inside a loop: the
            # exception tore out of the loop, so the files after this one were
            # never even attempted AND the aggregate failure dialog at the end
            # of that loop was never reached — the batch just stopped, in
            # total silence, on a background thread. Report it like the
            # image/video path already does (_send_media_status_bg) and let
            # the batch carry on.
            logging.error("[status audio] Failed to read/encode %s: %s", ogg_path, exc)
            if report_result:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
            return False
        finally:
            try:
                os.unlink(ogg_path)
            except Exception:
                pass

        url = f"{mw.wpp_server}:{mw.wpp_port}/api/{mw.token}/send-status-voice-base64"
        headers = {"Authorization": f"Bearer {mw.token}", "Content-Type": "application/json"}
        payload = {"base64Ptt": f"data:audio/ogg;codecs=opus;base64,{audio_b64}"}
        try:
            resp = api_post(url, json=payload, headers=headers,
                            timeout=status_upload_timeout(len(audio)))
            ok   = resp.status_code in (200, 201)
            err_msg = "" if ok else f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.Timeout as exc:
            if not isinstance(exc, requests.exceptions.ConnectTimeout):
                logging.warning("[status audio] send-status-voice-base64 unconfirmed: timed out")
                if report_result:
                    # It may be up already: look before posting again.
                    wx.CallAfter(
                        wx.MessageBox,
                        mw.i18n.t("status_post_unconfirmed"),
                        mw.app_name,
                        wx.OK | wx.ICON_WARNING,
                    )
                return STATUS_POST_UNCONFIRMED
            ok = False
            err_msg = type(exc).__name__
        except Exception as exc:
            ok = False
            err_msg = str(exc)

        if ok:
            wx.CallAfter(self._on_status_sent)
        else:
            logging.error("[status audio] send-status-voice-base64 failed: %s", err_msg)
            if report_result:
                wx.CallAfter(
                    wx.MessageBox,
                    mw.i18n.t("status_error"),
                    mw.app_name,
                    wx.OK | wx.ICON_ERROR,
                )
        return ok
