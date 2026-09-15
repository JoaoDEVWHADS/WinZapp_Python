"""Configurações, every non-checkbox control, driven through the real dialog:
set a value that is not the default, Apply, check what was saved, open the
dialog again on that settings dict and check the control shows it.

Checkboxes have their own round trip (tests/test_settings_checkboxes_roundtrip.py).
The keys every scenario here covers are read by
tests/test_settings_dialog_wiring.py, which fails when a control saves a key no
scenario drives — so a new control cannot land untested.

Importing this module constructs nothing; only the tests below build a dialog.

Needs a real wx.App — see tests/test_settings_dialog_apply_button.py's
docstring for why this dialog cannot be exercised against a stub.
"""

import os

import pytest

from core import save_location
from core.spell_checker import SPELL_CHECK_MODES
from core.utils import GROUP_MEDIA_TYPES, AUTO_DOWNLOAD_MEDIA_TYPES

# Creates a REAL top-level wx dialog - see the wxgui marker in pytest.ini.
pytestmark = pytest.mark.wxgui


def _write(path):
    with open(path, "wb") as f:
        f.write(b"RIFF")
    return str(path)


# Each scenario: the keys it saves with their expected values (a callable taking
# tmp_path when the value depends on it), how to set the controls, and how to
# tell the reopened dialog shows it. Every function receives (dialog, tmp_path).
SCENARIOS = {
    "language": dict(
        saves={("general", "language"): "en-US"},
        set=lambda d, t: d._lang_combo.SetSelection(d._lang_codes.index("en-US")),
        shows=lambda d, t: d._lang_codes[d._lang_combo.GetSelection()] == "en-US",
    ),
    "spell_check_mode": dict(
        saves={("general", "spell_check_mode"): "off"},
        set=lambda d, t: d._spell_check_radio.SetSelection(SPELL_CHECK_MODES.index("off")),
        shows=lambda d, t: SPELL_CHECK_MODES[d._spell_check_radio.GetSelection()] == "off",
    ),
    "search_normalization": dict(
        saves={("general", "search_normalization"): "nfkd"},
        set=lambda d, t: d._search_norm_radio.SetSelection(2),
        shows=lambda d, t: d._search_norm_radio.GetSelection() == 2,
    ),
    "switch_behavior": dict(
        saves={("general", "switch_behavior"): "keep_open"},
        set=lambda d, t: d._switch_behavior_keep_open_rb.SetValue(True),
        shows=lambda d, t: d._switch_behavior_keep_open_rb.GetValue(),
    ),
    "global_hotkey": dict(
        saves={("general", "global_hotkey"): {"vk": 0x4B, "mod": 3}},
        set=lambda d, t: (setattr(d._hotkey_field, "_vk", 0x4B), setattr(d._hotkey_field, "_mod", 3)),
        shows=lambda d, t: (d._hotkey_field._vk, d._hotkey_field._mod) == (0x4B, 3),
    ),
    "messages_page_size": dict(
        saves={("user_interface", "messages_page_size"): 321},
        set=lambda d, t: d._messages_page_size_field.SetValue("321"),
        shows=lambda d, t: d._messages_page_size_field.GetValue() == "321",
    ),
    "page_jump_size": dict(
        saves={("user_interface", "page_jump_size"): 7, ("user_interface", "page_up_down_step"): 7},
        set=lambda d, t: d._page_jump_size_field.SetValue("7"),
        shows=lambda d, t: d._page_jump_size_field.GetValue() == "7",
    ),
    "focus_on_open": dict(
        saves={("user_interface", "focus_on_open"): "unread_or_last"},
        set=lambda d, t: d._focus_unread_or_last_rb.SetValue(True),
        shows=lambda d, t: d._focus_unread_or_last_rb.GetValue(),
    ),
    "voice_record_focus": dict(
        saves={("user_interface", "voice_record_focus"): "discard"},
        set=lambda d, t: d._voice_focus_discard_rb.SetValue(True),
        shows=lambda d, t: d._voice_focus_discard_rb.GetValue(),
    ),
    "message_list_mode": dict(
        saves={("user_interface", "message_list_mode"): "listbox"},
        set=lambda d, t: d._msg_list_mode_listbox_rb.SetValue(True),
        shows=lambda d, t: d._msg_list_mode_listbox_rb.GetValue(),
    ),
    "selected_announcement_position": dict(
        saves={("user_interface", "selected_announcement_position"): "start"},
        set=lambda d, t: d._selected_announce_start_rb.SetValue(True),
        shows=lambda d, t: d._selected_announce_start_rb.GetValue(),
    ),
    "voice_message_mode": dict(
        saves={("user_interface", "voice_message_mode"): "audio"},
        set=lambda d, t: d._voice_msg_mode_audio_rb.SetValue(True),
        shows=lambda d, t: d._voice_msg_mode_audio_rb.GetValue(),
    ),
    "self_reference": dict(
        saves={("user_interface", "self_reference_mode"): "custom",
               ("user_interface", "self_reference_custom_word"): "Tu"},
        set=lambda d, t: (d._self_ref_other_rb.SetValue(True), d._self_ref_custom_field.SetValue("Tu")),
        shows=lambda d, t: d._self_ref_other_rb.GetValue() and d._self_ref_custom_field.GetValue() == "Tu",
    ),
    "group_media_default_types": dict(
        saves={("user_interface", "group_media_default_types"): list(GROUP_MEDIA_TYPES[1:])},
        set=lambda d, t: d._group_media_types_list.CheckItem(0, False),
        shows=lambda d, t: d._selected_group_media_types() == list(GROUP_MEDIA_TYPES[1:]),
    ),
    "connection_fields": dict(
        saves={("connection", "wpp_server"): "http://10.0.0.5",
               ("connection", "wpp_ws_server"): "ws://10.0.0.5",
               ("connection", "wpp_port"): 6400,
               ("connection", "wpp_api_key"): "chave-de-teste"},
        set=lambda d, t: (d._server_field.SetValue("http://10.0.0.5"),
                          d._ws_server_field.SetValue("ws://10.0.0.5"),
                          d._port_field.SetValue("6400"),
                          d._api_key_field.SetValue("chave-de-teste")),
        shows=lambda d, t: (d._server_field.GetValue(), d._ws_server_field.GetValue(),
                            d._port_field.GetValue(), d._api_key_field.GetValue())
        == ("http://10.0.0.5", "ws://10.0.0.5", "6400", "chave-de-teste"),
    ),
    "storage_limits": dict(
        saves={("storage", "media_max_days"): 12, ("storage", "media_max_mb"): 34},
        set=lambda d, t: (d._media_max_days_field.SetValue("12"), d._media_max_mb_field.SetValue("34")),
        shows=lambda d, t: (d._media_max_days_field.GetValue(), d._media_max_mb_field.GetValue()) == ("12", "34"),
    ),
    "auto_download_media_types": dict(
        saves={("storage", "auto_download_media_types"): list(AUTO_DOWNLOAD_MEDIA_TYPES[1:])},
        set=lambda d, t: d._auto_download_types_list.CheckItem(0, False),
        shows=lambda d, t: d._selected_auto_download_types() == list(AUTO_DOWNLOAD_MEDIA_TYPES[1:]),
    ),
    "save_folder_downloads": dict(
        saves={("files", "save_dialog_folder_mode"): save_location.MODE_DOWNLOADS},
        set=lambda d, t: d._save_folder_radio.SetSelection(save_location.mode_index(save_location.MODE_DOWNLOADS)),
        shows=lambda d, t: d._save_folder_radio.GetSelection() == save_location.mode_index(save_location.MODE_DOWNLOADS),
    ),
    "save_folder_custom": dict(
        saves={("files", "save_dialog_folder_mode"): save_location.MODE_CUSTOM,
               ("files", "save_dialog_custom_folder"): lambda t: str(t)},
        set=lambda d, t: (d._save_folder_radio.SetSelection(save_location.mode_index(save_location.MODE_CUSTOM)),
                          d._save_folder_custom_field.SetValue(str(t))),
        shows=lambda d, t: d._save_folder_custom_field.GetValue() == str(t),
    ),
    "audio_default_speed": dict(
        saves={("audio_playback", "audio_default_speed"): 2.0},
        set=lambda d, t: d._audio_speed_combo.SetSelection(d._AUDIO_SPEED_STEPS.index(2.0)),
        shows=lambda d, t: d._audio_speed_combo.GetSelection() == d._AUDIO_SPEED_STEPS.index(2.0),
    ),
    "alert_tones": dict(
        saves={("alert_tones", "private"): "custom",
               ("alert_tones", "private_custom_path"): lambda t: os.path.join(str(t), "private.wav"),
               ("alert_tones", "group"): "custom",
               ("alert_tones", "group_custom_path"): lambda t: os.path.join(str(t), "group.wav")},
        set=lambda d, t: (d._set_alert_combo(d._alert_private_combo, "custom"),
                          d._alert_private_custom_field.SetValue(_write(t / "private.wav")),
                          d._set_alert_combo(d._alert_group_combo, "custom"),
                          d._alert_group_custom_field.SetValue(_write(t / "group.wav"))),
        shows=lambda d, t: d._selected_alert_key(d._alert_private_combo) == "custom"
        and d._selected_alert_key(d._alert_group_combo) == "custom"
        and d._alert_private_custom_field.GetValue().endswith("private.wav")
        and d._alert_group_custom_field.GetValue().endswith("group.wav"),
    ),
    "profile_backup_intervals": dict(
        saves={("profile_backup", "close_snapshot_min_hours"): 6,
               ("profile_backup", "live_snapshot_interval_hours"): 3},
        set=lambda d, t: (d._close_snapshot_hours_field.SetValue("6"),
                          d._live_snapshot_check.SetValue(True),
                          d._update_live_snapshot_fields(),
                          d._live_snapshot_hours_field.SetValue("3")),
        shows=lambda d, t: (d._close_snapshot_hours_field.GetValue(),
                            d._live_snapshot_hours_field.GetValue()) == ("6", "3")
        and d._live_snapshot_hours_field.IsShown(),
    ),
}

