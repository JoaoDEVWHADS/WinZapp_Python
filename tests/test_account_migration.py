"""Tests for client/account_migration.py — journaled legacy->default migration."""

import json
import os

import pytest

import app_paths
import account_migration as mig
from accounts import AccountRegistry


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account(None)
    app_paths.set_allow_legacy_flat(False)
    yield
    app_paths.set_active_account(None)
    app_paths.set_allow_legacy_flat(False)


def _make_legacy(tmp_path, with_token=True):
    """Create a fake flat legacy data/ dir."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    settings = {"general": {"language": "pl"}}
    if with_token:
        settings["privateinfo"] = {"WA_token_protected": "gAAAAABxxxx"}
    (data / "settings.json").write_text(json.dumps(settings))
    (data / "secret.key").write_bytes(b"0" * 44)
    (data / "messages.db").write_bytes(b"SQLite format 3\x00rest")
    (data / "media").mkdir(exist_ok=True)
    (data / "media" / "x.wzmedia").write_bytes(b"media")
    return data


def _gd(tmp_path):
    return str(tmp_path / "data" / "global")


def test_no_legacy_returns_none(tmp_path):
    assert mig.migrate_if_needed(_gd(tmp_path)) is None


def test_migration_creates_paired_default_with_token(tmp_path):
    _make_legacy(tmp_path, with_token=True)
    acc_id = mig.migrate_if_needed(_gd(tmp_path))
    assert acc_id is not None
    reg = AccountRegistry(_gd(tmp_path))
    acc = reg.get(acc_id)
    assert acc["state"] == "paired"
    assert reg.last_foreground() == acc_id
    # data landed under accounts/<id>/
    dest = tmp_path / "data" / "accounts" / acc_id
    assert (dest / "settings.json").is_file()
    assert (dest / "secret.key").is_file()
    assert (dest / "messages.db").is_file()
    assert (dest / "media" / "x.wzmedia").is_file()
    # legacy backed up, not left in place as flat settings.json
    assert not (tmp_path / "data" / "settings.json").exists()


def test_migration_without_token_is_pending(tmp_path):
    _make_legacy(tmp_path, with_token=False)
    acc_id = mig.migrate_if_needed(_gd(tmp_path))
    reg = AccountRegistry(_gd(tmp_path))
    assert reg.get(acc_id)["state"] == "pending"
    assert reg.last_foreground() is None


def test_migration_idempotent(tmp_path):
    _make_legacy(tmp_path)
    first = mig.migrate_if_needed(_gd(tmp_path))
    # second run: registry already has an account -> no-op
    second = mig.migrate_if_needed(_gd(tmp_path))
    assert second is None
    reg = AccountRegistry(_gd(tmp_path))
    assert len(reg.list()) == 1
    assert reg.list()[0]["id"] == first


def test_detects_legacy_by_messages_db_only(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "messages.db").write_bytes(b"SQLite format 3\x00")
    acc_id = mig.migrate_if_needed(_gd(tmp_path))
    assert acc_id is not None  # detected even without settings.json


def test_does_not_migrate_new_layout_dirs(tmp_path):
    """global/ and accounts/ under data/ must never be swept into staging."""
    _make_legacy(tmp_path)
    acc_id = mig.migrate_if_needed(_gd(tmp_path))
    dest = tmp_path / "data" / "accounts" / acc_id
    # the account dir must NOT contain a nested accounts/ or global/
    assert not (dest / "accounts").exists()
    assert not (dest / "global").exists()


def test_migration_splits_global_settings_to_app_json(tmp_path):
    """Global keys (language/updates/connection) land in global/app.json and are
    removed from the migrated account's settings.json (Zad 2.3)."""
    import app_settings
    _make_legacy(tmp_path, with_token=True)
    gd = _gd(tmp_path)
    acc_id = mig.migrate_if_needed(gd)
    app = app_settings.AppSettings(gd)
    assert app.get("language") == "pl"
    # per-account settings.json no longer carries the global 'language'
    sp = tmp_path / "data" / "accounts" / acc_id / "settings.json"
    per = json.loads(sp.read_text())
    assert "language" not in per.get("general", {})
    assert "connection" not in per


def test_resume_after_commit_before_backup(tmp_path):
    """If the registry was committed but backup not done, a rerun completes it
    (journal handled before the accounts-exist no-op)."""
    data = _make_legacy(tmp_path)
    gd = _gd(tmp_path)
    # First full migration
    acc_id = mig.migrate_if_needed(gd)
    # Simulate a leftover journal claiming an incomplete backup step, plus a
    # stray flat settings.json that a crashed run would have left behind.
    (data / "settings.json").write_text("{}")
    journal = os.path.join(gd, "migration.journal")
    with open(journal, "w") as f:
        json.dump({"stage": "committed", "target_id": acc_id}, f)
    # Rerun: journal handled first -> finishes backup, clears journal, no dup.
    mig.migrate_if_needed(gd)
    reg = AccountRegistry(gd)
    assert len(reg.list()) == 1
    assert not os.path.exists(journal)
