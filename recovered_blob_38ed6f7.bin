import ctypes
import wx
from core.i18n import LANGUAGE_NAMES

# Win32 modifier constants for RegisterHotKey
_MOD_ALT     = 0x0001
_MOD_CONTROL = 0x0002
_MOD_SHIFT   = 0x0004
_MOD_WIN     = 0x0008


class _HotkeyCaptureAccessible(wx.Accessible):
    """Expose the hotkey capture field as a real hotkey field to screen readers."""

    def __init__(self, ctrl, name=""):
        super().__init__()
        self._ctrl = ctrl
        self._name = name

    def SetNameText(self, name: str):
        self._name = name

    def GetName(self, childId):
        return (wx.ACC_OK, self._name or self._ctrl.GetHint())

    def GetRole(self, childId):
        return (wx.ACC_OK, wx.ROLE_SYSTEM_HOTKEYFIELD)

    def GetValue(self, childId):
        return (wx.ACC_OK, self._ctrl.GetValue())

    def GetDescription(self, childId):
        return (wx.ACC_OK, self._ctrl.GetHint())


class _HotkeyCapture(wx.TextCtrl):
    """
    TextCtrl that captures the next key combination pressed while focused and
    stores it as (vk, mod) for use with RegisterHotKey.

    Tab / Shift+Tab always navigate focus normally.
    Delete or Backspace clears the hotkey.
    A combination with Ctrl or Alt (e.g. Ctrl+Shift+W) is recorded.
    """

    def __init__(self, parent, accessible_name=""):
        # No TE_READONLY — that flag removes the control from the Tab order on
        # Windows, making it unreachable for screen-reader users.  Character
        # insertion is blocked via EVT_CHAR instead.
        super().__init__(parent, style=wx.TE_PROCESS_ENTER)
        self._vk  = 0
        self._mod = 0
        self._accessible = _HotkeyCaptureAccessible(self, accessible_name)
        self.SetName(accessible_name)
        self.SetAccessible(self._accessible)
        self.Bind(wx.EVT_KEY_DOWN, self._on_key_down)
        self.Bind(wx.EVT_CHAR,     self._on_char)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)

    def SetAccessibleName(self, name: str):
        self.SetName(name)
        self._accessible.SetNameText(name)

    def _on_focus(self, event):
        self.SelectAll()
        event.Skip()

    def _on_char(self, event):
        # Block all character input; Tab is allowed through for focus traversal.
        if event.GetKeyCode() == wx.WXK_TAB:
            event.Skip()

    def _on_key_down(self, event):
        vk = event.GetRawKeyCode()

        # Tab / Shift+Tab: always let focus move normally.
        if vk == wx.WXK_TAB:
            event.Skip()
            return

        # Pure modifier keys (Ctrl, Alt, Shift, Win) — wait for a non-modifier.
        if vk in (0, 0x10, 0x11, 0x12, 0x5B, 0x5C):
            event.Skip()
            return

        # Delete / Backspace: clear the captured hotkey.
        if vk in (wx.WXK_DELETE, wx.WXK_BACK):
            self._vk  = 0
            self._mod = 0
            self.SetValue("")
            return

        mod = 0
        if event.ControlDown(): mod |= _MOD_CONTROL
        if event.AltDown():     mod |= _MOD_ALT
        if event.ShiftDown():   mod |= _MOD_SHIFT

        # Require Ctrl or Alt so that plain letters and Shift+Tab don't capture.
        if not (mod & (_MOD_CONTROL | _MOD_ALT)):
            return  # consume silently — EVT_CHAR is also blocked by _on_char

        self._vk  = vk
        self._mod = mod
        from main import _vk_mod_to_str
        self.SetValue(_vk_mod_to_str(vk, mod))


