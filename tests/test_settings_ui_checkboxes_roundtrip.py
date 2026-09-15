"""Configurações > Interface do usuário, driven through the real dialog: every
plain checkbox opens on the stored value (or the shipped default), and what
the user leaves ticked is what Apply writes — for each one, not just the one
someone remembered to test.

The list of checkboxes is not written out here. It comes from the same parse
tests/test_settings_ui_checkboxes_wiring.py uses, so a checkbox added to the
tab is covered the moment it exists, and that file fails loudly if the parse
stops finding them.

The static file proves the four pieces of wiring name the same key; this one
proves that wiring actually carries the value through wx, which a source
reading cannot see (a control created on the wrong page, a load that runs
before the control exists, a later write in _apply_values() overwriting the
key).

Needs a real wx.App — see tests/test_settings_dialog_apply_button.py's
docstring for why this dialog cannot be exercised against a stub.
"""

import pytest

from core.i18n import I18n
from core.sound_system import DEFAULT_PACK_ID
from core.utils import DEFAULT_SETTINGS
from tests.conftest import hidden_frame
from tests.test_settings_ui_checkboxes_wiring import SECTION, checkbox_keys
from ui.dialogs.settings_dialog import SettingsDialog

# Creates a REAL top-level wx dialog - see the wxgui marker in pytest.ini.
pytestmark = pytest.mark.wxgui

CHECKBOXES = checkbox_keys()


class _FakeSoundSystem:
    def get_output_devices(self):
        return []

    def get_input_devices(self):
        return []

    def apply_output_device(self, name):
        return True

    def apply_effects_device(self, name):
        return True


def _make_frame(settings):
    frame = hidden_frame()
    frame.settings = settings
    frame.app_name = "WinZapp"
    frame.i18n = I18n(frame)
    frame.i18n.get_language()
    frame.wpp_port = 6300
    frame.wpp_custom_api = False
    frame._sound_packs = {DEFAULT_PACK_ID: {"name": "Default", "path": ""}}
    frame._default_sound_pack = {"name": "Default", "path": ""}
    frame.set_global_hotkey = lambda vk, mod: None
    frame.save_settings = lambda: None
    frame.load_sounds = lambda: None
    frame.apply_language_changes = lambda: None
    frame.sound_system = _FakeSoundSystem()
    frame.refresh_sound_packs = lambda: None
    return frame


@pytest.fixture
def make_dialog(wx_app):
    created = []

    def _make(settings=None):
        dlg = SettingsDialog(_make_frame(settings if settings is not None else {}))
        created.append(dlg)
        return dlg

    yield _make
    for dlg in created:
        dlg.Destroy()


def _default(key):
    return bool(DEFAULT_SETTINGS[SECTION][key])


def _opposite_of_defaults():
    return {SECTION: {key: not _default(key) for _, key in CHECKBOXES}}


@pytest.mark.parametrize("attr, key", CHECKBOXES)
def test_an_install_without_the_key_shows_the_shipped_default(make_dialog, attr, key):
    dialog = make_dialog({})

    assert getattr(dialog, attr).GetValue() is _default(key)


@pytest.mark.parametrize("attr, key", CHECKBOXES)
def test_a_stored_value_is_what_the_box_shows(make_dialog, attr, key):
    """Every key set to the opposite of its default at once: a box loading
    from a neighbour's key shows the wrong state here."""
    dialog = make_dialog(_opposite_of_defaults())

    assert getattr(dialog, attr).GetValue() is (not _default(key))


def test_apply_writes_each_box_to_its_own_key(make_dialog):
    dialog = make_dialog({})
    for attr, key in CHECKBOXES:
        getattr(dialog, attr).SetValue(not _default(key))

    assert dialog._apply_values() is True

    stored = dialog.main_window.settings[SECTION]
    wrong = {key: stored.get(key) for _, key in CHECKBOXES if stored.get(key) is not (not _default(key))}
    assert wrong == {}


def test_opening_again_after_apply_keeps_every_choice(make_dialog):
    """The full cycle a user goes through: change, save, reopen. This is the
    path by which "don't show again" is turned back on from Settings."""
    first = make_dialog({})
    for attr, key in CHECKBOXES:
        getattr(first, attr).SetValue(not _default(key))
    assert first._apply_values() is True

    second = make_dialog(first.main_window.settings)

    wrong = [attr for attr, key in CHECKBOXES if getattr(second, attr).GetValue() is _default(key)]
    assert wrong == []


def test_unchanged_boxes_are_saved_as_they_were(make_dialog):
    """Opening Settings and pressing OK must not reset anything.

    The expected values are taken before the dialog opens: the dialog keeps
    the very same settings dict and _apply_values() writes into it, so
    comparing against that dict afterwards would compare it with itself."""
    expected = {key: not _default(key) for _, key in CHECKBOXES}
    dialog = make_dialog(_opposite_of_defaults())

    assert dialog._apply_values() is True

    saved = dialog.main_window.settings[SECTION]
    assert {key: saved[key] for _, key in CHECKBOXES} == expected
