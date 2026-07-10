"""
api_startup.py — WinZapp Evolution API startup dialog.

Displayed while the bundled Node / Evolution API process is starting.
A background thread polls the configured port every 500 ms for up to
2 minutes.  The dialog has no Cancel button — starting the API is
mandatory — but it closes itself automatically once the port is open
(or after the timeout).

Modal result:
  wx.ID_OK     — port opened; caller may proceed normally
  wx.ID_CANCEL — 2-minute timeout elapsed; caller shows log and warns
"""

import socket
import threading
import time

import wx


class ApiStartupDialog(wx.Dialog):
    """Indeterminate-progress dialog shown while Evolution API starts."""

    _PULSE_MS        = 80     # gauge pulse interval
    _POLL_INTERVAL_S = 0.5    # how often to probe the port
    _TIMEOUT_S       = 120    # 2 minutes

    def __init__(self, parent, port):
        from core.i18n import I18n
        self._i18n = I18n(parent)
        self._i18n.get_language()

        self._port = port
        self._done = False

        title = self._i18n.t("api_startup_title")
        # Remove close box; EVT_CLOSE is also swallowed below
        style = wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX
        super().__init__(parent, title=title, style=style)

        self._build_ui()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_pulse, self._timer)
        self.Bind(wx.EVT_CLOSE, self._on_close_attempt)

        t = threading.Thread(target=self._poll_thread, daemon=True)
        t.start()

        self._timer.Start(self._PULSE_MS)

    # ── UI construction ────────────────────────────────────────────────────

    def _build_ui(self):
        # Pulsing gauge (indeterminate)
        self._gauge = wx.Gauge(self, range=100,
                               style=wx.GA_HORIZONTAL | wx.GA_SMOOTH)

        cancel_btn = wx.Button(self, wx.ID_CANCEL,
                               label=self._i18n.t("cancel"))
        cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._gauge, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(cancel_btn,  0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize((380, -1))
        self.Centre()

    # ── Timer ──────────────────────────────────────────────────────────────

    def _on_pulse(self, _event):
        if self:
            self._gauge.Pulse()

    # ── Cancel ────────────────────────────────────────────────────────────

    def _on_cancel(self, _event):
        """User clicked Cancel — stop polling and close with CANCEL."""
        self._done = True
        if self:
            self._timer.Stop()
            self.EndModal(wx.ID_CANCEL)

    # ── Prevent accidental close (Alt-F4) ─────────────────────────────────

    def _on_close_attempt(self, _event):
        """Alt-F4 is treated the same as Cancel."""
        self._on_cancel(_event)

    # ── Background polling thread ──────────────────────────────────────────

    def _poll_thread(self):
        deadline = time.time() + self._TIMEOUT_S
        while time.time() < deadline:
            if self._done:
                return
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=1):
                    if self:
                        wx.CallAfter(self._finish_success)
                    return
            except OSError:
                time.sleep(self._POLL_INTERVAL_S)
        if self:
            wx.CallAfter(self._finish_timeout)

    # ── Completion callbacks (called on main thread via wx.CallAfter) ──────

    def _finish_success(self):
        if not self or self._done:
            return
        if not self.IsModal():
            wx.CallLater(50, self._finish_success)
            return
        self._done = True
        self._timer.Stop()
        try:
            self.EndModal(wx.ID_OK)
        except Exception:
            self._done = False
            if self:
                self._timer.Start(self._PULSE_MS)
                wx.CallLater(50, self._finish_success)

    def _finish_timeout(self):
        if not self or self._done:
            return
        if not self.IsModal():
            wx.CallLater(50, self._finish_timeout)
            return
        self._done = True
        self._timer.Stop()
        try:
            self.EndModal(wx.ID_CANCEL)
        except Exception:
            self._done = False
            if self:
                self._timer.Start(self._PULSE_MS)
                wx.CallLater(50, self._finish_timeout)
