import json
import os
import sys
import types
from unittest.mock import MagicMock

try:
    import wx
    import wx.adv
except ImportError:
    for _mod in ("wx", "wx.adv"):
        if _mod not in sys.modules:
            mod = types.ModuleType(_mod)
            if "." not in _mod:
                mod.__path__ = []
            sys.modules[_mod] = mod
    class _FakeWxModule(types.ModuleType):
        ACC_OK = 0
        ACC_NOT_IMPLEMENTED = -1
        def __getattr__(self, name):
            if name == "__file__":
                return "<fake_wx>"
            if name == "CallAfter":
                return lambda fn, *a, **k: fn(*a, **k)
            if name.startswith("ID_") or name.startswith("wxID_") or name in ("HORIZONTAL", "VERTICAL", "EXPAND", "ALL"):
                return 1000
            if name in ("Frame", "Panel", "Dialog", "Accessible", "Timer", "App", "Window", "Control", "Button", "StaticBox", "RadioButton", "CheckBox", "TextCtrl", "Choice", "ComboBox", "Notebook", "StaticText", "SpinCtrl"):
                return object
            return MagicMock
    sys.modules["wx"].__class__ = _FakeWxModule
    sys.modules["wx.adv"].__class__ = _FakeWxModule
    wx = sys.modules["wx"]

try:
    import sound_lib
except ImportError:
    for _mod in ("sound_lib", "sound_lib.output", "sound_lib.stream", "sound_lib.main", "sound_lib.effects"):
        if _mod not in sys.modules:
            mod = types.ModuleType(_mod)
            if "." not in _mod:
                mod.__path__ = []
            sys.modules[_mod] = mod
    sys.modules["sound_lib.main"].bass_call = lambda *a, **k: None
    sys.modules["sound_lib.output"].Output = object

from core.utils import DEFAULT_SETTINGS


# Runtime-only sections that must NOT be shipped as defaults, and so are
# excluded from the invariant rather than added to the template to satisfy it.
# "privateinfo" is the token vault's own section (WA_token / WA_token_protected
# live there), and its "paired" key is used as a PRESENCE flag — unpairing does
# `pi.pop("paired", None)` and every read is a truthy `.get("paired")`. Baking
# the key into the template means the backfill re-injects it after every
# unpair; harmless while the value is falsy, wrong the moment anything checks
# `"paired" in pi`.
_RUNTIME_ONLY_SECTIONS = {"privateinfo"}


def test_default_settings_matches_json_structure():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, "client", "data", "settings_default.json")
    with open(json_path, "r", encoding="utf-8") as f:
        json_data = json.load(f)

    assert set(DEFAULT_SETTINGS.keys()) == set(json_data.keys()), (
        f"Top-level keys mismatch: {set(DEFAULT_SETTINGS.keys()) ^ set(json_data.keys())}"
    )
    assert not (_RUNTIME_ONLY_SECTIONS & set(json_data.keys())), (
        f"runtime-only state shipped as a default: "
        f"{_RUNTIME_ONLY_SECTIONS & set(json_data.keys())}"
    )

    for section, val in DEFAULT_SETTINGS.items():
        if isinstance(val, dict):
            assert isinstance(json_data[section], dict), f"Section {section} must be a dict"
            for k, v in json_data[section].items():
                assert k in val, f"Key {k} in section {section} missing from DEFAULT_SETTINGS"
                assert val[k] == v, (
                    f"Default value mismatch for {section}.{k}: {val[k]!r} != {v!r}"
                )


def test_recreation_when_settings_file_deleted(tmp_path, monkeypatch):
    from ui.dialogs.settings_dialog import ensure_default_settings_file
    fake_settings_file = str(tmp_path / "settings.json")
    fake_default_file = str(tmp_path / "data" / "settings_default.json")

    monkeypatch.setattr("app_paths.data_path", lambda name: fake_settings_file)
    monkeypatch.setattr("app_paths.resource_path", lambda *parts: fake_default_file)

    ensure_default_settings_file()
    assert os.path.isfile(fake_settings_file)
    with open(fake_settings_file, "r", encoding="utf-8") as f:
        recreated = json.load(f)

    assert set(recreated.keys()) == set(DEFAULT_SETTINGS.keys())
    for section, val in DEFAULT_SETTINGS.items():
        if isinstance(val, dict):
            for k in val:
                assert recreated[section][k] == val[k]
