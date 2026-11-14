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


def test_update_writes_what_the_change_returns(tmp_path):
    gd = _gd(tmp_path)
    s = aset.AppSettings(gd)
    seen = []
    written = s.update("transcription_external_models",
                       lambda current: seen.append(current) or current + [{"id": "a"}])
    assert seen == [[]]  # the default, when nothing is stored
    assert written == [{"id": "a"}]
    assert aset.AppSettings(gd).get("transcription_external_models") == [{"id": "a"}]


def test_update_refuses_a_per_account_key(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    with pytest.raises(KeyError):
        s.update("notifications_enabled", lambda current: current)


def test_update_is_one_step_so_two_writers_both_land(tmp_path):
    """The reason update() exists: get() then set() takes the lock twice, and
    two account processes appending to one list in that gap each write back
    their own addition over the other's. The change function sleeps to hold
    the gap open; each writer uses its own AppSettings, as two processes do."""
    import threading
    import time

    gd = _gd(tmp_path)

    def append(tag):
        def change(current):
            time.sleep(0.05)
            return current + [tag]
        aset.AppSettings(gd).update("transcription_external_models", change)

    threads = [threading.Thread(target=append, args=(f"t{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    stored = aset.AppSettings(gd).get("transcription_external_models")
    assert sorted(stored) == ["t0", "t1", "t2", "t3"]


def test_the_default_list_is_handed_out_as_a_copy(tmp_path):
    """get(), update() and all() each hand a caller the default when nothing
    is stored; if that were _DEFAULTS' own list, appending to it would change
    the default for every later reader in the process."""
    s = aset.AppSettings(_gd(tmp_path))
    s.get("transcription_external_models").append("leaked by get")
    s.all()["transcription_external_models"].append("leaked by all")
    s.update("transcription_external_models",
             lambda current: current.append("leaked by update") or [])
    assert aset._DEFAULTS["transcription_external_models"] == []
    assert s.get("transcription_external_models") == []


def test_the_external_models_list_is_never_mirrored_per_account():
    """_GENERAL_GLOBAL/_CONNECTION_GLOBAL keys are copied into each account's
    settings and written back whole by _persist_global_settings() when that
    copy differs from the account's snapshot, the later write winning. A list
    two accounts add to cannot go that way: each would write back its own list,
    and the later one would drop the other's addition. It is read and written
    only through AppSettings.update()."""
    assert "transcription_external_models" not in aset._GENERAL_GLOBAL
    assert "transcription_external_models" not in aset._CONNECTION_GLOBAL


def test_get_strict_reads_an_absent_file_as_the_defaults(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    assert s.get_strict("transcription_external_models") == []


def test_get_strict_reads_what_is_stored(tmp_path):
    s = aset.AppSettings(_gd(tmp_path))
    s.set("transcription_external_models", [{"id": "r1"}])
    assert s.get_strict("transcription_external_models") == [{"id": "r1"}]


@pytest.mark.parametrize("content", ["{ broken", "[1, 2]"])
def test_get_strict_says_so_when_the_file_is_there_and_unreadable(tmp_path, content):
    """get() reads it as the defaults; a caller acting on what is absent
    from a list must be able to tell that from "nothing stored"."""
    gd = _gd(tmp_path)
    with open(os.path.join(gd, "app.json"), "w", encoding="utf-8") as f:
        f.write(content)
    s = aset.AppSettings(gd)
    assert s.get("transcription_external_models") == []
    with pytest.raises(ValueError):
        s.get_strict("transcription_external_models")


def test_get_strict_refuses_a_per_account_key(tmp_path):
    with pytest.raises(KeyError):
        aset.AppSettings(_gd(tmp_path)).get_strict("audio_default_speed")