class SettingsDialog(wx.Dialog):
    """Settings dialog with a General, Connection, and Audio playback tab."""

    _AUDIO_SPEED_STEPS = [1.0, 1.5, 2.0]

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

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _format_speed(self, speed: float) -> str:
        """Format a speed float as a locale-sensitive label (e.g. '1,5×')."""
        sep = self.main_window.i18n.t("decimal_separator")
        return f"{speed:.1f}".replace(".", sep) + "×"

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

        self._sounds_check = wx.CheckBox(
            self._general_page, label=i18n.t("sounds_label")
        )
        gen_sizer.Add(self._sounds_check, 0, wx.ALL, 8)

        self._notifications_check = wx.CheckBox(
            self._general_page, label=i18n.t("notifications_label")
        )
        gen_sizer.Add(self._notifications_check, 0, wx.ALL, 8)

        self._autostart_check = wx.CheckBox(
            self._general_page, label=i18n.t("autostart_label")
        )
        gen_sizer.Add(self._autostart_check, 0, wx.ALL, 8)

        self._tray_icon_check = wx.CheckBox(
            self._general_page, label=i18n.t("tray_show_icon")
        )
        gen_sizer.Add(self._tray_icon_check, 0, wx.ALL, 8)

        self._updates_check = wx.CheckBox(
            self._general_page, label=i18n.t("updates_label")
        )
        gen_sizer.Add(self._updates_check, 0, wx.ALL, 8)

        self._hotkey_label = wx.StaticText(self._general_page, label=i18n.t("global_hotkey_label"))
        gen_sizer.Add(
            self._hotkey_label,
            0, wx.LEFT | wx.TOP | wx.RIGHT, 8,
        )
        self._hotkey_field = _HotkeyCapture(
            self._general_page,
            accessible_name=i18n.t("global_hotkey_label"),
        )
        self._hotkey_field.SetHint(i18n.t("global_hotkey_hint"))
        gen_sizer.Add(self._hotkey_field, 0, wx.EXPAND | wx.ALL, 8)

        self._general_page.SetSizer(gen_sizer)
        self._notebook.AddPage(self._general_page, i18n.t("tab_general"))

        # ── User Interface tab ───────────────────────────────────────────────
        self._ui_page = wx.Panel(self._notebook)
        ui_sizer = wx.BoxSizer(wx.VERTICAL)

        ui_sizer.Add(
            wx.StaticText(self._ui_page, label=i18n.t("ui_messages_page_size_label")),
            0, wx.LEFT | wx.TOP | wx.RIGHT, 8,
        )
        self._messages_page_size_field = wx.TextCtrl(self._ui_page, style=wx.TE_DONTWRAP)
        ui_sizer.Add(self._messages_page_size_field, 0, wx.EXPAND | wx.ALL, 8)

        # Wrap radio buttons in a StaticBox so NVDA reads the group label when
        # the user tabs into them.  A plain StaticText label is not sufficient
        # for screen readers to announce group membership.
        self._focus_box = wx.StaticBox(self._ui_page, label=i18n.t("ui_focus_label"))
        focus_sizer = wx.StaticBoxSizer(self._focus_box, wx.VERTICAL)

        self._focus_message_field_rb = wx.RadioButton(
            self._focus_box, label=i18n.t("ui_focus_message_field"), style=wx.RB_GROUP
        )
        focus_sizer.Add(self._focus_message_field_rb, 0, wx.LEFT | wx.TOP, 5)

        self._focus_unread_or_last_rb = wx.RadioButton(
            self._focus_box, label=i18n.t("ui_focus_unread_or_last")
        )
        focus_sizer.Add(self._focus_unread_or_last_rb, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        ui_sizer.Add(focus_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self._voice_focus_box = wx.StaticBox(
            self._ui_page, label=i18n.t("ui_voice_record_focus_label")
        )
        voice_focus_sizer = wx.StaticBoxSizer(self._voice_focus_box, wx.VERTICAL)

        self._voice_focus_send_rb = wx.RadioButton(
            self._voice_focus_box,
            label=i18n.t("ui_voice_record_focus_send"),
            style=wx.RB_GROUP,
        )
        voice_focus_sizer.Add(self._voice_focus_send_rb, 0, wx.LEFT | wx.TOP, 5)

        self._voice_focus_discard_rb = wx.RadioButton(
            self._voice_focus_box, label=i18n.t("ui_voice_record_focus_discard")
        )
        voice_focus_sizer.Add(
            self._voice_focus_discard_rb, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5
        )

        ui_sizer.Add(voice_focus_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self._ui_page.SetSizer(ui_sizer)
        self._notebook.AddPage(self._ui_page, i18n.t("tab_ui"))

        # ── Connection tab ───────────────────────────────────────────────────
        self._conn_page = wx.Panel(self._notebook)
        conn_sizer = wx.BoxSizer(wx.VERTICAL)

        self._custom_api_check = wx.CheckBox(
            self._conn_page, label=i18n.t("connection_custom_api_label")
        )
        conn_sizer.Add(self._custom_api_check, 0, wx.ALL, 8)

        self._server_label = wx.StaticText(self._conn_page, label=i18n.t("connection_server_label"))
        conn_sizer.Add(self._server_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._server_field = wx.TextCtrl(self._conn_page, style=wx.TE_DONTWRAP)
        conn_sizer.Add(self._server_field, 0, wx.EXPAND | wx.ALL, 8)

        self._ws_server_label = wx.StaticText(self._conn_page, label=i18n.t("connection_ws_server_label"))
        conn_sizer.Add(self._ws_server_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._ws_server_field = wx.TextCtrl(self._conn_page, style=wx.TE_DONTWRAP)
        conn_sizer.Add(self._ws_server_field, 0, wx.EXPAND | wx.ALL, 8)

        self._port_label = wx.StaticText(self._conn_page, label=i18n.t("wpp_port_label"))
        conn_sizer.Add(self._port_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._port_field = wx.TextCtrl(self._conn_page, style=wx.TE_DONTWRAP)
        conn_sizer.Add(self._port_field, 0, wx.EXPAND | wx.ALL, 8)

        self._api_key_label = wx.StaticText(self._conn_page, label=i18n.t("connection_api_key_label"))
        conn_sizer.Add(self._api_key_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._api_key_field = wx.TextCtrl(self._conn_page, style=wx.TE_DONTWRAP)
        conn_sizer.Add(self._api_key_field, 0, wx.EXPAND | wx.ALL, 8)

        self._conn_page.SetSizer(conn_sizer)
        self._notebook.AddPage(self._conn_page, i18n.t("tab_connection"))

        self._custom_api_check.Bind(wx.EVT_CHECKBOX, self._on_custom_api_toggle)

        # ── Audio playback tab ───────────────────────────────────────────────
        self._audio_page = wx.Panel(self._notebook)
        audio_sizer = wx.BoxSizer(wx.VERTICAL)

        self._audio_speed_label = wx.StaticText(
            self._audio_page, label=i18n.t("audio_speed_label")
        )
        audio_sizer.Add(self._audio_speed_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)

        self._audio_speed_combo = wx.ComboBox(
            self._audio_page,
            style=wx.CB_READONLY,
            choices=[self._format_speed(s) for s in self._AUDIO_SPEED_STEPS],
        )
        audio_sizer.Add(self._audio_speed_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._audio_page.SetSizer(audio_sizer)
        self._notebook.AddPage(self._audio_page, i18n.t("tab_audio_playback"))

        # ── Button row ───────────────────────────────────────────────────────
        btn_sizer = wx.StdDialogButtonSizer()
        self._ok_btn = wx.Button(self, wx.ID_OK, label=i18n.t("ok"))
        self._cancel_btn = wx.Button(self, wx.ID_CANCEL, label=i18n.t("cancel"))
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

        sounds = self.main_window.settings.get("general", {}).get("sounds_enabled", True)
        self._sounds_check.SetValue(sounds)

        notifs = self.main_window.settings.get("general", {}).get("notifications_enabled", True)
        self._notifications_check.SetValue(notifs)

        from autostart import is_autostart_enabled
        self._autostart_check.SetValue(is_autostart_enabled())

        show_tray = self.main_window.settings.get("general", {}).get("show_tray_icon", True)
        self._tray_icon_check.SetValue(show_tray)

        updates = self.main_window.settings.get("general", {}).get("updates_enabled", True)
        self._updates_check.SetValue(updates)

        hk = self.main_window.settings.get("general", {}).get("global_hotkey")
        if hk and isinstance(hk, dict) and hk.get("vk"):
            from main import _vk_mod_to_str
            self._hotkey_field.SetValue(_vk_mod_to_str(hk["vk"], hk.get("mod", 0)))
            self._hotkey_field._vk  = hk["vk"]
            self._hotkey_field._mod = hk.get("mod", 0)
        else:
            self._hotkey_field.SetValue("")
            self._hotkey_field._vk  = 0
            self._hotkey_field._mod = 0

        page_size = self.main_window.settings.get("user_interface", {}).get("messages_page_size", 200)
        self._messages_page_size_field.SetValue(str(page_size))

        focus_on_open = self.main_window.settings.get("user_interface", {}).get("focus_on_open", "message_field")
        if focus_on_open == "unread_or_last":
            self._focus_unread_or_last_rb.SetValue(True)
        else:
            self._focus_message_field_rb.SetValue(True)

        voice_record_focus = self.main_window.settings.get("user_interface", {}).get(
            "voice_record_focus", "send"
        )
        if voice_record_focus == "discard":
            self._voice_focus_discard_rb.SetValue(True)
        else:
            self._voice_focus_send_rb.SetValue(True)

        conn = self.main_window.settings.get("connection", {})
        custom_api = conn.get("wpp_custom_api", False)
        self._custom_api_check.SetValue(custom_api)

        server = conn.get("wpp_server", "http://127.0.0.1")
        self._server_field.SetValue(server)

        ws_server = conn.get("wpp_ws_server", "ws://127.0.0.1")
        self._ws_server_field.SetValue(ws_server)

        self._port_field.SetValue(str(self.main_window.wpp_port))

        api_key = conn.get("wpp_api_key", "wz-local-api-key")
        self._api_key_field.SetValue(api_key)

        self._update_fields_state()

    def _update_fields_state(self):
        is_custom = self._custom_api_check.GetValue()
        self._server_field.Enable(is_custom)
        self._ws_server_field.Enable(is_custom)
        self._api_key_field.Enable(is_custom)

    def _on_custom_api_toggle(self, event):
        self._update_fields_state()

        saved_speed = self.main_window.settings.get("audio_playback", {}).get("audio_default_speed", 1.0)
        try:
            speed_idx = self._AUDIO_SPEED_STEPS.index(float(saved_speed))
        except (ValueError, TypeError):
            speed_idx = 0
        self._audio_speed_combo.SetSelection(speed_idx)

    def _validate(self) -> bool:
        """Return True if all values are valid; show an error and return False otherwise."""
        page_size_str = self._messages_page_size_field.GetValue().strip()
        try:
            page_size = int(page_size_str)
            if page_size < 1:
                raise ValueError
        except ValueError:
            wx.MessageBox(
                self.main_window.i18n.t("invalid_messages_page_size"),
                self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._messages_page_size_field.SetFocus()
            return False

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

        if self._custom_api_check.GetValue():
            server_str = self._server_field.GetValue().strip()
            ws_server_str = self._ws_server_field.GetValue().strip()
            if not server_str:
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_server_url"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                self._server_field.SetFocus()
                return False
            if not ws_server_str:
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_ws_server_url"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                self._ws_server_field.SetFocus()
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

        # UI: messages page size
        page_size = int(self._messages_page_size_field.GetValue().strip())
        self.main_window.settings.setdefault("user_interface", {})["messages_page_size"] = page_size

        # UI: focus on open
        focus_on_open = (
            "unread_or_last" if self._focus_unread_or_last_rb.GetValue()
            else "message_field"
        )
        self.main_window.settings.setdefault("user_interface", {})["focus_on_open"] = focus_on_open

        # UI: focus when recording a voice message
        voice_record_focus = (
            "discard" if self._voice_focus_discard_rb.GetValue()
            else "send"
        )
        self.main_window.settings.setdefault("user_interface", {})[
            "voice_record_focus"
        ] = voice_record_focus

        # Connection settings
        custom_api = self._custom_api_check.GetValue()
        self.main_window.settings.setdefault("connection", {})["wpp_custom_api"] = custom_api
        self.main_window.wpp_custom_api = custom_api

        server = self._server_field.GetValue().strip()
        self.main_window.settings.setdefault("connection", {})["wpp_server"] = server
        self.main_window.wpp_server = server

        ws_server = self._ws_server_field.GetValue().strip()
        self.main_window.settings.setdefault("connection", {})["wpp_ws_server"] = ws_server
        self.main_window.wpp_ws_server = ws_server

        port = int(self._port_field.GetValue().strip())
        self.main_window.settings.setdefault("connection", {})["wpp_port"] = port
        self.main_window.wpp_port = port

        api_key = self._api_key_field.GetValue().strip()
        self.main_window.settings.setdefault("connection", {})["wpp_api_key"] = api_key
        self.main_window.wpp_api_key = api_key

        # Sounds
        self.main_window.settings.setdefault("general", {})["sounds_enabled"] = (
            self._sounds_check.GetValue()
        )

        # Notifications
        self.main_window.settings.setdefault("general", {})["notifications_enabled"] = (
            self._notifications_check.GetValue()
        )

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

        # Updates
        self.main_window.settings.setdefault("general", {})["updates_enabled"] = (
            self._updates_check.GetValue()
        )

        # Tray icon
        new_show_tray = self._tray_icon_check.GetValue()
        old_show_tray = self.main_window.settings.get("general", {}).get("show_tray_icon", True)
        self.main_window.settings.setdefault("general", {})["show_tray_icon"] = new_show_tray
        if new_show_tray and not old_show_tray:
            # Enable tray icon
            if self.main_window.tray_icon is None:
                self.main_window._init_tray()
        elif not new_show_tray and old_show_tray:
            # Disable tray icon
            if self.main_window.tray_icon is not None:
                try:
                    self.main_window.tray_icon.RemoveIcon()
                    self.main_window.tray_icon.Destroy()
                except Exception:
                    pass
                self.main_window.tray_icon = None

        # Audio playback speed
        speed_sel = self._audio_speed_combo.GetSelection()
        if speed_sel != wx.NOT_FOUND:
            new_speed = self._AUDIO_SPEED_STEPS[speed_sel]
            self.main_window.settings.setdefault("audio_playback", {})["audio_default_speed"] = new_speed
            # Sync live playback panel so the button label and next playback use the new speed
            cp = getattr(self.main_window, "conversations_panel", None)
            if cp is not None:
                try:
                    cp._audio_speed_index = speed_sel
                    cp.audio_speed_btn.SetLabel(cp._format_speed(new_speed))
                    # Apply to any audio currently playing
                    if cp._audio_tempo_ctrl is not None:
                        cp._audio_tempo_ctrl.tempo = cp._audio_tempo_map.get(new_speed, 0)
                except Exception:
                    pass

        # Global hotkey
        self.main_window.set_global_hotkey(self._hotkey_field._vk, self._hotkey_field._mod)

        # Persist and propagate
        self.main_window.save_settings()

        # Invalidate cache and re-read the new language
        from core.i18n import I18n
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
        self._notebook.SetPageText(1, i18n.t("tab_ui"))
        self._notebook.SetPageText(2, i18n.t("tab_connection"))
        self._notebook.SetPageText(3, i18n.t("tab_audio_playback"))
        self._sounds_check.SetLabel(i18n.t("sounds_label"))
        self._notifications_check.SetLabel(i18n.t("notifications_label"))
        self._autostart_check.SetLabel(i18n.t("autostart_label"))
        self._tray_icon_check.SetLabel(i18n.t("tray_show_icon"))
        self._updates_check.SetLabel(i18n.t("updates_label"))
        self._focus_box.SetLabel(i18n.t("ui_focus_label"))
        self._focus_message_field_rb.SetLabel(i18n.t("ui_focus_message_field"))
        self._focus_unread_or_last_rb.SetLabel(i18n.t("ui_focus_unread_or_last"))
        self._voice_focus_box.SetLabel(i18n.t("ui_voice_record_focus_label"))
        self._voice_focus_send_rb.SetLabel(i18n.t("ui_voice_record_focus_send"))
        self._voice_focus_discard_rb.SetLabel(i18n.t("ui_voice_record_focus_discard"))
        self._hotkey_label.SetLabel(i18n.t("global_hotkey_label"))
        self._hotkey_field.SetAccessibleName(i18n.t("global_hotkey_label"))
        self._hotkey_field.SetHint(i18n.t("global_hotkey_hint"))
        self._ok_btn.SetLabel(i18n.t("ok"))
        self._cancel_btn.SetLabel(i18n.t("cancel"))
        self._apply_btn.SetLabel(i18n.t("apply"))
        self._audio_speed_label.SetLabel(i18n.t("audio_speed_label"))
        self._custom_api_check.SetLabel(i18n.t("connection_custom_api_label"))
        self._server_label.SetLabel(i18n.t("connection_server_label"))
        self._ws_server_label.SetLabel(i18n.t("connection_ws_server_label"))
        self._port_label.SetLabel(i18n.t("wpp_port_label"))
        self._api_key_label.SetLabel(i18n.t("connection_api_key_label"))
        # Regenerate speed labels — decimal separator may have changed with language
        cur_sel = self._audio_speed_combo.GetSelection()
        self._audio_speed_combo.Clear()
        for s in self._AUDIO_SPEED_STEPS:
            self._audio_speed_combo.Append(self._format_speed(s))
        self._audio_speed_combo.SetSelection(cur_sel if cur_sel != wx.NOT_FOUND else 0)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_ok(self, event):
        if self._apply_values():
            self.EndModal(wx.ID_OK)

    def _on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)

    def _on_apply(self, event):
        if self._apply_values():
            self._refresh_dialog_labels()