#: Every (section, key) some scenario saves — read by the static wiring test.
ROUNDTRIP_KEYS = frozenset(pair for scenario in SCENARIOS.values() for pair in scenario["saves"])

#: Scenarios left out of the combined tests because another scenario sets the
#: same control: key is the one left out, value the one that stays in.
_EXCLUSIVE_WITH = {"save_folder_downloads": "save_folder_custom"}


def _expected(scenario, tmp_path):
    return {pair: (value(tmp_path) if callable(value) else value) for pair, value in scenario["saves"].items()}


def _stored(settings, pair):
    section, key = pair
    return settings.get(section, {}).get(key)


def _make_frame(settings):
    from core.i18n import I18n
    from core.sound_system import DEFAULT_PACK_ID
    from tests.conftest import hidden_frame

    class _FakeSoundSystem:
        def get_output_devices(self):
            return []

        def get_input_devices(self):
            return []

        def apply_output_device(self, name):
            return True

        def apply_effects_device(self, name):
            return True

    frame = hidden_frame()
    frame.settings = settings
    frame.app_name = "WinZapp"
    frame.i18n = I18n(frame)
    frame.i18n.get_language()
    frame.wpp_port = settings.get("connection", {}).get("wpp_port", 6300)
    frame.wpp_custom_api = False
    frame._sound_packs = {DEFAULT_PACK_ID: {"name": "Default", "path": ""}}
    frame._default_sound_pack = {"name": "Default", "path": ""}

    def set_global_hotkey(vk, mod):
        # Same persistence as MainWindow.set_global_hotkey(), minus registering it.
        general = frame.settings.setdefault("general", {})
        if vk:
            general["global_hotkey"] = {"vk": vk, "mod": mod}
        else:
            general.pop("global_hotkey", None)

    frame.set_global_hotkey = set_global_hotkey
    frame.save_settings = lambda: None
    frame.load_sounds = lambda: None
    frame.apply_language_changes = lambda: None
    frame.sound_system = _FakeSoundSystem()
    frame.refresh_sound_packs = lambda: None
    frame.get_active_sound_pack = lambda: frame._default_sound_pack
    frame.tray_icon = None
    frame._init_tray = lambda: None
    # Changing self-reference or the voice-message mode makes _apply_values()
    # rebuild the chat list through the main window.
    frame.add_chats_to_ui = lambda: None
    return frame


