"""
api_version_check.py — WinZapp Evolution API version check dialog.

Shown when the installed Evolution API version is below the minimum
required by this build of WinZapp.  The user can choose to:

  RESULT_UPDATE   — update automatically (re-download + reinstall)
  RESULT_EXIT     — close WinZapp
  RESULT_CONTINUE — proceed with the outdated version (not recommended)
"""

import wx

# ── Modal-result constants ────────────────────────────────────────────────────
RESULT_UPDATE   = 1   # User chose to update now
RESULT_EXIT     = 2   # User chose to exit
RESULT_CONTINUE = 3   # User chose to continue with the current version


class ApiVersionOutdatedDialog(wx.Dialog):
    """
    Dialog shown when the installed Evolution API is below the required minimum.

    Parameters
    ----------
    parent           : wx.Window
    i18n             : I18n  (already initialised by main.py)
    current_version  : str   e.g. "2.3.7"
    required_version : str   e.g. "2.4.0-rc2"
    """

    def __init__(self, parent, i18n, current_version: str, required_version: str):
        title = i18n.t("api_update_outdated_title")
        # Disable the close-box — the user must pick one of the three options
        style = wx.DEFAULT_DIALOG_STYLE & ~wx.CLOSE_BOX
        super().__init__(parent, title=title, style=style)

        self._i18n = i18n
        self._build_ui(current_version, required_version)
        self.Bind(wx.EVT_CLOSE, self._on_close_attempt)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self, current_version: str, required_version: str):
        msg = self._i18n.t("api_update_outdated_message").format(
            current=current_version,
            required=required_version,
        )

        msg_ctrl = wx.StaticText(self, label=msg)
        msg_ctrl.Wrap(480)

        update_btn   = wx.Button(self, wx.ID_ANY, self._i18n.t("api_update_now"))
        exit_btn     = wx.Button(self, wx.ID_ANY, self._i18n.t("api_update_exit"))
        continue_btn = wx.Button(self, wx.ID_ANY, self._i18n.t("api_update_continue"))

        update_btn.Bind(wx.EVT_BUTTON,   lambda _e: self.EndModal(RESULT_UPDATE))
        exit_btn.Bind(wx.EVT_BUTTON,     lambda _e: self.EndModal(RESULT_EXIT))
        continue_btn.Bind(wx.EVT_BUTTON, lambda _e: self.EndModal(RESULT_CONTINUE))

        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        btn_sizer.Add(update_btn,   0, wx.ALL, 5)
        btn_sizer.Add(exit_btn,     0, wx.ALL, 5)
        btn_sizer.Add(continue_btn, 0, wx.ALL, 5)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(msg_ctrl,  0, wx.ALL | wx.EXPAND, 15)
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.BOTTOM, 12)

        self.SetSizer(sizer)
        sizer.Fit(self)
        self.SetMinSize((520, -1))
        self.Centre()

    # ── Alt-F4 / OS close → treated as "Exit" ────────────────────────────────

    def _on_close_attempt(self, _event):
        self.EndModal(RESULT_EXIT)
