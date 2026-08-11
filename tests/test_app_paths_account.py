"""Tests for per-account / global path scoping in client/app_paths.py."""

import os

import pytest

import app_paths


@pytest.fixture(autouse=True)
def _reset_account():
    """Ensure account state doesn't leak between tests."""
    app_paths.set_active_account(None)
    app_paths._allow_legacy_flat = False
    yield
    app_paths.set_active_account(None)
    app_paths._allow_legacy_flat = False


def test_no_account_raises(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account(None)
    with pytest.raises(RuntimeError):
        app_paths.data_path("settings.json")


def test_legacy_flat_opt_in(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account(None)
    app_paths.set_allow_legacy_flat(True)
    p = app_paths.data_path("settings.json")
    assert os.path.normpath(p) == os.path.normpath(
        str(tmp_path / "data" / "settings.json")
    )


def test_account_scoped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account("a" * 32)
    p = app_paths.data_path("settings.json")
    assert os.path.normpath(p) == os.path.normpath(
        str(tmp_path / "data" / "accounts" / ("a" * 32) / "settings.json")
    )


def test_log_path_account_scoped(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account("b" * 32)
    p = app_paths.log_path("log.log")
    assert os.path.normpath(p) == os.path.normpath(
        str(tmp_path / "data" / "accounts" / ("b" * 32) / "logs" / "log.log")
    )


def test_global_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert os.path.normpath(app_paths.global_dir()) == os.path.normpath(
        str(tmp_path / "data" / "global")
    )


def test_accounts_root(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert os.path.normpath(app_paths.accounts_root()) == os.path.normpath(
        str(tmp_path / "data" / "accounts")
    )


def test_bootstrap_log_path_is_global(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    app_paths.set_active_account(None)
    # bootstrap log must not require an active account
    p = app_paths.bootstrap_log_path()
    assert os.path.normpath(p) == os.path.normpath(
        str(tmp_path / "data" / "global" / "bootstrap.log")
    )


def test_active_account_roundtrip():
    app_paths.set_active_account("c" * 32)
    assert app_paths.active_account_id() == "c" * 32