@pytest.fixture
def make_dialog(wx_app):
    from ui.dialogs.settings_dialog import SettingsDialog

    created = []

    def _make(settings=None):
        dlg = SettingsDialog(_make_frame(settings if settings is not None else {}))
        created.append(dlg)
        return dlg

    yield _make
    for dlg in created:
        dlg.Destroy()


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_apply_saves_it_and_reopening_shows_it(make_dialog, tmp_path, name):
    scenario = SCENARIOS[name]
    expected = _expected(scenario, tmp_path)
    first = make_dialog({})
    scenario["set"](first, tmp_path)

    assert first._apply_values() is True

    settings = first.main_window.settings
    wrong = {f"{s}.{k}": _stored(settings, (s, k)) for (s, k), v in expected.items() if _stored(settings, (s, k)) != v}
    assert wrong == {}

    second = make_dialog(settings)
    assert scenario["shows"](second, tmp_path), f"{name}: reopened dialog does not show the saved value"


def _combined(tmp_path):
    names = [n for n in sorted(SCENARIOS) if n not in _EXCLUSIVE_WITH]
    return names, {pair: v for n in names for pair, v in _expected(SCENARIOS[n], tmp_path).items()}


def test_every_scenario_applied_together(make_dialog, tmp_path):
    """One Apply with every control changed: a later write in _apply_values()
    overwriting an earlier key only shows up when they are changed together."""
    names, expected = _combined(tmp_path)
    dialog = make_dialog({})
    for name in names:
        SCENARIOS[name]["set"](dialog, tmp_path)

    assert dialog._apply_values() is True

    settings = dialog.main_window.settings
    wrong = {f"{s}.{k}": _stored(settings, (s, k)) for (s, k), v in expected.items() if _stored(settings, (s, k)) != v}
    assert wrong == {}


