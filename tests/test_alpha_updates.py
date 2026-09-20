"""Tests for the current WinZapp release updater.

The updater now follows GitHub's single /releases/latest endpoint.  Alpha
channel selection used to live here, but that API was removed from
client/updater.py; these tests cover the behavior the current implementation
actually exposes instead of pinning deleted private helpers.
"""

from types import SimpleNamespace

import pytest

import updater


def _assets(*names):
    return [
        {"name": name, "browser_download_url": f"https://example.invalid/{name}"}
        for name in names
    ]


def test_zip_asset_prefers_full_package():
    url = updater.find_zip_asset(
        _assets("extras.zip", "WinZapp.zip", "WinZappClient.zip"),
        client_only=False,
    )
    assert url.endswith("/WinZapp.zip")


def test_zip_asset_prefers_client_only_package_when_requested():
    url = updater.find_zip_asset(
        _assets("WinZapp.zip", "WinZappClient.zip"),
        client_only=True,
    )
    assert url.endswith("/WinZappClient.zip")


def test_zip_asset_falls_back_to_a_zip_when_named_asset_is_absent():
    url = updater.find_zip_asset(_assets("portable-build.zip"), client_only=False)
    assert url.endswith("/portable-build.zip")


def test_zip_asset_absent():
    assert updater.find_zip_asset([], client_only=False) == ""
    assert updater.find_zip_asset(None, client_only=False) == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0.25.0.0beta", ((0, 25, 0, 0), "beta")),
        ("0.25.0.1500alpha", ((0, 25, 0, 1500), "alpha")),
        ("1.0.0.0", ((1, 0, 0, 0), "")),
    ],
)
def test_supported_versions_parse(value, expected):
    assert updater.parse_version(value) == expected


def test_version_ordering_is_numeric_before_suffix():
    assert updater.is_newer("0.25.0.1500alpha", "0.25.0.0beta")
    assert updater.is_newer("0.25.0.1501alpha", "0.25.0.1500alpha")
    assert updater.is_newer("0.26.0.0beta", "0.25.0.1501alpha")
    assert not updater.is_newer("0.25.0.1501alpha", "0.26.0.0beta")


class _I18n:
    def get_language(self):
        return "pt-BR"

    def t(self, key):
        return key


class _MainWindow:
    def __init__(self):
        self.i18n = _I18n()


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _release(tag, assets=None, body=""):
    return {
        "tag_name": tag,
        "assets": assets if assets is not None else _assets(
            "WinZapp.zip", "SHA256SUMS.txt"
        ),
        "body": body,
    }


def test_check_once_offers_a_newer_latest_release(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    offered = []
    monkeypatch.setattr(updater, "__version__", "1.0.0.0")
    monkeypatch.setattr(updater, "is_client_only_install", lambda: False)
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _Response(_release("v1.1.0.0")),
    )
    monkeypatch.setattr(
        updater,
        "resolve_changelog",
        lambda *a, **kw: "changes",
    )
    monkeypatch.setattr(
        updater.wx,
        "CallAfter",
        lambda fn, *args: offered.append((fn.__name__, args)),
    )

    checker._check_once()

    assert offered
    name, args = offered[0]
    assert name == "_show_update_dialog"
    assert args[0] == "1.1.0.0"
    assert args[1] == "changes"
    assert args[2].endswith("/WinZapp.zip")
    assert args[3].endswith("/SHA256SUMS.txt")


def test_check_once_retries_when_latest_release_is_not_newer(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []
    monkeypatch.setattr(updater, "__version__", "1.1.0.0")
    monkeypatch.setattr(updater, "is_client_only_install", lambda: False)
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _Response(_release("v1.1.0.0")),
    )
    monkeypatch.setattr(checker, "_schedule_retry", lambda: retried.append(True))

    checker._check_once()

    assert retried == [True]


def test_check_once_retries_on_network_failure(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []

    def fail(*a, **kw):
        raise RuntimeError("offline")

    monkeypatch.setattr(updater.requests, "get", fail)
    monkeypatch.setattr(checker, "_schedule_retry", lambda: retried.append(True))

    checker._check_once()

    assert retried == [True]


def test_check_once_retries_when_release_has_no_zip(monkeypatch):
    checker = updater.UpdateChecker(_MainWindow())
    retried = []
    monkeypatch.setattr(
        updater.requests,
        "get",
        lambda *a, **kw: _Response(_release("v1.1.0.0", assets=_assets("notes.txt"))),
    )
    monkeypatch.setattr(updater, "is_client_only_install", lambda: False)
    monkeypatch.setattr(checker, "_schedule_retry", lambda: retried.append(True))

    checker._check_once()

    assert retried == [True]
