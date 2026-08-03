import ctypes
import os
import wx
from core.i18n import LANGUAGE_NAMES
from core.sound_system import (
    SOUND_EVENTS, ALERT_TONE_COUNT, alert_tone_choice_keys, resolve_alert_tone_path,
    DEFAULT_PACK_ID, import_soundpack, AlertPreviewController,
)
from core.audio_devices import (
    enumerate_output_devices, enumerate_input_devices, test_input_device,
)

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
        self._restart_required = False
        self._build_ui()
        self._load_values()
        self.Fit()
        self.SetMinSize((360, -1))
        self.Centre()
        # Enter on the sound events list must toggle the selected event, not
        # trigger the dialog's default OK button — EVT_CHAR_HOOK fires before
        # that default-button handling, so it's the only reliable place to
        # intercept Enter (Space alone is caught fine by the list's own
        # EVT_KEY_DOWN handler, since Space has no such competing default).
        self.Bind(wx.EVT_CHAR_HOOK, self._on_dialog_char_hook)

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

        self._msg_list_mode_box = wx.StaticBox(
            self._ui_page, label=i18n.t("ui_message_list_mode_label")
        )
        msg_list_mode_sizer = wx.StaticBoxSizer(self._msg_list_mode_box, wx.VERTICAL)

        self._msg_list_mode_classic_rb = wx.RadioButton(
            self._msg_list_mode_box,
            label=i18n.t("ui_message_list_mode_classic"),
            style=wx.RB_GROUP,
        )
        msg_list_mode_sizer.Add(self._msg_list_mode_classic_rb, 0, wx.LEFT | wx.TOP, 5)

        self._msg_list_mode_listbox_rb = wx.RadioButton(
            self._msg_list_mode_box, label=i18n.t("ui_message_list_mode_listbox")
        )
        msg_list_mode_sizer.Add(
            self._msg_list_mode_listbox_rb, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5
        )

        ui_sizer.Add(msg_list_mode_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self._self_ref_box = wx.StaticBox(
            self._ui_page, label=i18n.t("ui_self_reference_label")
        )
        self_ref_sizer = wx.StaticBoxSizer(self._self_ref_box, wx.VERTICAL)

        self._self_ref_eu_rb = wx.RadioButton(
            self._self_ref_box, label=i18n.t("sender_you"), style=wx.RB_GROUP
        )
        self_ref_sizer.Add(self._self_ref_eu_rb, 0, wx.LEFT | wx.TOP, 5)

        self._self_ref_voce_rb = wx.RadioButton(
            self._self_ref_box, label=i18n.t("ui_self_reference_voce")
        )
        self_ref_sizer.Add(self._self_ref_voce_rb, 0, wx.LEFT | wx.TOP, 5)

        self._self_ref_other_rb = wx.RadioButton(
            self._self_ref_box, label=i18n.t("ui_self_reference_other")
        )
        self_ref_sizer.Add(self._self_ref_other_rb, 0, wx.LEFT | wx.TOP | wx.BOTTOM, 5)

        self._self_ref_custom_label = wx.StaticText(
            self._self_ref_box, label=i18n.t("ui_self_reference_custom_label")
        )
        self_ref_sizer.Add(
            self._self_ref_custom_label, 0, wx.LEFT | wx.RIGHT, 8
        )
        self._self_ref_custom_field = wx.TextCtrl(self._self_ref_box, style=wx.TE_DONTWRAP)
        self_ref_sizer.Add(
            self._self_ref_custom_field, 0, wx.EXPAND | wx.ALL, 8
        )

        for rb in (self._self_ref_eu_rb, self._self_ref_voce_rb, self._self_ref_other_rb):
            rb.Bind(wx.EVT_RADIOBUTTON, self._on_self_reference_toggle)

        ui_sizer.Add(self_ref_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self._ui_page.SetSizer(ui_sizer)
        self._notebook.AddPage(self._ui_page, i18n.t("tab_ui"))

        # ── Spoken content tab ───────────────────────────────────────────────
        self._speech_page = wx.Panel(self._notebook)
        speech_sizer = wx.BoxSizer(wx.VERTICAL)

        self._announce_typing_check = wx.CheckBox(
            self._speech_page, label=i18n.t("speech_announce_typing_label")
        )
        speech_sizer.Add(self._announce_typing_check, 0, wx.ALL, 8)

        self._announce_recording_check = wx.CheckBox(
            self._speech_page, label=i18n.t("speech_announce_recording_label")
        )
        speech_sizer.Add(self._announce_recording_check, 0, wx.ALL, 8)

        self._speech_page.SetSizer(speech_sizer)
        self._notebook.AddPage(self._speech_page, i18n.t("tab_speech_content"))

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

        # ── Audio Devices tab ────────────────────────────────────────────────
        self._audio_devices_page = wx.Panel(self._notebook)
        adev_sizer = wx.BoxSizer(wx.VERTICAL)

        self._audio_input_label = wx.StaticText(
            self._audio_devices_page, label=i18n.t("audio_input_device_label")
        )
        adev_sizer.Add(self._audio_input_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._audio_input_combo = wx.ComboBox(self._audio_devices_page, style=wx.CB_READONLY)
        adev_sizer.Add(self._audio_input_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._audio_output_label = wx.StaticText(
            self._audio_devices_page, label=i18n.t("audio_output_device_label")
        )
        adev_sizer.Add(self._audio_output_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._audio_output_combo = wx.ComboBox(self._audio_devices_page, style=wx.CB_READONLY)
        adev_sizer.Add(self._audio_output_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._noise_reduction_check = wx.CheckBox(
            self._audio_devices_page, label=i18n.t("noise_reduction_label")
        )
        adev_sizer.Add(self._noise_reduction_check, 0, wx.ALL, 8)

        self._audio_devices_page.SetSizer(adev_sizer)
        self._notebook.AddPage(self._audio_devices_page, i18n.t("tab_audio_devices"))

        # ── Sound Events tab ─────────────────────────────────────────────────
        self._sound_events_page = wx.Panel(self._notebook)
        se_sizer = wx.BoxSizer(wx.VERTICAL)

        self._sound_pack_label = wx.StaticText(
            self._sound_events_page, label=i18n.t("sound_pack_label")
        )
        se_sizer.Add(self._sound_pack_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._sound_pack_combo = wx.ComboBox(self._sound_events_page, style=wx.CB_READONLY)
        se_sizer.Add(self._sound_pack_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._import_sound_pack_btn = wx.Button(
            self._sound_events_page, label=i18n.t("import_sound_pack_button")
        )
        se_sizer.Add(self._import_sound_pack_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._sound_events_list_label = wx.StaticText(
            self._sound_events_page, label=i18n.t("sound_events_list_label")
        )
        se_sizer.Add(self._sound_events_list_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)

        # A plain wx.ListBox, not wx.CheckListBox: NVDA does not reliably
        # expose CheckListBox items' checked state or checkbox role on
        # Windows, so each item's on/off state is spelled out in its own
        # label instead (", Ativado"/", Desativado") — Enter/Space toggles
        # it. See _sound_event_label()/_toggle_current_sound_event().
        self._sound_events_list = wx.ListBox(self._sound_events_page)
        se_sizer.Add(self._sound_events_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        self._sound_event_path_label = wx.StaticText(
            self._sound_events_page, label=i18n.t("sound_event_path_label")
        )
        se_sizer.Add(self._sound_event_path_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._sound_event_path_field = wx.TextCtrl(self._sound_events_page, style=wx.TE_DONTWRAP)
        se_sizer.Add(self._sound_event_path_field, 0, wx.EXPAND | wx.ALL, 8)

        se_btn_row = wx.BoxSizer(wx.HORIZONTAL)
        self._activate_all_btn = wx.Button(
            self._sound_events_page, label=i18n.t("activate_all_sounds")
        )
        self._deactivate_all_btn = wx.Button(
            self._sound_events_page, label=i18n.t("deactivate_all_sounds")
        )
        se_btn_row.Add(self._activate_all_btn, 0, wx.RIGHT, 6)
        se_btn_row.Add(self._deactivate_all_btn, 0)
        se_sizer.Add(se_btn_row, 0, wx.ALL, 8)

        self._sound_events_page.SetSizer(se_sizer)
        self._notebook.AddPage(self._sound_events_page, i18n.t("tab_sound_events"))

        self._sound_pack_combo.Bind(wx.EVT_COMBOBOX, self._on_sound_pack_selected)
        self._import_sound_pack_btn.Bind(wx.EVT_BUTTON, self._on_import_sound_pack)
        self._sound_events_list.Bind(wx.EVT_LISTBOX, self._on_sound_event_selected)
        self._sound_events_list.Bind(wx.EVT_KEY_DOWN, self._on_sound_event_list_key_down)
        self._sound_event_path_field.Bind(wx.EVT_TEXT, self._on_sound_event_path_changed)
        self._activate_all_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all_sound_events(True))
        self._deactivate_all_btn.Bind(wx.EVT_BUTTON, lambda e: self._set_all_sound_events(False))

        # ── Alert Tones tab ──────────────────────────────────────────────────
        self._alert_page = wx.Panel(self._notebook)
        alert_sizer = wx.BoxSizer(wx.VERTICAL)

        self._alert_choice_keys = alert_tone_choice_keys()
        alert_choice_labels = [i18n.t("alert_tone_default")] + [
            i18n.t("alert_tone_item").format(n=n) for n in range(1, ALERT_TONE_COUNT + 1)
        ] + [i18n.t("alert_tone_custom")]

        self._alert_private_label = wx.StaticText(
            self._alert_page, label=i18n.t("alert_tone_private_label")
        )
        alert_sizer.Add(self._alert_private_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._alert_private_combo = wx.ComboBox(
            self._alert_page, style=wx.CB_READONLY, choices=alert_choice_labels
        )
        alert_sizer.Add(self._alert_private_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._alert_private_preview_btn = wx.Button(
            self._alert_page, label=i18n.t("preview_sound_play")
        )
        alert_sizer.Add(self._alert_private_preview_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._alert_private_custom_label = wx.StaticText(
            self._alert_page, label=i18n.t("alert_tone_custom_path_label")
        )
        alert_sizer.Add(self._alert_private_custom_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._alert_private_custom_field = wx.TextCtrl(self._alert_page, style=wx.TE_DONTWRAP)
        alert_sizer.Add(self._alert_private_custom_field, 0, wx.EXPAND | wx.ALL, 8)

        self._alert_group_label = wx.StaticText(
            self._alert_page, label=i18n.t("alert_tone_group_label")
        )
        alert_sizer.Add(self._alert_group_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._alert_group_combo = wx.ComboBox(
            self._alert_page, style=wx.CB_READONLY, choices=alert_choice_labels
        )
        alert_sizer.Add(self._alert_group_combo, 0, wx.EXPAND | wx.ALL, 8)

        self._alert_group_preview_btn = wx.Button(
            self._alert_page, label=i18n.t("preview_sound_play")
        )
        alert_sizer.Add(self._alert_group_preview_btn, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self._alert_group_custom_label = wx.StaticText(
            self._alert_page, label=i18n.t("alert_tone_custom_path_label")
        )
        alert_sizer.Add(self._alert_group_custom_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._alert_group_custom_field = wx.TextCtrl(self._alert_page, style=wx.TE_DONTWRAP)
        alert_sizer.Add(self._alert_group_custom_field, 0, wx.EXPAND | wx.ALL, 8)

        self._alert_page.SetSizer(alert_sizer)
        self._notebook.AddPage(self._alert_page, i18n.t("tab_alert_tones"))

        # ── Storage tab ──────────────────────────────────────────────────────
        self._storage_page = wx.Panel(self._notebook)
        storage_sizer = wx.BoxSizer(wx.VERTICAL)

        self._auto_download_media_check = wx.CheckBox(
            self._storage_page, label=i18n.t("auto_download_media_label")
        )
        storage_sizer.Add(self._auto_download_media_check, 0, wx.ALL, 8)

        self._media_max_days_label = wx.StaticText(
            self._storage_page, label=i18n.t("media_max_days_label")
        )
        storage_sizer.Add(self._media_max_days_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._media_max_days_field = wx.TextCtrl(self._storage_page, style=wx.TE_DONTWRAP)
        storage_sizer.Add(self._media_max_days_field, 0, wx.EXPAND | wx.ALL, 8)

        self._media_max_mb_label = wx.StaticText(
            self._storage_page, label=i18n.t("media_max_mb_label")
        )
        storage_sizer.Add(self._media_max_mb_label, 0, wx.LEFT | wx.TOP | wx.RIGHT, 8)
        self._media_max_mb_field = wx.TextCtrl(self._storage_page, style=wx.TE_DONTWRAP)
        storage_sizer.Add(self._media_max_mb_field, 0, wx.EXPAND | wx.ALL, 8)

        self._storage_page.SetSizer(storage_sizer)
        self._notebook.AddPage(self._storage_page, i18n.t("tab_storage"))

        self._alert_private_combo.Bind(wx.EVT_COMBOBOX, self._on_alert_choice_changed)
        self._alert_group_combo.Bind(wx.EVT_COMBOBOX, self._on_alert_choice_changed)

        # Preview buttons — sharing a group so starting one stops the other.
        _alert_preview_group = []
        self._alert_private_preview = AlertPreviewController(
            self.main_window, self._alert_private_preview_btn,
            lambda: self._resolve_alert_preview_path("private"),
            group=_alert_preview_group,
        )
        self._alert_group_preview = AlertPreviewController(
            self.main_window, self._alert_group_preview_btn,
            lambda: self._resolve_alert_preview_path("group"),
            group=_alert_preview_group,
        )

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

        message_list_mode = self.main_window.settings.get("user_interface", {}).get(
            "message_list_mode", "classic"
        )
        # "dataview" was the old (now-removed) alternative mode name — treat
        # it as "listbox" so settings saved before the switch still resolve
        # to the equivalent current option.
        if message_list_mode in ("listbox", "dataview"):
            self._msg_list_mode_listbox_rb.SetValue(True)
        else:
            self._msg_list_mode_classic_rb.SetValue(True)

        self_reference_mode = self.main_window.settings.get("user_interface", {}).get(
            "self_reference_mode", "eu"
        )
        if self_reference_mode == "voce":
            self._self_ref_voce_rb.SetValue(True)
        elif self_reference_mode == "custom":
            self._self_ref_other_rb.SetValue(True)
        else:
            self._self_ref_eu_rb.SetValue(True)
        self._self_ref_custom_field.SetValue(
            self.main_window.settings.get("user_interface", {}).get(
                "self_reference_custom_word", ""
            )
        )
        self._update_self_reference_field_state()

        speech = self.main_window.settings.get("speech_content", {})
        self._announce_typing_check.SetValue(speech.get("announce_typing", True))
        self._announce_recording_check.SetValue(speech.get("announce_recording", True))

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

        # Audio devices
        audio_devices_cfg = self.main_window.settings.get("audio_devices", {})
        self._reload_audio_device_choices(
            prefer_output=audio_devices_cfg.get("output_device_name") or None,
            prefer_input=audio_devices_cfg.get("input_device_name") or None,
        )
        noise_red = self.main_window.settings.get("general", {}).get("noise_reduction_enabled", False)
        self._noise_reduction_check.SetValue(noise_red)

        # Sound events / packs
        self.main_window.refresh_sound_packs()
        self._pack_event_settings = {}
        self._reload_sound_pack_choices()

        # Alert tones
        tones = self.main_window.settings.get("alert_tones", {})
        self._set_alert_combo(self._alert_private_combo, tones.get("private", "default"))
        self._alert_private_custom_field.SetValue(tones.get("private_custom_path", ""))
        self._set_alert_combo(self._alert_group_combo, tones.get("group", "default"))
        self._alert_group_custom_field.SetValue(tones.get("group_custom_path", ""))
        self._update_alert_custom_field_state()

        # Storage
        storage = self.main_window.settings.get("storage", {})
        self._auto_download_media_check.SetValue(storage.get("auto_download_media", True))
        self._media_max_days_field.SetValue(str(storage.get("media_max_days", 30)))
        self._media_max_mb_field.SetValue(str(storage.get("media_max_mb", 100)))

    def _set_alert_combo(self, combo, choice_key: str):
        try:
            idx = self._alert_choice_keys.index(choice_key)
        except ValueError:
            idx = 0
        combo.SetSelection(idx)

    # ── Audio Devices tab ────────────────────────────────────────────────────

    def _current_combo_device_name(self, combo, names):
        """Friendly name of whatever `combo` currently has selected (None for
        the "system default" first entry, or no selection at all)."""
        sel = combo.GetSelection()
        if sel > 0 and sel - 1 < len(names):
            return names[sel - 1]
        return None

    def _select_device_in_combo(self, combo, names, name):
        if name and name in names:
            combo.SetSelection(1 + names.index(name))
        else:
            combo.SetSelection(0)

    def _reload_audio_device_choices(self, prefer_output=None, prefer_input=None):
        """(Re)populate the input/output device combos.

        `prefer_output`/`prefer_input` seed the initial selection from stored
        settings on first load; omit them on later calls (e.g. after a
        language change) so whatever's currently selected is preserved
        instead. A configured device that isn't currently enumerated (e.g.
        temporarily unplugged) is kept as an extra entry rather than silently
        dropped — reopening Settings while it's briefly unavailable must not
        wipe it from settings just because it's not in the combo's list.
        """
        i18n = self.main_window.i18n

        prev_output = prefer_output if prefer_output is not None else self._current_combo_device_name(
            self._audio_output_combo, getattr(self, "_audio_output_device_names", [])
        )
        self._audio_output_device_names = [name for _idx, name in enumerate_output_devices()]
        if prev_output and prev_output not in self._audio_output_device_names:
            self._audio_output_device_names.append(prev_output)
        self._audio_output_combo.Set(
            [i18n.t("audio_default_output_device")] + self._audio_output_device_names
        )
        self._select_device_in_combo(self._audio_output_combo, self._audio_output_device_names, prev_output)

        prev_input = prefer_input if prefer_input is not None else self._current_combo_device_name(
            self._audio_input_combo, getattr(self, "_audio_input_device_names", [])
        )
        self._audio_input_device_names = [name for _idx, name in enumerate_input_devices()]
        if prev_input and prev_input not in self._audio_input_device_names:
            self._audio_input_device_names.append(prev_input)
        self._audio_input_combo.Set(
            [i18n.t("audio_default_input_device")] + self._audio_input_device_names
        )
        self._select_device_in_combo(self._audio_input_combo, self._audio_input_device_names, prev_input)

    # ── Soundpacks (Sound Events tab) ────────────────────────────────────────

    def _reload_sound_pack_choices(self, select_pack_id: "str | None" = None):
        """(Re)populate the pack combobox from main_window._sound_packs and
        show the given pack's (or the currently-active, or default) settings.
        Called on initial load and again after a successful pack import.
        """
        i18n = self.main_window.i18n
        packs = self.main_window._sound_packs
        self._sound_pack_ids = sorted(
            packs.keys(), key=lambda pid: (pid != DEFAULT_PACK_ID, packs[pid]["name"].lower())
        )
        pack_labels = [
            i18n.t("sound_pack_default_label") if pid == DEFAULT_PACK_ID else packs[pid]["name"]
            for pid in self._sound_pack_ids
        ]
        self._sound_pack_combo.Set(pack_labels)

        if select_pack_id and select_pack_id in self._sound_pack_ids:
            target = select_pack_id
        else:
            target = self.main_window.settings.get("active_sound_pack", DEFAULT_PACK_ID)
            if target not in self._sound_pack_ids:
                target = DEFAULT_PACK_ID if DEFAULT_PACK_ID in self._sound_pack_ids else (
                    self._sound_pack_ids[0] if self._sound_pack_ids else None
                )
        if not target:
            return

        # Seed working (in-memory, editable) settings for any pack not
        # already tracked this dialog session, from what's actually stored.
        stored = self.main_window.settings.get("sound_events", {})
        for pid in self._sound_pack_ids:
            if pid in self._pack_event_settings:
                continue
            pack_stored = stored.get(pid, {})
            self._pack_event_settings[pid] = {}
            for key, _default_filename in SOUND_EVENTS:
                cfg = pack_stored.get(key) or {}
                self._pack_event_settings[pid][key] = {
                    "enabled": cfg.get("enabled", True),
                    "path": cfg.get("path", ""),
                }

        self._current_pack_id = target
        self._sound_pack_combo.SetSelection(self._sound_pack_ids.index(target))
        self._load_sound_events_display(target)

    def _sound_event_label(self, key: str, enabled: bool) -> str:
        """Item label spelling out the on/off state in text (', Ativado' /
        ', Desativado') since NVDA can't reliably read a CheckListBox item's
        checked state or checkbox role on Windows."""
        i18n = self.main_window.i18n
        state = i18n.t("sound_event_state_enabled") if enabled else i18n.t("sound_event_state_disabled")
        return f"{i18n.t(f'sound_event_{key}')}, {state}"

    def _load_sound_events_display(self, pack_id: str):
        """Populate the list's item labels (name + on/off state) from working
        settings for `pack_id`, and select/display the first event's path."""
        settings_for_pack = self._pack_event_settings.get(pack_id, {})
        labels = [
            self._sound_event_label(key, (settings_for_pack.get(key) or {}).get("enabled", True))
            for key, _default_filename in SOUND_EVENTS
        ]
        self._sound_events_list.Set(labels)
        if self._sound_events_list.GetCount() > 0:
            self._sound_events_list.SetSelection(0)
        self._update_sound_event_path_display()

    def _update_sound_event_path_display(self):
        """Show the resolved path for the currently-selected event: the
        user's own override for the current pack if they set one, else the
        path that would actually be used at runtime (current pack's file,
        falling back to the default pack's)."""
        idx = self._sound_events_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(SOUND_EVENTS):
            self._sound_event_path_field.ChangeValue("")
            return
        key = SOUND_EVENTS[idx][0]
        cfg = self._pack_event_settings.get(self._current_pack_id, {}).get(key) or {}
        override = cfg.get("path", "")
        if override:
            display_path = override
        else:
            from core.sound_system import resolve_sound_event_path
            pack = self.main_window._sound_packs.get(self._current_pack_id)
            default_pack = self.main_window._default_sound_pack
            display_path = resolve_sound_event_path(pack, default_pack, key, "") or ""
        self._sound_event_path_field.ChangeValue(display_path)

    def _on_sound_pack_selected(self, event):
        idx = self._sound_pack_combo.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._sound_pack_ids):
            return
        self._current_pack_id = self._sound_pack_ids[idx]
        self._load_sound_events_display(self._current_pack_id)

    def _on_import_sound_pack(self, event):
        i18n = self.main_window.i18n
        with wx.DirDialog(
            self, message=i18n.t("select_folder_dialog_title"),
            style=wx.DD_DEFAULT_STYLE,
        ) as dir_dlg:
            if dir_dlg.ShowModal() != wx.ID_OK:
                return
            source_folder = dir_dlg.GetPath()

        ok, err_key, new_pack_id = import_soundpack(
            source_folder, self.main_window.sound_system.sound_dir
        )
        if not ok:
            wx.MessageBox(
                i18n.t(err_key),
                i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR, self,
            )
            return

        self.main_window.refresh_sound_packs()
        self._reload_sound_pack_choices(select_pack_id=new_pack_id)
        wx.MessageBox(
            i18n.t("soundpack_import_success"),
            i18n.t("settings_title"),
            wx.OK | wx.ICON_INFORMATION, self,
        )

    def _update_fields_state(self):
        is_custom = self._custom_api_check.GetValue()
        self._server_field.Enable(is_custom)
        self._ws_server_field.Enable(is_custom)
        self._api_key_field.Enable(is_custom)

    def _update_self_reference_field_state(self):
        is_other = self._self_ref_other_rb.GetValue()
        self._self_ref_custom_field.Enable(is_other)

    def _on_self_reference_toggle(self, event):
        self._update_self_reference_field_state()

    # ── Sound events tab ─────────────────────────────────────────────────────

    def _on_dialog_char_hook(self, event):
        if (event.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER)
                and wx.Window.FindFocus() is getattr(self, "_sound_events_list", None)):
            self._toggle_current_sound_event()
            return  # swallow — do NOT Skip, so it doesn't also fire the OK button
        event.Skip()

    def _on_sound_event_selected(self, event):
        self._update_sound_event_path_display()

    def _on_sound_event_list_key_down(self, event):
        if event.GetKeyCode() in (wx.WXK_SPACE, wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            self._toggle_current_sound_event()
        else:
            event.Skip()

    def _toggle_current_sound_event(self):
        idx = self._sound_events_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(SOUND_EVENTS):
            return
        key = SOUND_EVENTS[idx][0]
        settings_for_pack = self._pack_event_settings.setdefault(self._current_pack_id, {})
        entry = settings_for_pack.setdefault(key, {"enabled": True, "path": ""})
        entry["enabled"] = not entry.get("enabled", True)
        self._sound_events_list.SetString(idx, self._sound_event_label(key, entry["enabled"]))
        self._sound_events_list.SetSelection(idx)

    def _on_sound_event_path_changed(self, event):
        idx = self._sound_events_list.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(SOUND_EVENTS):
            return
        key = SOUND_EVENTS[idx][0]
        settings_for_pack = self._pack_event_settings.setdefault(self._current_pack_id, {})
        entry = settings_for_pack.setdefault(key, {"enabled": True, "path": ""})
        entry["path"] = self._sound_event_path_field.GetValue()

    def _set_all_sound_events(self, value: bool):
        settings_for_pack = self._pack_event_settings.setdefault(self._current_pack_id, {})
        for idx, (key, _default_filename) in enumerate(SOUND_EVENTS):
            entry = settings_for_pack.setdefault(key, {"enabled": True, "path": ""})
            entry["enabled"] = value
            self._sound_events_list.SetString(idx, self._sound_event_label(key, value))

    # ── Alert tones tab ──────────────────────────────────────────────────────

    def _update_alert_custom_field_state(self):
        is_custom_private = self._alert_private_combo.GetSelection() == len(self._alert_choice_keys) - 1
        self._alert_private_custom_label.Show(is_custom_private)
        self._alert_private_custom_field.Show(is_custom_private)

        is_custom_group = self._alert_group_combo.GetSelection() == len(self._alert_choice_keys) - 1
        self._alert_group_custom_label.Show(is_custom_group)
        self._alert_group_custom_field.Show(is_custom_group)

        self._alert_page.Layout()

    def _on_alert_choice_changed(self, event):
        self._update_alert_custom_field_state()
        # Changing the selection invalidates whatever was previewing —
        # stop it and reset that button back to "play" immediately.
        if event.GetEventObject() is self._alert_private_combo:
            self._alert_private_preview.stop()
        else:
            self._alert_group_preview.stop()

    def _resolve_alert_preview_path(self, kind: str) -> str:
        """Resolve whatever the private/group Alert Tones combo currently
        has selected to an absolute path, for the preview buttons."""
        if kind == "private":
            combo, custom_field = self._alert_private_combo, self._alert_private_custom_field
        else:
            combo, custom_field = self._alert_group_combo, self._alert_group_custom_field
        idx = combo.GetSelection()
        if idx == wx.NOT_FOUND or idx >= len(self._alert_choice_keys):
            return ""
        choice = self._alert_choice_keys[idx]
        active_pack = self.main_window.get_active_sound_pack()
        default_pack = self.main_window._default_sound_pack
        return resolve_alert_tone_path(active_pack, default_pack, choice, custom_field.GetValue().strip())

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

        # Storage: media download day/size limits — 0 is the documented
        # "unlimited" sentinel, so only negative or non-integer values are
        # rejected.
        max_days_str = self._media_max_days_field.GetValue().strip()
        try:
            max_days = int(max_days_str)
            if max_days < 0:
                raise ValueError
        except ValueError:
            self._notebook.SetSelection(7)
            wx.MessageBox(
                self.main_window.i18n.t("invalid_media_max_days"),
                self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._media_max_days_field.SetFocus()
            return False

        max_mb_str = self._media_max_mb_field.GetValue().strip()
        try:
            max_mb = int(max_mb_str)
            if max_mb < 0:
                raise ValueError
        except ValueError:
            self._notebook.SetSelection(7)
            wx.MessageBox(
                self.main_window.i18n.t("invalid_media_max_mb"),
                self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            self._media_max_mb_field.SetFocus()
            return False

        # Sound events: an ENABLED event's override path, if the user set one,
        # must point to a real file. An empty override is always fine — it
        # just means "use the sound pack's own file for this event" (with a
        # further fallback to the default pack), never an error. A disabled
        # event's path is never used, so it's not worth blocking on either.
        # (Enabled state is already live in _pack_event_settings — every
        # toggle writes straight there, there's nothing left to flush.)
        pack_settings = self._pack_event_settings.get(self._current_pack_id, {})
        for idx, (key, _) in enumerate(SOUND_EVENTS):
            cfg = pack_settings.get(key) or {}
            if not cfg.get("enabled", True):
                continue
            override = (cfg.get("path") or "").strip()
            if override and not os.path.isfile(override):
                self._notebook.SetSelection(5)
                self._sound_events_list.SetSelection(idx)
                self._update_sound_event_path_display()
                self._sound_event_path_field.SetFocus()
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_sound_path"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return False

        # Alert tones: a "Custom" choice must point to a real file.
        last_idx = len(self._alert_choice_keys) - 1
        if self._alert_private_combo.GetSelection() == last_idx:
            path = self._alert_private_custom_field.GetValue().strip()
            if not path or not os.path.isfile(path):
                self._notebook.SetSelection(6)
                self._alert_private_custom_field.SetFocus()
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_sound_path"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return False
        if self._alert_group_combo.GetSelection() == last_idx:
            path = self._alert_group_custom_field.GetValue().strip()
            if not path or not os.path.isfile(path):
                self._notebook.SetSelection(6)
                self._alert_group_custom_field.SetFocus()
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_sound_path"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
                return False

        # Audio devices: a non-default selection must actually open. Checked
        # last, since output switching happens for real right here (it's the
        # only way to test it) — on failure the device is left on the system
        # default by apply_output_device() itself, so nothing needs undoing,
        # but there's no reason to touch the live output device at all if an
        # earlier, cheaper check is going to fail this validation anyway.
        # Input is a plain open+close test — actually starting to record here
        # would be pointless.
        # Always call apply_output_device() — even when "default" (index 0)
        # is selected — so switching back to the default actually happens
        # live. Guarding this behind "only if a specific device is picked"
        # used to mean picking "default" here only ever updated settings.json
        # (correctly retried on next launch) without ever telling BASS to
        # switch away from whatever non-default device was still active.
        output_sel = self._audio_output_combo.GetSelection()
        output_name = self._audio_output_device_names[output_sel - 1] if output_sel > 0 else ""
        if not self.main_window.sound_system.apply_output_device(output_name):
            self._notebook.SetSelection(4)
            self._audio_output_combo.SetFocus()
            wx.MessageBox(
                self.main_window.i18n.t("invalid_audio_output_device"),
                self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return False

        input_sel = self._audio_input_combo.GetSelection()
        if input_sel > 0:
            input_name = self._audio_input_device_names[input_sel - 1]
            input_index = None
            for idx, name in enumerate_input_devices():
                if name == input_name:
                    input_index = idx
                    break
            if input_index is None or not test_input_device(input_index):
                self._notebook.SetSelection(4)
                self._audio_input_combo.SetFocus()
                wx.MessageBox(
                    self.main_window.i18n.t("invalid_audio_input_device"),
                    self.main_window.i18n.t("error").format(app_name=self.main_window.app_name),
                    wx.OK | wx.ICON_ERROR,
                    self,
                )
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

        # UI: messages list control type (ListCtrl vs ListBox) — takes effect
        # after restart since the conversation panel control is built once at
        # startup and switching its underlying wx control type at runtime would
        # require rebuilding the whole conversation panel.
        new_message_list_mode = (
            "listbox" if self._msg_list_mode_listbox_rb.GetValue() else "classic"
        )
        old_message_list_mode = self.main_window.settings.get("user_interface", {}).get(
            "message_list_mode", "classic"
        )
        if old_message_list_mode == "dataview":
            old_message_list_mode = "listbox"
        self.main_window.settings.setdefault("user_interface", {})[
            "message_list_mode"
        ] = new_message_list_mode
        if new_message_list_mode != old_message_list_mode:
            self._restart_required = True

        # UI: how to refer to the user's own messages/replies in the messages list
        if self._self_ref_voce_rb.GetValue():
            self_reference_mode = "voce"
        elif self._self_ref_other_rb.GetValue():
            self_reference_mode = "custom"
        else:
            self_reference_mode = "eu"
        self_reference_custom_word = self._self_ref_custom_field.GetValue().strip()
        old_ui_settings = self.main_window.settings.get("user_interface", {})
        self_reference_changed = (
            old_ui_settings.get("self_reference_mode", "eu") != self_reference_mode
            or old_ui_settings.get("self_reference_custom_word", "") != self_reference_custom_word
        )
        self.main_window.settings.setdefault("user_interface", {})[
            "self_reference_mode"
        ] = self_reference_mode
        self.main_window.settings.setdefault("user_interface", {})[
            "self_reference_custom_word"
        ] = self_reference_custom_word

        # Spoken content: typing/recording announcements
        self.main_window.settings.setdefault("speech_content", {})[
            "announce_typing"
        ] = self._announce_typing_check.GetValue()
        self.main_window.settings.setdefault("speech_content", {})[
            "announce_recording"
        ] = self._announce_recording_check.GetValue()

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

        # Audio devices — output was already switched live during _validate()
        # (that's the only way to test it); here we just persist the choice
        # and, for input, tell voice-message recording which device to use
        # from now on.
        output_sel = self._audio_output_combo.GetSelection()
        output_name = self._audio_output_device_names[output_sel - 1] if output_sel > 0 else ""
        self.main_window.settings.setdefault("audio_devices", {})["output_device_name"] = output_name

        input_sel = self._audio_input_combo.GetSelection()
        input_name = self._audio_input_device_names[input_sel - 1] if input_sel > 0 else ""
        self.main_window.settings.setdefault("audio_devices", {})["input_device_name"] = input_name
        self.main_window.effective_input_device_name = input_name

        self.main_window.settings.setdefault("general", {})["noise_reduction_enabled"] = (
            self._noise_reduction_check.GetValue()
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

        # Sound events / active pack — enabled/path edits are already live in
        # _pack_event_settings (every toggle/keystroke writes straight there).
        self.main_window.settings["sound_events"] = self._pack_event_settings
        self.main_window.settings["active_sound_pack"] = self._current_pack_id

        # Alert tones
        private_choice = self._alert_choice_keys[self._alert_private_combo.GetSelection()]
        group_choice = self._alert_choice_keys[self._alert_group_combo.GetSelection()]
        self.main_window.settings["alert_tones"] = {
            "private": private_choice,
            "private_custom_path": self._alert_private_custom_field.GetValue().strip(),
            "group": group_choice,
            "group_custom_path": self._alert_group_custom_field.GetValue().strip(),
        }
        # Per-conversation overrides use resolved paths cached by object identity
        # (see play_background_notification_sound) — a changed alert-tone
        # default should not keep serving a stale cached Sound for "default".
        cache = getattr(self.main_window, "_notification_sound_cache", None)
        if cache is not None:
            cache.clear()

        # Storage
        self.main_window.settings.setdefault("storage", {}).update({
            "auto_download_media": self._auto_download_media_check.GetValue(),
            "media_max_days": int(self._media_max_days_field.GetValue().strip()),
            "media_max_mb": int(self._media_max_mb_field.GetValue().strip()),
        })

        # Persist and propagate
        self.main_window.save_settings()
        # Reload sound objects so per-event enabled/path changes (and the new
        # alert-tone defaults) take effect immediately, without a restart.
        self.main_window.load_sounds()

        # Invalidate cache and re-read the new language
        from core.i18n import I18n
        I18n.invalidate_cache()
        self.main_window.i18n.get_language()

        # Refresh all visible labels in the main window
        self.main_window.apply_language_changes()

        # Re-render the open conversation's message list, and the conversation
        # list's last-message previews (which also embed the self-reference
        # word for chats whose last message is our own), so a self-reference
        # change (e.g. "Eu" -> "Você") takes effect immediately instead of
        # only on the next restart.
        if self_reference_changed:
            cp = getattr(self.main_window, "conversations_panel", None)
            if cp is not None and getattr(cp, "conversation", None) is not None:
                cp.populate_messages(preserve_focus=True)
            # add_chats_to_ui() skips its rebuild when its content fingerprint
            # (jid/name/unread/last-record-id) is unchanged from the last run —
            # which it is here, since only the self-reference word changed, not
            # any of the fingerprinted fields. Clear it so the previews (which
            # embed that word for chats whose last message is our own) are
            # actually regenerated instead of being served from the stale list.
            # Call add_chats_to_ui() directly rather than set_chats(): the
            # underlying messages/order/names haven't changed (only the
            # pronoun used in previews for our own last messages), so there's
            # no need to pay for set_chats()'s full lid-cache rebuild + name
            # resolution + re-sort over every chat (which freezes the UI for
            # a few seconds) just to refresh some preview strings. This also
            # lets add_chats_to_ui()'s SetItem fast path kick in, updating
            # row text in place instead of tearing down and rebuilding the
            # whole list control.
            self.main_window._chats_ui_fp = None
            self.main_window.add_chats_to_ui()

        return True

    def _refresh_dialog_labels(self):
        """Update this dialog's own title and notebook tab captions after a language change."""
        i18n = self.main_window.i18n
        self.SetTitle(i18n.t("settings_title"))
        self._notebook.SetPageText(0, i18n.t("tab_general"))
        self._notebook.SetPageText(1, i18n.t("tab_ui"))
        self._notebook.SetPageText(2, i18n.t("tab_speech_content"))
        self._notebook.SetPageText(3, i18n.t("tab_connection"))
        self._notebook.SetPageText(4, i18n.t("tab_audio_devices"))
        self._notebook.SetPageText(5, i18n.t("tab_sound_events"))
        self._notebook.SetPageText(6, i18n.t("tab_alert_tones"))
        self._notebook.SetPageText(7, i18n.t("tab_storage"))
        self._notebook.SetPageText(8, i18n.t("tab_audio_playback"))
        self._audio_input_label.SetLabel(i18n.t("audio_input_device_label"))
        self._audio_output_label.SetLabel(i18n.t("audio_output_device_label"))
        self._reload_audio_device_choices()
        self._noise_reduction_check.SetLabel(i18n.t("noise_reduction_label"))
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
        self._msg_list_mode_box.SetLabel(i18n.t("ui_message_list_mode_label"))
        self._msg_list_mode_classic_rb.SetLabel(i18n.t("ui_message_list_mode_classic"))
        self._msg_list_mode_listbox_rb.SetLabel(i18n.t("ui_message_list_mode_listbox"))
        self._self_ref_box.SetLabel(i18n.t("ui_self_reference_label"))
        self._self_ref_eu_rb.SetLabel(i18n.t("sender_you"))
        self._self_ref_voce_rb.SetLabel(i18n.t("ui_self_reference_voce"))
        self._self_ref_other_rb.SetLabel(i18n.t("ui_self_reference_other"))
        self._self_ref_custom_label.SetLabel(i18n.t("ui_self_reference_custom_label"))
        self._announce_typing_check.SetLabel(i18n.t("speech_announce_typing_label"))
        self._announce_recording_check.SetLabel(i18n.t("speech_announce_recording_label"))
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

        # Sound events tab
        self._sound_pack_label.SetLabel(i18n.t("sound_pack_label"))
        self._import_sound_pack_btn.SetLabel(i18n.t("import_sound_pack_button"))
        packs = self.main_window._sound_packs
        pack_sel = self._sound_pack_combo.GetSelection()
        self._sound_pack_combo.Set([
            i18n.t("sound_pack_default_label") if pid == DEFAULT_PACK_ID else packs[pid]["name"]
            for pid in self._sound_pack_ids
        ])
        self._sound_pack_combo.SetSelection(pack_sel if pack_sel != wx.NOT_FOUND else 0)
        self._sound_events_list_label.SetLabel(i18n.t("sound_events_list_label"))
        self._sound_event_path_label.SetLabel(i18n.t("sound_event_path_label"))
        self._activate_all_btn.SetLabel(i18n.t("activate_all_sounds"))
        self._deactivate_all_btn.SetLabel(i18n.t("deactivate_all_sounds"))
        cur_event_sel = self._sound_events_list.GetSelection()
        settings_for_pack = self._pack_event_settings.get(self._current_pack_id, {})
        self._sound_events_list.Set([
            self._sound_event_label(key, (settings_for_pack.get(key) or {}).get("enabled", True))
            for key, _default_filename in SOUND_EVENTS
        ])
        if cur_event_sel != wx.NOT_FOUND:
            self._sound_events_list.SetSelection(cur_event_sel)

        # Alert tones tab
        self._alert_private_label.SetLabel(i18n.t("alert_tone_private_label"))
        self._alert_group_label.SetLabel(i18n.t("alert_tone_group_label"))
        self._alert_private_custom_label.SetLabel(i18n.t("alert_tone_custom_path_label"))
        self._alert_group_custom_label.SetLabel(i18n.t("alert_tone_custom_path_label"))
        alert_choice_labels = [i18n.t("alert_tone_default")] + [
            i18n.t("alert_tone_item").format(n=n) for n in range(1, ALERT_TONE_COUNT + 1)
        ] + [i18n.t("alert_tone_custom")]
        priv_sel = self._alert_private_combo.GetSelection()
        self._alert_private_combo.Set(alert_choice_labels)
        self._alert_private_combo.SetSelection(priv_sel if priv_sel != wx.NOT_FOUND else 0)
        grp_sel = self._alert_group_combo.GetSelection()
        self._alert_group_combo.Set(alert_choice_labels)
        self._alert_group_combo.SetSelection(grp_sel if grp_sel != wx.NOT_FOUND else 0)

        # Storage tab
        self._auto_download_media_check.SetLabel(i18n.t("auto_download_media_label"))
        self._media_max_days_label.SetLabel(i18n.t("media_max_days_label"))
        self._media_max_mb_label.SetLabel(i18n.t("media_max_mb_label"))
        self._alert_private_preview.refresh_label()
        self._alert_group_preview.refresh_label()

        # Regenerate speed labels — decimal separator may have changed with language
        cur_sel = self._audio_speed_combo.GetSelection()
        self._audio_speed_combo.Clear()
        for s in self._AUDIO_SPEED_STEPS:
            self._audio_speed_combo.Append(self._format_speed(s))
        self._audio_speed_combo.SetSelection(cur_sel if cur_sel != wx.NOT_FOUND else 0)

    # ── Event handlers ───────────────────────────────────────────────────────

    def _stop_alert_previews(self):
        self._alert_private_preview.stop()
        self._alert_group_preview.stop()

    def _on_ok(self, event):
        if self._apply_values():
            self._stop_alert_previews()
            self._maybe_warn_restart_required()
            self.EndModal(wx.ID_OK)

    def _on_cancel(self, event):
        self._stop_alert_previews()
        self.EndModal(wx.ID_CANCEL)

    def _on_apply(self, event):
        if self._apply_values():
            self._refresh_dialog_labels()
            self._maybe_warn_restart_required()

    def _maybe_warn_restart_required(self):
        if self._restart_required:
            self._restart_required = False
            wx.MessageBox(
                self.main_window.i18n.t("restart_required_message"),
                self.main_window.i18n.t("settings_title"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
