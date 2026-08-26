"""Accessible modeless dialog for an active WhatsApp call."""

import ctypes
import logging
import sys
from ctypes import wintypes

import wx

from ui.dialogs.call_audio_settings import CallAudioSettingsDialog


class ActiveCallDialog(wx.Dialog):
    """Show active call information with duration timer, mute toggle, audio settings and end call action."""

    def __init__(self, parent, call_id: str, caller_name: str, on_end, on_toggle_mute=None):
        self.main_window = parent if hasattr(parent, "i18n") else parent.GetParent()
        self.i18n = self.main_window.i18n
        self.call_id = call_id
        self.caller_name = caller_name or self.i18n.t("unknown_contact")
        self._on_end_callback = on_end
        self._on_toggle_mute_callback = on_toggle_mute
        self._closing = False
        self._is_muted = False
        self._seconds_elapsed = 0

        title = self.i18n.t("active_call_title").format(name=self.caller_name)
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )

        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)

        self._caller_text = wx.StaticText(panel, label=self.caller_name)
        self._caller_text.SetName(self.caller_name)
        font = self._caller_text.GetFont()
        font.MakeBold()
        self._caller_text.SetFont(font)
        content.Add(self._caller_text, 0, wx.EXPAND | wx.ALL, 10)

        initial_duration = self._format_duration(0)
        self._status_text = wx.StaticText(
            panel,
            label=self.i18n.t("active_call_status_connected").format(duration=initial_duration)
        )
        self._status_text.SetName(self._status_text.GetLabel())
        content.Add(self._status_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)

        self._mute_button = wx.Button(
            panel,
            label=self.i18n.t("active_call_mute_mic")
        )
        self._audio_settings_button = wx.Button(
            panel,
            label=self.i18n.t("active_call_audio_settings_btn")
        )
        self._end_button = wx.Button(
            panel,
            wx.ID_CANCEL,
            label=self.i18n.t("active_call_end_button")
        )

        buttons_sizer.Add(self._mute_button, 0, wx.ALL, 6)
        buttons_sizer.Add(self._audio_settings_button, 0, wx.ALL, 6)
        buttons_sizer.Add(self._end_button, 0, wx.ALL, 6)

        content.Add(buttons_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        panel.SetSizer(content)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.SetMinSize((420, -1))
        self.CentreOnParent()

        self._mute_button.Bind(wx.EVT_BUTTON, self._on_toggle_mute)
        self._audio_settings_button.Bind(wx.EVT_BUTTON, self._on_open_audio_settings)
        self._end_button.Bind(wx.EVT_BUTTON, self._on_end)
        self.Bind(wx.EVT_CLOSE, self._on_end)

        # Timer for call duration
        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self._timer.Start(1000)

    def _format_duration(self, seconds: int) -> str:
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    def _on_tick(self, _event):
        if self._closing:
            return
        self._seconds_elapsed += 1
        formatted = self._format_duration(self._seconds_elapsed)
        status_label = self.i18n.t("active_call_status_connected").format(duration=formatted)
        if self._is_muted:
            status_label += f" ({self.i18n.t('active_call_status_muted')})"
        self._status_text.SetLabel(status_label)
        self._status_text.SetName(status_label)

    def _on_toggle_mute(self, _event):
        self._is_muted = not self._is_muted
        if self._is_muted:
            self._mute_button.SetLabel(self.i18n.t("active_call_unmute_mic"))
        else:
            self._mute_button.SetLabel(self.i18n.t("active_call_mute_mic"))

        if self._on_toggle_mute_callback:
            try:
                self._on_toggle_mute_callback(self._is_muted)
            except Exception:
                logging.exception("[call] error calling toggle_mute callback")

        formatted = self._format_duration(self._seconds_elapsed)
        status_label = self.i18n.t("active_call_status_connected").format(duration=formatted)
        if self._is_muted:
            status_label += f" ({self.i18n.t('active_call_status_muted')})"
        self._status_text.SetLabel(status_label)
        self._status_text.SetName(status_label)

    def _on_open_audio_settings(self, _event):
        dlg = CallAudioSettingsDialog(self)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()

    def show_accessibly(self):
        """Display over the current app and focus the end call button."""
        self.Show()
        self._force_foreground()
        self._foreground_retry = wx.CallLater(150, self._force_foreground)

    def _force_foreground(self):
        try:
            self.Raise()
            if sys.platform == "win32":
                user32 = ctypes.windll.user32
                user32.GetForegroundWindow.restype = wintypes.HWND
                user32.GetWindowThreadProcessId.argtypes = [
                    wintypes.HWND, ctypes.POINTER(wintypes.DWORD)
                ]
                user32.GetWindowThreadProcessId.restype = wintypes.DWORD
                user32.AttachThreadInput.argtypes = [
                    wintypes.DWORD, wintypes.DWORD, wintypes.BOOL
                ]
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND,
                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                    wintypes.UINT,
                ]
                user32.BringWindowToTop.argtypes = [wintypes.HWND]
                user32.SetForegroundWindow.argtypes = [wintypes.HWND]
                hwnd = wintypes.HWND(int(self.GetHandle()))
                foreground = user32.GetForegroundWindow()
                current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
                foreground_thread = (
                    user32.GetWindowThreadProcessId(foreground, None)
                    if foreground else 0
                )
                attached = bool(
                    foreground_thread
                    and foreground_thread != current_thread
                    and user32.AttachThreadInput(
                        current_thread, foreground_thread, True
                    )
                )
                try:
                    user32.SetWindowPos(
                        hwnd, wintypes.HWND(-1), 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0040,
                    )
                    user32.BringWindowToTop(hwnd)
                    user32.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        user32.AttachThreadInput(
                            current_thread, foreground_thread, False
                        )
            self._end_button.SetFocus()
        except Exception:
            try:
                self.Raise()
                self._end_button.SetFocus()
            except Exception:
                pass

    def close_from_call_lifecycle(self):
        """Close without reporting a user hangup back to the owner."""
        if self._closing:
            return
        self._closing = True
        if hasattr(self, "_timer") and self._timer.IsRunning():
            self._timer.Stop()
        self.Destroy()

    def _on_end(self, _event):
        if self._closing:
            return
        self._closing = True
        if hasattr(self, "_timer") and self._timer.IsRunning():
            self._timer.Stop()
        if self._on_end_callback:
            self._on_end_callback()
        self.Destroy()
