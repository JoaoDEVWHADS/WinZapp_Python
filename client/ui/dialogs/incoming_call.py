"""Accessible modeless dialog for an incoming WhatsApp call."""

import ctypes
import sys
from ctypes import wintypes

import wx


class IncomingCallDialog(wx.Dialog):
    """Show caller information and expose a native local-stop button.

    The dialog is deliberately modeless.  WhatsApp can send an ended/answered
    event while it is visible, and the main wx event loop must remain free to
    process that event and close this window automatically.
    """

    def __init__(self, parent, message: str, on_stop, on_closed):
        i18n = parent.i18n
        super().__init__(
            parent,
            title=i18n.t("incoming_call_popup_title"),
            # This behaviour is explicitly user-controlled in Settings.  When
            # enabled, the alert must surface over the application currently
            # in use so a screen-reader user never has to hunt for it via Alt+Tab.
            style=wx.DEFAULT_DIALOG_STYLE | wx.STAY_ON_TOP,
        )
        self._on_stop_callback = on_stop
        self._on_closed_callback = on_closed
        self._closing = False

        panel = wx.Panel(self)
        content = wx.BoxSizer(wx.VERTICAL)

        self._message = wx.StaticText(panel, label=message)
        self._message.SetName(message)
        content.Add(self._message, 0, wx.EXPAND | wx.ALL, 12)

        buttons = wx.StdDialogButtonSizer()
        self._stop_button = wx.Button(
            panel, wx.ID_OK, label=i18n.t("incoming_call_stop_button")
        )
        self._close_button = wx.Button(
            panel, wx.ID_CANCEL, label=i18n.t("incoming_call_close_button")
        )
        buttons.AddButton(self._stop_button)
        buttons.AddButton(self._close_button)
        buttons.Realize()
        content.Add(buttons, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(content)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.SetMinSize((360, -1))
        self.CentreOnParent()

        self._stop_button.SetDefault()
        self._stop_button.Bind(wx.EVT_BUTTON, self._on_stop)
        self._close_button.Bind(wx.EVT_BUTTON, self._on_close)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def show_accessibly(self):
        """Display over the current app and focus the local-stop button."""
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
            self._stop_button.SetFocus()
        except Exception:
            # STAY_ON_TOP and Raise remain the portable fallback.
            try:
                self.Raise()
                self._stop_button.SetFocus()
            except Exception:
                pass

    def close_from_call_lifecycle(self):
        """Close without reporting a user dismissal back to the owner."""
        if self._closing:
            return
        self._closing = True
        self.Destroy()

    def _on_stop(self, _event):
        if self._closing:
            return
        self._closing = True
        self._on_stop_callback()
        self.Destroy()

    def _on_close(self, _event):
        if self._closing:
            return
        self._closing = True
        self._on_closed_callback()
        self.Destroy()
