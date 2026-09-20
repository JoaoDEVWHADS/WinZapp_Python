"""Regression coverage for WinZapp's rolling WPPConnect dependency policy.

The current setup intentionally follows the Git repositories for the three
WPPConnect runtime packages.  The policy lives in core.wpp_dependency_setup
and both installation paths consume the same key set, so tests should guard
that shared contract rather than the retired exact-version "homologated pair".
"""

import json
from pathlib import Path

import pytest

import setup_api
from core.wpp_dependency_setup import GITHUB_DEPENDENCIES, PATCHED_DEPENDENCY_KEYS
from ui.dialogs.api_setup import _PATCHED_DEPENDENCY_KEYS as _DIALOG_KEYS


ROOT = Path(__file__).resolve().parents[1]


def _patch_package_json() -> dict:
    return json.loads(
        (ROOT / "client" / "api_patches" / "package.json").read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("package_name, git_url", tuple(GITHUB_DEPENDENCIES.items()))
def test_api_patches_tracks_the_shared_git_runtime(package_name, git_url):
    declared = _patch_package_json()["dependencies"].get(package_name)
    assert declared == git_url
    assert declared.startswith("git+https://github.com/")
    assert "#" not in declared, "rolling Git dependencies must not silently regain a frozen ref"


@pytest.mark.parametrize("package_name", tuple(GITHUB_DEPENDENCIES))
def test_both_installers_apply_every_git_runtime_dependency(package_name):
    assert package_name in setup_api._PATCHED_DEPENDENCY_KEYS
    assert package_name in _DIALOG_KEYS


def test_wa_version_is_updated_with_the_other_git_dependencies():
    assert "@wppconnect/wa-version" in GITHUB_DEPENDENCIES
    assert "@wppconnect/wa-version" in PATCHED_DEPENDENCY_KEYS
    assert _patch_package_json()["dependencies"]["@wppconnect/wa-version"] == (
        GITHUB_DEPENDENCIES["@wppconnect/wa-version"]
    )


def test_the_two_installers_patch_the_same_dependency_set():
    assert tuple(setup_api._PATCHED_DEPENDENCY_KEYS) == tuple(_DIALOG_KEYS)
    assert tuple(_DIALOG_KEYS) == tuple(PATCHED_DEPENDENCY_KEYS)


def test_the_patched_set_matches_the_shared_policy():
    assert set(PATCHED_DEPENDENCY_KEYS) == {
        "prom-client",
        "zod",
        "@ffmpeg-installer/ffmpeg",
        *GITHUB_DEPENDENCIES.keys(),
    }


def test_package_json_contains_every_shared_dependency_value():
    dependencies = _patch_package_json()["dependencies"]
    for package_name, expected in GITHUB_DEPENDENCIES.items():
        assert dependencies[package_name] == expected


def test_every_node_modules_patch_still_matches_the_installed_runtime():
    """When node_modules is available, the WinZapp search/replace patches must
    still match whatever rolling Git revision was installed."""
    dist = (
        ROOT / "client" / "api" / "node_modules" / "@wppconnect-team"
        / "wppconnect" / "dist"
    )
    if not (dist / "api" / "layers" / "host.layer.js").exists():
        pytest.skip("client/api/node_modules not present")

    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "node_modules" / "@wppconnect-team" / "wppconnect" / "dist"
        shutil.copytree(dist / "api" / "layers", dest / "api" / "layers")
        shutil.copytree(dist / "controllers", dest / "controllers")
        assert setup_api._patch_wppconnect_host_layer(tmp)
        assert setup_api._patch_wppconnect_status_layer(tmp)
        assert setup_api._patch_wppconnect_sender_layer(tmp)
        assert setup_api._patch_wppconnect_welcome_layer(tmp)
