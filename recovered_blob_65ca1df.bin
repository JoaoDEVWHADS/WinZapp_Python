import wx
from i18n import LANGUAGE_NAMES


class SettingsDialog(wx.Dialog):
    """Settings dialog with a General tab (language) and a Connection tab (port)."""

    def __init__(self, parent):
        self.main_window = parent
        i18n = self.main_window.i18n
        super().__init__(
            parent,
            title=i18n.t("settings_title"),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._lang_codes = list(LANGUAGE_NAMES.keys())
        self._build_ui()
        self._load_values()
        self.Fit()
        self.SetMinSize((360, -1))
        self.Centre()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        i18n = self.main_window.i18n

        self._notebook = wx.Notebook(self)

        # ── General tab ──────────────────────────────────────────────────────
        self._general_page = wx.Panel(self._notebook)
        gen_sizer = wx.BoxSizer(wx.VERTICAL)

        gen_sizer.Add(
            wx.StaticText(self._general_page, label=i18n.t("language_label")),
            0, wx.LEFT | wx.TOP | wx.RIGHT, 8,
        )
        self._lang_combo = wx.ComboBox(
            self._general_page,
            style=wx.CB_READONLY,
            choices=list(LANGUAGE_NAMES.values()),
        )
        gen_sizer.Add(self._lang_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._autostart_check = wx.CheckBox(
            self._general_page, label=i18n.t("autostart_label")
        )
        gen_sizer.Add(self._autostart_check, 0, wx.ALL, 8)
        self._general_page.SetSizer(gen_sizer)
        self._notebook.AddPage(self._general_page, i18n.t("tab_general"))

        # ── Connection tab ───────────────────────────────────────────────────
        self._conn_page = wx.Panel(self._notebook)
        conn_sizer = wx.BoxSizer(wx.VERTICAL)

        conn_sizer.Add(
            wx.StaticText(self._conn_page, label=i18n.t("evolution_port_label")),
            0, wx.LEFT | wx.TOP | wx.RIGHT, 8,
        )
        self._port_field = wx.TextCtrl(self._conn_page)
        conn_sizer.Add(self._port_field, 0, wx.EXPAND | wx.ALL, 8)
        self._conn_page.SetSizer(conn_sizer)
        self._notebook.AddPage(self._conn_page, i18n.t("tab_connection"))

        # ── Button row ───────────────────────────────────────────────────────
        btn_sizer = wx.StdDialogButtonSizer()
        self._ok_btn = wx.Button(self, wx.ID_OK)
        self._cancel_btn = wx.Button(self, wx.ID_CANCEL)
        self._apply_btn = wx.Button(self, wx.ID_APPLY, label=i18n.t("apply"))
        btn_sizer.AddButton(self._ok_btn)
        btn_sizer.AddButton(self._cancel_btn)
        btn_sizer.AddButton(self._apply_btn)
        btn_sizer.Realize()

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(self._notebook, 1, wx.EXPAND | wx.ALL, 5)
        main_sizer.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        self.SetSizer(main_sizer)

        self._ok_btn.Bind(wx.EVT_BUTTON, self._on_ok)
        self._cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        self._apply_btn.Bind(wx.EVT_BUTTON, self._on_apply)

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _load_values(self):
        """Populate controls from current settings."""
        lang_code = self.main_window.settings.get("general", {}).get("language", "pt-BR")
        if lang_code in self._lang_codes:
            self._lang_combo.SetSelection(self._lang_codes.index(lang_code))
        else:
            self._lang_combo.SetSelection(0)

        from autostart import is_autostart_enabled
        self._autostart_check.SetValue(is_autostart_enabled())

        self._port_field.SetValue(str(self.main_window.evolution_port))

    def _validate(self) -> bool:
        """Return True if the port value is valid; show an error and return False otherwise."""
        port_str = self._port_field.GetValue().strip()
        try:
            port = int(port_str)
            if not (1024 <= port <= 65535):
                raise ValueError
        except ValueError:
            wx.MessageBox(
                self.main_window.i18n.t("invalid_port"),
                self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._port_field.SetFocus()
            return False
        return True

    def _apply_values(self) -> bool:
        """Validate, save, and apply all settings. Returns True on success."""
        if not self._validate():
            return False

        # Language
        sel = self._lang_combo.GetSelection()
        new_lang = self._lang_codes[sel] if sel != wx.NOT_FOUND else "pt-BR"
        self.main_window.settings.setdefault("general", {})["language"] = new_lang

        # Port
        port = int(self._port_field.GetValue().strip())
        self.main_window.settings.setdefault("connection", {})["evolution_port"] = port
        self.main_window.evolution_port = port

        # Autostart
        from autostart import is_autostart_enabled
        new_autostart = self._autostart_check.GetValue()
        current_autostart = is_autostart_enabled()
        if new_autostart != current_autostart:
            # Delegate to main_window so the shared logic lives in one place.
            # _apply_autostart() saves settings and shows confirmation/error dialogs.
            self.main_window._apply_autostart(enable=new_autostart)
            # Resync the checkbox in case _apply_autostart failed and rolled back
            self._autostart_check.SetValue(is_autostart_enabled())

        # Persist and propagate
        self.main_window.save_settings()

        # Invalidate cache and re-read the new language
        from i18n import I18n
        I18n.invalidate_cache()
        self.main_window.i18n.get_language()

        # Refresh all visible labels in the main window
        self.main_window.apply_language_changes()
        return True

    def _refresh_dialog_labels(self):
        """Update this dialog's own title and notebook tab captions after a language change."""
        i18n = self.main_window.i18n
        self.SetTitle(i18n.t("settings_title"))
        self._notebook.SetPageText(0, i18n.t("tab_general"))
        self._notebook.SetPageText(1, i18n.t("tab_connection"))
        self._autostart_check.SetLabel(i18n.t("autostart_label"))
        self._apply_btn.SetLabel(i18n.t("apply"))

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_ok(self, event):
        if self._apply_values():
            self.EndModal(wx.ID_OK)

    def _on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def _on_apply(self, event):
        if self._apply_values():
            self._refresh_dialog_labels()
