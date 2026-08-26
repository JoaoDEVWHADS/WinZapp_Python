"""WPPConnect runtime dependencies must resolve from GitHub main."""

import json
from pathlib import Path

from core.wpp_dependency_setup import (
    GITHUB_DEPENDENCIES,
    PATCHED_DEPENDENCY_KEYS,
)


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "client/api_patches/package.json"


def test_runtime_dependencies_use_their_real_package_names_and_github_sources():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dependencies = manifest.get("dependencies", {})

    assert {
        name: dependencies.get(name)
        for name in GITHUB_DEPENDENCIES
    } == GITHUB_DEPENDENCIES


def test_github_dependencies_follow_head_instead_of_a_frozen_revision():
    for source in GITHUB_DEPENDENCIES.values():
        assert source.startswith("git+https://github.com/")
        assert "#" not in source


def test_wrong_team_aliases_are_not_declared():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dependencies = manifest.get("dependencies", {})

    assert "@wppconnect-team/wa-js" not in dependencies
    assert "@wppconnect-team/wa-version" not in dependencies


def test_installers_merge_all_github_dependencies():
    assert set(GITHUB_DEPENDENCIES) <= set(PATCHED_DEPENDENCY_KEYS)

    setup_source = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    dialog_source = (
        ROOT / "client/ui/dialogs/api_setup.py"
    ).read_text(encoding="utf-8")
    expected_import = (
        "PATCHED_DEPENDENCY_KEYS as _PATCHED_DEPENDENCY_KEYS"
    )

    assert expected_import in setup_source
    assert expected_import in dialog_source
