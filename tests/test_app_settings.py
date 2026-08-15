"""Tests for client/app_settings.py — global (cross-account) settings split."""

import json
import os

import pytest

import app_settings as aset


def _gd(tmp_path):
    gd = str(tmp_path / "global")
    os.makedirs(gd, exist_ok=True)
    return gd


def test_defaults_when_absent(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    assert s.get("language") == ""
    assert s.get("updates_enabled") is True
    assert s.get("show_tray_icon") is True


def test_set_and_persist(tmp_path):
    gd = _gd(tmp_path)
    s = aset.AppSettings(gd)
    s.set("language", "pl")
    s.set("updates_enabled", False)
    # reload from disk (another instance / process)
    s2 = aset.AppSettings(gd)
    assert s2.get("language") == "pl"
    assert s2.get("updates_enabled") is False


def test_only_global_keys_accepted(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    with pytest.raises(KeyError):
        s.set("notifications_enabled", False)  # per-account, not global
    with pytest.raises(KeyError):
        s.get("audio_default_speed")  # per-account, not global


def test_first_run_flags_are_global(tmp_path):
    """Install-wide one-time setup prompts must be global so a new account never
    re-asks autostart / hotkey / api-type (regression: they were per-account)."""
    gd = _gd(tmp_path)
    s = aset.AppSettings(gd)
    assert s.get("first_run") is True  # default
    s.set("first_run", False)
    s.set("hotkey_first_run_asked", True)
    s.set("api_type_first_run_asked", True)
    s2 = aset.AppSettings(gd)
    assert s2.get("first_run") is False
    assert s2.get("hotkey_first_run_asked") is True
    assert s2.get("api_type_first_run_asked") is True


def test_wpp_port_is_per_account(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    with pytest.raises(KeyError):
        s.set("wpp_port", 6301)


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    gd = _gd(tmp_path)
    open(os.path.join(gd, "app.json"), "w").write("{ broken")
    s = aset.AppSettings(gd)
    assert s.get("language") == ""  # no crash, defaults


def test_split_global_from_legacy():
    legacy = {
        "general": {"language": "pl", "updates_enabled": False, "autostart": True,
                    "show_tray_icon": False, "notifications_enabled": True, "first_run": True},
        "connection": {"wpp_server": "http://127.0.0.1", "wpp_port": 6300},
        "status": {"messages_set_completed": True},
    }
    glob, per = aset.split_legacy_settings(legacy)
    # global keys extracted
    assert glob["language"] == "pl"
    assert glob["updates_enabled"] is False
    assert glob["show_tray_icon"] is False
    assert "wpp_port" not in glob
    # per-account keys retained, global ones removed from per-account general
    assert per["general"]["notifications_enabled"] is True
    assert per["connection"] == {"wpp_port": 6300}
    assert "language" not in per["general"]
    assert "updates_enabled" not in per["general"]
    assert per["status"]["messages_set_completed"] is True


def test_atomic_write_leaves_no_partial(tmp_path):
    gd = _gd(tmp_path)
    s = aset.AppSettings(gd)
    s.set("language", "es")
    # no .tmp left behind
    assert not any(f.endswith(".tmp") for f in os.listdir(gd))
