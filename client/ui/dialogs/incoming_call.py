"""Accessible modeless dialog for an incoming WhatsApp call."""

import ctypes
import sys
from ctypes import wintypes

import wx


class IncomingCallDialog(wx.Dialog):
    """Show caller information and expose accessible Answer, Decline and Close buttons.

    The dialog is deliberately modeless. WhatsApp can send an ended/answered
    event while it is visible, and the main wx event loop must remain free to
    process that event and close this window automatically.
    """

    def __init__(self, parent, message: str, on_accept, on_reject, on_closed):
        i18n = parent.i18n
        super().__init__(
            parent,
            title=i18n.t("incoming_call_popup_title"),
            # This behaviour is explicitly user-controlled in Settings. When
            # enabled, the alert must surface over the application currently
            # in use so a screen-reader user never has to hunt for it via Alt+Tab.
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )
        self._on_accept_callback = on_accept
        self._on_reject_callback = on_reject
        self._on_closed_callback = on_closed
        self._closing = False

        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)

        self._message = wx.StaticText(panel, label=message)
        self._message.SetName(message)
        content.Add(self._message, 0, wx.EXPAND | wx.ALL, 12)

        buttons_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._accept_button = wx.Button(
            panel, wx.ID_OK, label=i18n.t("incoming_call_accept_button")
        )
        self._reject_button = wx.Button(
            panel, wx.ID_CANCEL, label=i18n.t("incoming_call_reject_button")
        )
        self._close_button = wx.Button(
            panel, wx.ID_CLOSE, label=i18n.t("incoming_call_close_button")
        )

        buttons_sizer.Add(self._accept_button, 0, wx.ALL, 6)
        buttons_sizer.Add(self._reject_button, 0, wx.ALL, 6)
        buttons_sizer.Add(self._close_button, 0, wx.ALL, 6)

        content.Add(buttons_sizer, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(content)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.SetMinSize((400, -1))
        self.CentreOnParent()

        self._accept_button.SetDefault()
        self._accept_button.Bind(wx.EVT_BUTTON, self._on_accept)
        self._reject_button.Bind(wx.EVT_BUTTON, self._on_reject)
        self._close_button.Bind(wx.EVT_BUTTON, self._on_close)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def show_accessibly(self):
        """Display over the current app and focus the answer button."""
        self.Show()
        self._force_foreground()
        # Windows can finish activating the previously focused application
        # after Show() returns. Repeat once after that race has settled.
        self._foreground_retry = wx.CallLater(150, self._force_foreground)

    def _force_foreground(self):
        """Use Win32 focus attachment when ordinary Raise() is insufficient."""
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
                    # HWND_TOPMOST plus SHOWWINDOW makes the user-selected
                    # popup visible even over a full-screen foreground app.
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
            self._accept_button.SetFocus()
        except Exception:
            # STAY_ON_TOP and Raise remain the portable fallback.
            try:
                self.Raise()
                self._accept_button.SetFocus()
            except Exception:
                pass

    def close_from_call_lifecycle(self):
        """Close without reporting a user dismissal back to the owner."""
        if self._closing:
            return
        self._closing = True
        self.Destroy()

    def _on_accept(self, _event):
        if self._closing:
            return
        self._closing = True
        if self._on_accept_callback:
            self._on_accept_callback()
        self.Destroy()

    def _on_reject(self, _event):
        if self._closing:
            return
        self._closing = True
        if self._on_reject_callback:
            self._on_reject_callback()
        self.Destroy()

    def _on_close(self, _event):
        if self._closing:
            return
        self._closing = True
        if self._on_closed_callback:
            self._on_closed_callback()
        self.Destroy()