def _live_backup_options(dialog):
    return (dialog._live_snapshot_hours_label, dialog._live_snapshot_hours_field,
            dialog._live_snapshot_confirm_check)


def test_the_live_backup_options_follow_their_checkbox(make_dialog):
    """The interval and the confirmation appear only while "back up with
    WinZapp open" is ticked — both when the user ticks it and when the dialog
    opens on a saved "on"."""
    import wx

    dialog = make_dialog({})
    assert not any(c.IsShown() for c in _live_backup_options(dialog))

    check = dialog._live_snapshot_check
    check.SetValue(True)
    event = wx.CommandEvent(wx.wxEVT_CHECKBOX, check.GetId())
    event.SetEventObject(check)
    event.SetInt(1)
    check.GetEventHandler().ProcessEvent(event)
    assert all(c.IsShown() for c in _live_backup_options(dialog))

    check.SetValue(False)
    event.SetInt(0)
    check.GetEventHandler().ProcessEvent(event)
    assert not any(c.IsShown() for c in _live_backup_options(dialog))

    reopened = make_dialog({"profile_backup": {"live_snapshot_enabled": True}})
    assert all(c.IsShown() for c in _live_backup_options(reopened))


def test_a_hidden_unusable_interval_keeps_the_stored_one(make_dialog):
    """While the option is off its field is hidden and not validated: garbage
    left there must neither fail Apply nor overwrite the saved interval."""
    dialog = make_dialog({"profile_backup": {"live_snapshot_interval_hours": 5}})
    dialog._live_snapshot_hours_field.SetValue("abc")

    assert dialog._apply_values() is True
    assert dialog.main_window.settings["profile_backup"]["live_snapshot_interval_hours"] == 5


def test_ok_without_changes_resets_nothing(make_dialog, tmp_path):
    """Open on a settings dict holding every non-default value, Apply without
    touching anything: every value must survive. Expected values are computed
    before the dialog opens, since the dialog writes into that very dict."""
    names, expected = _combined(tmp_path)
    seeded = make_dialog({})
    for name in names:
        SCENARIOS[name]["set"](seeded, tmp_path)
    assert seeded._apply_values() is True

    reopened = make_dialog(seeded.main_window.settings)
    assert reopened._apply_values() is True

    settings = reopened.main_window.settings
    wrong = {f"{s}.{k}": _stored(settings, (s, k)) for (s, k), v in expected.items() if _stored(settings, (s, k)) != v}
    assert wrong == {}
