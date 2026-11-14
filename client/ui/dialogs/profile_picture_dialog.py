"""The "Profile picture" button of the chat and group data dialog.

`show_profile_picture()` fetches the picture off the UI thread and then either
opens `ProfilePictureDialog` or tells the user, in a message box, that the
picture is not available to them (none set, or hidden by the contact's privacy
settings — WhatsApp answers both the same way, so they cannot be told apart).
"""

import logging
import os
import subprocess
import sys
import threading

import wx

from app_paths import data_path
from core import profile_picture, tls_trust
from core.api_client import api_get

# The largest the picture is drawn inside the dialog; the external viewer is
# there for the full size.
_MAX_SHOWN = 480


def open_in_default_app(path: str) -> None:
    """Open `path` in the program Windows associates with its type."""
    if sys.platform == "win32":
        try:
            os.startfile(path)
        except OSError:
            # No program is set for this type: let Windows ask which one.
            os.startfile(path, "openas")
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_profile_picture(parent, main_window, jid: str, name: str, button=None) -> None:
    """Fetch `jid`'s picture in the background, then show it or say why not.

    A second press while the first download runs is ignored. The button is
    not disabled for it: disabling the focused control drops the keyboard
    focus, and the screen reader with it. `button` gets the focus back once
    the picture dialog closes.
    """
    i18n = main_window.i18n
    if getattr(parent, "_profile_picture_loading", False):
        return
    parent._profile_picture_loading = True
    main_window.speak_output.output(i18n.t("loading"))
    base_url = f"{main_window.wpp_server}:{main_window.wpp_port}"
    token = main_window.token
    query_jid = profile_picture.query_jid(
        jid, getattr(main_window, "_lid_to_phone", None))
    contacts = getattr(main_window, "contacts", None)
    # An @lid chat's contact entry may be keyed by its phone instead.
    fallback = (profile_picture.stored_picture_url(contacts, jid)
                or profile_picture.stored_picture_url(contacts, query_jid))

    def _work():
        path = ""
        try:
            data = profile_picture.fetch_profile_picture(
                base_url, token, query_jid, api_get, tls_trust.get, fallback
            )
            if data:
                path = profile_picture.save_picture(
                    data_path("profile_pictures"), jid, data
                )
        except Exception:
            logging.exception("[profile_picture] fetching the picture failed")
        wx.CallAfter(_done, path)

    def _done(path):
        # A destroyed wx window is falsy: the data dialog may have been
        # closed while the download ran, and then there is nobody to show to.
        if not parent:
            return
        parent._profile_picture_loading = False
        if not parent.IsShown():
            return
        if not path:
            wx.MessageBox(
                i18n.t("profile_picture_unavailable"),
                i18n.t("profile_picture_title"),
                wx.OK | wx.ICON_INFORMATION,
                parent,
            )
            return
        dlg = ProfilePictureDialog(parent, i18n, name, path)
        try:
            dlg.ShowModal()
        finally:
            dlg.Destroy()
        if button:
            button.SetFocus()

    threading.Thread(target=_work, daemon=True).start()


class ProfilePictureDialog(wx.Dialog):
    """Shows one saved profile picture, with a button to open it elsewhere."""

    def __init__(self, parent, i18n, name: str, path: str):
        self._i18n = i18n
        self._path = path
        super().__init__(
            parent, title=f"{name} | {i18n.t('profile_picture_title')}",
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # LogNull: a file wx cannot decode would otherwise pop up wx's own
        # error box before this dialog; IsOk() below already covers it.
        with wx.LogNull():
            image = wx.Image(path)
        if image.IsOk():
            w, h = image.GetWidth(), image.GetHeight()
            ratio = min(1.0, _MAX_SHOWN / max(w, h, 1))
            if ratio < 1.0:
                image = image.Scale(max(1, int(w * ratio)), max(1, int(h * ratio)),
                                    wx.IMAGE_QUALITY_HIGH)
            picture = wx.StaticBitmap(panel, bitmap=wx.Bitmap(image))
            picture.SetName(i18n.t("profile_picture_title"))
            sizer.Add(picture, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 8)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        self._open_btn = wx.Button(panel, label=i18n.t("profile_picture_open_external"))
        self._open_btn.Bind(wx.EVT_BUTTON, self._on_open_external)
        buttons.Add(self._open_btn, 0, wx.RIGHT, 8)
        close_btn = wx.Button(panel, wx.ID_CANCEL, label=i18n.t("close"))
        buttons.Add(close_btn, 0)
        sizer.Add(buttons, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 8)

        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)
        self.CentreOnParent()
        self._open_btn.SetFocus()

    def _on_open_external(self, event):
        try:
            open_in_default_app(self._path)
        except Exception:
            logging.exception("[profile_picture] opening in the external viewer failed")
            wx.MessageBox(
                self._i18n.t("profile_picture_open_failed"),
                self._i18n.t("profile_picture_title"),
                wx.OK | wx.ICON_ERROR,
                self,
            )
