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


def test_the_installed_wa_js_is_the_one_that_was_pinned():
    """The pair's other half. wppconnect 2.3.4 changed no compiled file and
    moved only its wa-js range, so an install can sit on the pinned wppconnect
    with the previous wa-js underneath it and every wppconnect check passing."""
    live = ROOT / "client" / "api" / "node_modules" / "@wppconnect" / "wa-js" / "package.json"
    if not live.exists():
        pytest.skip("client/api/node_modules not present")
    installed = json.loads(live.read_text(encoding="utf-8"))["version"]
    expected = _patch_package_json()["dependencies"]["@wppconnect/wa-js"]
    assert installed == expected, (
        f"client/api/node_modules holds @wppconnect/wa-js {installed}, but the "
        f"homologated pin is {expected}. Re-run setup_api.py."
    )


def _npm_range_allows(pinned: str, npm_range: str) -> bool:
    """Whether an exact version satisfies a single npm range operator.

    Only the three forms upstream actually uses are understood — a caret, a
    tilde, and a bare exact version. Anything else raises rather than quietly
    passing: a range this cannot read is a range nobody is checking.
    """
    low = Version(pinned)
    if npm_range.startswith("^"):
        floor = Version(npm_range[1:])
        # A caret allows changes that do not modify the left-most *non-zero*
        # component, so ^0.2.3 stops at 0.3.0 and ^0.0.3 at 0.0.4 — widening
        # those to 1.0.0 would let a range nobody satisfies read as satisfied.
        if floor.major:
            ceiling = Version(f"{floor.major + 1}.0.0")
        elif floor.minor:
            ceiling = Version(f"0.{floor.minor + 1}.0")
        else:
            ceiling = Version(f"0.0.{floor.micro + 1}")
    elif npm_range.startswith("~"):
        floor = Version(npm_range[1:])
        ceiling = Version(f"{floor.major}.{floor.minor + 1}.0")
    else:
        return low == Version(npm_range)
    return floor <= low < ceiling


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


def test_every_node_modules_patch_still_matches_the_pinned_runtime():
    """The node_modules patches are idempotent search-and-replace, so a
    runtime whose source moved is reported as a warning and skipped, never as
    an error. Assert the return value nothing else looks at.

    Runs against a throwaway copy so the test never writes into the real
    node_modules.
    """
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

        # The fifth patch is in the other half of the pair: wa-js's bundle.
        from core.wppconnect_wa_js_patch import WA_JS_BUNDLE_PARTS
        bundle = ROOT.joinpath("client", "api", *WA_JS_BUNDLE_PARTS)
        if bundle.exists():
            bundle_copy = Path(tmp).joinpath(*WA_JS_BUNDLE_PARTS)
            bundle_copy.parent.mkdir(parents=True)
            shutil.copy2(bundle, bundle_copy)
            assert setup_api._patch_wa_js_bundle(tmp)
            assert setup_api._patch_chat_lookup_bundle(tmp)
            assert setup_api._patch_newsletter_chat_bundle(tmp)
            # both of its fixes, not one: "already applied" is also answered
            # when only one of them matched, and text posts and polls to a
            # channel would fail again with nothing flagging it
            from core import wppconnect_newsletter_chat_patch as newsletter_chat
            patched = bundle_copy.read_text(encoding="utf-8")
            assert newsletter_chat._PATCHED.search(patched), "channel chat lookup not patched"
            assert newsletter_chat._NAMED_JOB.search(patched), "channel send job not bound by name"
