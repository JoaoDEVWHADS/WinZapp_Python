"""client/api_patches/ and client/api/ must never drift apart.

client/api/ is almost entirely git-ignored, but .gitignore deliberately
un-ignores exactly WinZapp's patched files, because a fresh checkout (including
the CI release build) otherwise has nothing to restore and silently ships
vanilla, unpatched WPPConnect Server.

That leaves two copies of every patch on disk, and setup_api.py restores
client/api/ *from* client/api_patches/. So editing only the client/api/ copy
looks like it works — until the next setup_api.py run silently reverts it.
That is exactly what happened to start.js: commit daf2d352 added the npx-cli.js
resolution fallback (needed on machines with no system-wide Node) to
client/api/start.js only, and re-running setup_api.py threw it away.

These tests compare the two copies byte for byte so the same mistake fails
here instead of in a user's install.

package.json is deliberately NOT compared: setup_api.py merges only
_PATCHED_DEPENDENCY_KEYS into whatever the clone produced (so WPPConnect's own
"version" field keeps reflecting the tag actually built) and re-serializes the
file, so the two copies legitimately differ. Its patched dependencies are
checked instead.
"""

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = ROOT / "client" / "api"
PATCHES = ROOT / "client" / "api_patches"

# Mirrors setup_api.py's CUSTOM_ROOT_FILES + CUSTOM_SRC_FILES, minus
# package.json (see the module docstring).
MIRRORED_FILES = [
    "start.js",
    "config.json",
    "decrypt.js",
    "src/config.ts",
    "src/index.ts",
    "src/util/createSessionUtil.ts",
    "src/util/sessionUtil.ts",
    "src/util/functions.ts",
    "src/middleware/statusConnection.ts",
    "src/controller/deviceController.ts",
    "src/controller/messageController.ts",
    "src/controller/sessionController.ts",
    "src/routes/index.ts",
]


@pytest.mark.parametrize("rel_path", MIRRORED_FILES)
def test_the_two_copies_of_each_patch_are_identical(rel_path):
    patch = PATCHES / rel_path
    live = API / rel_path
    if not patch.exists():
        pytest.skip(f"client/api_patches/{rel_path} not present")
    if not live.exists():
        # client/api/ is only populated after setup_api.py has run; a bare
        # checkout legitimately has just the tracked subset.
        pytest.skip(f"client/api/{rel_path} not present (API not set up here)")
    assert patch.read_bytes() == live.read_bytes(), (
        f"client/api/{rel_path} and client/api_patches/{rel_path} have drifted. "
        f"api_patches/ is the source of truth setup_api.py restores from — edit "
        f"that copy (and mirror it into client/api/), or the next setup_api.py "
        f"run will silently revert this file."
    )


def test_setup_api_patch_list_matches_this_one():
    """If setup_api.py starts patching another file, this test must cover it too."""
    src = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    for rel_path in MIRRORED_FILES:
        assert f'"{rel_path}"' in src, f"{rel_path} is no longer listed in setup_api.py"


def test_the_in_app_installer_restores_the_same_src_patches():
    """ApiSetupDialog (the "install modules" flow reachable by just running the
    program) has its own copy of the list. It must not fall behind
    setup_api.py's, or an install done that way ships unpatched code."""
    src = (ROOT / "client" / "ui" / "dialogs" / "api_setup.py").read_text(encoding="utf-8")
    for rel_path in MIRRORED_FILES:
        if rel_path in ("start.js", "config.json"):
            # Root-level files: preserved rather than restored — see _PRESERVE.
            assert f'"{rel_path}"' in src
            continue
        assert f'"{rel_path}"' in src, f"ApiSetupDialog does not restore {rel_path}"


def test_patched_dependencies_are_present_in_the_live_package_json():
    """setup_api.py merges these three into whatever the clone produced. They
    are what the file is patched *for*, so their absence means the merge never
    ran (or was undone)."""
    live = API / "package.json"
    if not live.exists():
        pytest.skip("client/api/package.json not present")
    patched = json.loads((PATCHES / "package.json").read_text(encoding="utf-8"))
    deps = json.loads(live.read_text(encoding="utf-8")).get("dependencies", {})
    for key in ("@wppconnect-team/wppconnect", "@ffmpeg-installer/ffmpeg", "fluent-ffmpeg"):
        assert key in deps, f"{key} missing from client/api/package.json"
        assert deps[key] == patched["dependencies"][key], (
            f"{key} is pinned to {patched['dependencies'][key]} in api_patches/ "
            f"but is {deps[key]} in client/api/"
        )
