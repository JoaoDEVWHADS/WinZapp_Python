"""Tests for client-only release/update package selection."""

import updater


def _assets(*names):
    return [
        {"name": n, "browser_download_url": f"https://example.invalid/{n}"}
        for n in names
    ]


def test_client_only_zip_asset_is_selected_explicitly():
    url = updater.find_zip_asset(
        _assets("WinZapp.zip", "WinZappClient.zip"), client_only=True
    )
    assert url.endswith("/WinZappClient.zip")


def test_client_only_zip_never_falls_back_to_full_package():
    assert updater.find_zip_asset(_assets("WinZapp.zip"), client_only=True) == ""


def test_full_package_never_falls_back_to_client_only_package():
    assert updater.find_zip_asset(_assets("WinZappClient.zip"), client_only=False) == ""


def test_client_only_distribution_marker_is_detected(tmp_path):
    (tmp_path / "distribution.json").write_text(
        '{"variant":"client-only"}\n', encoding="utf-8"
    )
    assert updater.is_client_only_install(str(tmp_path)) is True


def test_missing_distribution_marker_defaults_to_full(tmp_path):
    assert updater.is_client_only_install(str(tmp_path)) is False
