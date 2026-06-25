import sys
import wx
import logging


def _vk_mod_to_str(vk: int, mod: int) -> str:
    parts = []
    if mod & 0x0002: parts.append("Ctrl")
    if mod & 0x0001: parts.append("Alt")
    if mod & 0x0004: parts.append("Shift")
    if vk == 0x30:
        parts.append("0")
    elif 0x41 <= vk <= 0x5A:
        parts.append(chr(vk))
    else:
        parts.append(f"VK_{vk}")
    return "+".join(parts)


class FirstRunWizard:
    """First-run dialogs: language selection, autostart, global hotkey,
    terms-of-service acceptance, and quick tip — each shown exactly once."""

    def __init__(self, mw):
        self.mw = mw

    # ── Language selection ────────────────────────────────────────────────

    def ensure_language_selected(self):
        lang_already_set = bool(
            self.mw.settings.get("general", {}).get("language")
        )
        if lang_already_set:
            return

        from ui.dialogs.language_dialog import LanguageSelectionDialog
        dlg    = LanguageSelectionDialog(parent=None)
        result = dlg.ShowModal()
        lang   = dlg.selected_language
        dlg.Destroy()

        if result != wx.ID_OK:
            sys.exit(0)

        self.mw.settings.setdefault("general", {})["language"] = lang
        self.mw.save_settings()

    # ── First-run / autostart ─────────────────────────────────────────────

    def check_first_run(self):
        if not self.mw.settings.get("general", {}).get("first_run", True):
            return
        self.mw.settings.setdefault("general", {})["first_run"] = False
        self.mw.save_settings()

        result = wx.MessageBox(
            self.mw.i18n.t("autostart_ask_message"),
            self.mw.i18n.t("autostart_ask_title"),
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if result == wx.YES:
            self.apply_autostart(enable=True)
        else:
            self.mw.settings.setdefault("general", {})["autostart"] = False
            self.mw.save_settings()

    def check_hotkey_first_run(self):
        gen = self.mw.settings.get("general", {})
        if gen.get("hotkey_first_run_asked", False):
            return
        if gen.get("global_hotkey"):
            self.mw.settings.setdefault("general", {})["hotkey_first_run_asked"] = True
            self.mw.save_settings()
            return

        self.mw.settings.setdefault("general", {})["hotkey_first_run_asked"] = True
        self.mw.save_settings()

        from ui.dialogs.settings_dialog import _HotkeyCapture

        dlg = wx.Dialog(
            None,
            title=self.mw.i18n.t("hotkey_first_run_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        msg_ctrl = wx.StaticText(dlg, label=self.mw.i18n.t("hotkey_first_run_message"))
        msg_ctrl.Wrap(480)
        sizer.Add(msg_ctrl, 0, wx.ALL, 15)

        capture = _HotkeyCapture(
            dlg,
            accessible_name=self.mw.i18n.t("global_hotkey_label"),
        )
        capture.SetHint(self.mw.i18n.t("global_hotkey_hint"))
        sizer.Add(capture, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 15)

        btn_sizer = wx.StdDialogButtonSizer()
        ok_btn   = wx.Button(dlg, wx.ID_OK,     self.mw.i18n.t("ok"))
        skip_btn = wx.Button(dlg, wx.ID_CANCEL, self.mw.i18n.t("hotkey_first_run_skip"))
        btn_sizer.AddButton(ok_btn)
        btn_sizer.AddButton(skip_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(sizer)
        sizer.Fit(dlg)
        dlg.CenterOnScreen()

        result = dlg.ShowModal()
        vk  = capture._vk
        mod = capture._mod
        dlg.Destroy()

        if result == wx.ID_OK and vk:
            self.mw.settings.setdefault("general", {})["global_hotkey"] = {"vk": vk, "mod": mod}
            self.mw.save_settings()
            wx.MessageBox(
                self.mw.i18n.t("hotkey_first_run_success").format(
                    hotkey=_vk_mod_to_str(vk, mod)
                ),
                self.mw.i18n.t("autostart_success_title"),
                wx.OK | wx.ICON_INFORMATION,
            )

    def apply_autostart(self, enable: bool):
        from autostart import enable_autostart, disable_autostart
        if enable:
            try:
                enable_autostart()
                self.mw.settings.setdefault("general", {})["autostart"] = True
                self.mw.save_settings()
                wx.MessageBox(
                    self.mw.i18n.t("autostart_success_message"),
                    self.mw.i18n.t("autostart_success_title"),
                    wx.OK | wx.ICON_INFORMATION,
                )
            except Exception as exc:
                self.mw.settings.setdefault("general", {})["autostart"] = False
                self.mw.save_settings()
                wx.MessageBox(
                    f"{self.mw.i18n.t('autostart_error_message')}\n\n{exc}",
                    self.mw.i18n.t("error").format(app_name=self.mw.app_name),
                    wx.OK | wx.ICON_ERROR,
                )
        else:
            disable_autostart()
            self.mw.settings.setdefault("general", {})["autostart"] = False
            self.mw.save_settings()

    def sync_autostart_registry(self):
        if sys.platform != "win32":
            return

        if self.mw.settings.get("general", {}).get("first_run", True):
            return

        try:
            from autostart import is_autostart_enabled, enable_autostart, disable_autostart
            setting_enabled = self.mw.settings.get("general", {}).get("autostart", False)
            registry_enabled = is_autostart_enabled()

            if setting_enabled and not registry_enabled:
                logging.info("Startup: Autostart is enabled in settings but missing in registry. Enabling...")
                enable_autostart()
            elif not setting_enabled and registry_enabled:
                logging.info("Startup: Autostart is disabled in settings but present in registry. Disabling...")
                disable_autostart()
        except Exception as e:
            logging.error("Startup: Failed to sync autostart registry key: %s", e)

    # ── Quick tip ─────────────────────────────────────────────────────────

    def check_quick_tip(self):
        if self.mw.settings.get("general", {}).get("quick_tip_shown", False):
            return
        self.mw.settings.setdefault("general", {})["quick_tip_shown"] = True
        self.mw.save_settings()
        wx.MessageBox(
            self.mw.i18n.t("quick_tip_message"),
            self.mw.i18n.t("quick_tip_title"),
            wx.OK | wx.ICON_INFORMATION,
            self.mw,
        )

    # ── Terms of service ──────────────────────────────────────────────────

    def check_terms_acceptance(self):
        if self.mw.settings.get("general", {}).get("terms_alert_displayed", False):
            return

        dlg = wx.Dialog(
            None,
            title=self.mw.i18n.t("terms_title"),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)

        msg_ctrl = wx.StaticText(dlg, label=self.mw.i18n.t("terms_message"))
        msg_ctrl.Wrap(480)
        sizer.Add(msg_ctrl, 0, wx.ALL, 15)

        btn_sizer = wx.StdDialogButtonSizer()
        accept_btn  = wx.Button(dlg, wx.ID_OK,     self.mw.i18n.t("terms_accept"))
        decline_btn = wx.Button(dlg, wx.ID_CANCEL, self.mw.i18n.t("terms_decline"))
        btn_sizer.AddButton(accept_btn)
        btn_sizer.AddButton(decline_btn)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 10)

        dlg.SetSizer(sizer)
        sizer.Fit(dlg)
        dlg.CenterOnScreen()

        result = dlg.ShowModal()
        dlg.Destroy()

        if result == wx.ID_OK:
            self.mw.settings.setdefault("general", {})["terms_alert_displayed"] = True
            self.mw.save_settings()
        else:
            sys.exit(0)
