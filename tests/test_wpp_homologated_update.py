"""Tests for the current rolling-main WPPConnect update policy.

A tag can still be supplied explicitly through WPPCONNECT_TAG_VERSION, but
normal installs and in-app checks follow wppconnect-server/main.  The update
checker therefore compares the installed commit marker with the latest main
commit rather than treating client/wpp_minimum_version.txt as the source of
truth.
"""

import inspect
from pathlib import Path

from ui.dialogs import api_setup
from updater import WppUpdateChecker


ROOT = Path(__file__).resolve().parents[1]


def test_latest_lookup_prefers_the_main_branch_commit():
    source = inspect.getsource(api_setup.fetch_latest_wpp_tag)
    assert "fetch_latest_wpp_commit_sha" in source
    assert "WPP_GITHUB_API_LATEST_RELEASE" in source


def test_the_in_app_installer_can_download_main_or_an_explicit_tag():
    source = (ROOT / "client/ui/dialogs/api_setup.py").read_text(encoding="utf-8")
    assert "archive/refs/heads/main.zip" in source
    assert "archive/refs/tags/{tag}.zip" in source
    assert "WPPCONNECT_TAG_VERSION" in source


def test_setup_api_uses_the_environment_tag_only_as_an_optional_override():
    source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    assert 'env.get("WPPCONNECT_TAG_VERSION", "").strip()' in source
    assert "refs/heads/main" in source or "wppconnect-server.git" in source


def test_updater_uses_the_shared_latest_commit_or_release_lookup():
    source = inspect.getsource(WppUpdateChecker._fetch_latest_tag)
    assert "fetch_latest_wpp_tag()" in source


def test_legacy_minimum_version_file_is_not_required_by_install_paths():
    for path in (
        ROOT / "setup_api.py",
        ROOT / "client/ui/dialogs/api_setup.py",
        ROOT / "client/updater.py",
    ):
        assert "wpp_minimum_version.txt" not in path.read_text(encoding="utf-8")
