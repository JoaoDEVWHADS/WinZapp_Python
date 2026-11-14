"""Mac window lifecycle: close hides, the Dock icon brings it back.

On Windows, closing WinZapp's window hides it to the tray (it keeps
receiving messages); without a tray icon it quits. The Mac has no tray, so
upstream's close would quit — the Mac convention (Messages, Mail) is that
closing the window keeps the app running and the Dock icon reopens it;
Command-Q quits.

restore_window()/hide_to_tray() drive the window through Win32 calls; these
are their Mac equivalents. restore_window() is also what WinZapp's IPC
"activate" (a second launch, account switch) and the notification "open"
action call.
"""

import logging

import wx

_frames = []


def restore_window(self):
    self._window_hidden = False
    self.background_mode = False
    if self.IsIconized():
        self.Iconize(False)
    if not self.IsShown():
        self.Show(True)
    self.Raise()
    try:
        from AppKit import NSApp
        NSApp().activateIgnoringOtherApps_(True)
    except Exception:
        pass
    if hasattr(self, "conversations_panel"):
        wx.CallAfter(self.add_chats_to_ui)
    wx.CallAfter(self._focus_primary_control)


def _hide(self):
    self.lock_chat_vault(silent=True, show_conversations=False)
    self.Hide()
    self._window_hidden = True


def on_close(self, event):
    if event.CanVeto():
        _hide(self)
        event.Veto()
    else:
        self.real_exit()


def hide_to_tray(self):
    _hide(self)


def leave_dock():
    """Quitting: take WinZapp out of the Dock and Command-Tab at once, so it
    is gone the moment the user quits, while upstream's shutdown (session
    flush, profile snapshot, Node stop) finishes out of sight."""
    def do():
        try:
            from AppKit import NSApp
            NSApp().setActivationPolicy_(2)   # NSApplicationActivationPolicyProhibited
        except Exception:
            pass
    if wx.IsMainThread():
        do()
    else:
        wx.CallAfter(do)


def install():
    from main_window import window_lifecycle as wl
    cls = wl.WindowLifecycleMixin
    cls.restore_window = restore_window
    cls._on_close = on_close
    cls.hide_to_tray = hide_to_tray

    orig_real_exit = cls.real_exit

    def real_exit(self, *a, **k):
        for win in wx.GetTopLevelWindows():
            try:
                win.Hide()
            except Exception:
                pass
        leave_dock()
        return orig_real_exit(self, *a, **k)

    cls.real_exit = real_exit

    def mac_reopen(app_self):
        for win in wx.GetTopLevelWindows():
            if hasattr(win, "restore_window") and hasattr(win, "conversations_panel"):
                try:
                    win.restore_window()
                except Exception:
                    logging.exception("[lifecycle_mac] reopen failed")
                return

    wx.App.MacReopenApp = mac_reopen
