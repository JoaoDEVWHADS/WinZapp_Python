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


def test_the_in_app_installer_restores_the_same_patches():
    """ApiSetupDialog — the "install modules" flow every end user goes through
    just by running the program — has its own copy of the list. It must not fall
    behind setup_api.py's, or the API installed on users' machines is not the
    one we develop and test against."""
    src = (ROOT / "client" / "ui" / "dialogs" / "api_setup.py").read_text(encoding="utf-8")
    for rel_path in MIRRORED_FILES:
        assert f'"{rel_path}"' in src, f"ApiSetupDialog does not restore {rel_path}"


def test_both_installers_patch_the_same_dependencies():
    """package.json is merged, not copied, by both flows — but only setup_api.py
    used to do it at all, so every end-user install ran npm install against the
    vanilla upstream file: the wppconnect pin was ignored and neither ffmpeg
    dependency was installed."""
    setup = (ROOT / "setup_api.py").read_text(encoding="utf-8")
    dialog = (ROOT / "client" / "ui" / "dialogs" / "api_setup.py").read_text(encoding="utf-8")
    for key in ("@wppconnect-team/wppconnect", "@ffmpeg-installer/ffmpeg", "fluent-ffmpeg"):
        assert f'"{key}"' in setup, f"{key} dropped from setup_api.py"
        assert f'"{key}"' in dialog, f"{key} not patched by ApiSetupDialog"


def test_the_in_app_installer_refreshes_root_files_rather_than_only_preserving_them():
    """start.js and config.json carry no per-install state — the API key and
    port both come from environment variables injected at launch, and nothing
    writes either file at runtime. Merely preserving whatever was on disk froze
    them at whatever an older WinZapp install left behind, so a user updating
    from an old version silently kept its config.json forever."""
    dialog = (ROOT / "client" / "ui" / "dialogs" / "api_setup.py").read_text(encoding="utf-8")
    assert "_CUSTOM_ROOT_FILES" in dialog
    assert "_CUSTOM_SRC_FILES + _CUSTOM_ROOT_FILES" in dialog, (
        "root files must go through the same api_patches/ restore loop"
    )
    # ...while still being kept out of the upstream ZIP's way.
    assert '_PRESERVE = {"start.js", ".env", "config.json"}' in dialog


class TestPackageJsonMerge:
    """ApiSetupDialog._merge_package_json_dependencies is a staticmethod, so it
    runs without a wx.App."""

    @staticmethod
    def _dialog():
        from ui.dialogs.api_setup import ApiSetupDialog
        return ApiSetupDialog

    def _setup_dirs(self, tmp_path, pkg, patch):
        api = tmp_path / "api"
        patches = tmp_path / "api_patches"
        api.mkdir()
        patches.mkdir()
        (api / "package.json").write_text(json.dumps(pkg), encoding="utf-8")
        (patches / "package.json").write_text(json.dumps(patch), encoding="utf-8")
        return api, patches

    def test_patched_dependencies_are_applied(self, tmp_path):
        api, patches = self._setup_dirs(
            tmp_path,
            {"version": "2.10.1", "dependencies": {"@wppconnect-team/wppconnect": "^2.9.0"}},
            {"version": "0.0.0", "dependencies": {
                "@wppconnect-team/wppconnect": "2.2.4",
                "@ffmpeg-installer/ffmpeg": "^1.1.0",
                "fluent-ffmpeg": "^2.1.3",
            }},
        )
        self._dialog()._merge_package_json_dependencies(str(api), str(patches))
        out = json.loads((api / "package.json").read_text(encoding="utf-8"))
        assert out["dependencies"]["@wppconnect-team/wppconnect"] == "2.2.4"
        assert out["dependencies"]["@ffmpeg-installer/ffmpeg"] == "^1.1.0"
        assert out["dependencies"]["fluent-ffmpeg"] == "^2.1.3"

    def test_the_downloaded_version_field_is_never_overwritten(self, tmp_path):
        """WppUpdateChecker compares this against the latest GitHub release — it
        has to describe the tag actually downloaded, not one frozen in
        api_patches/."""
        api, patches = self._setup_dirs(
            tmp_path,
            {"version": "2.10.1", "dependencies": {}},
            {"version": "2.10.0", "dependencies": {"fluent-ffmpeg": "^2.1.3"}},
        )
        self._dialog()._merge_package_json_dependencies(str(api), str(patches))
        assert json.loads((api / "package.json").read_text(encoding="utf-8"))["version"] == "2.10.1"

    def test_other_upstream_dependencies_are_left_alone(self, tmp_path):
        """A wholesale copy would roll every unrelated dependency back to
        whatever api_patches/ happened to freeze."""
        api, patches = self._setup_dirs(
            tmp_path,
            {"version": "2.10.1", "dependencies": {"express": "4.22.1", "axios": "^1.14.0"}},
            {"version": "0.0.0", "dependencies": {"express": "4.0.0", "fluent-ffmpeg": "^2.1.3"}},
        )
        self._dialog()._merge_package_json_dependencies(str(api), str(patches))
        deps = json.loads((api / "package.json").read_text(encoding="utf-8"))["dependencies"]
        assert deps["express"] == "4.22.1", "express is not a patched key"
        assert deps["axios"] == "^1.14.0"

    def test_a_missing_package_json_is_not_fatal(self, tmp_path):
        api = tmp_path / "api"
        patches = tmp_path / "api_patches"
        api.mkdir()
        patches.mkdir()
        # Must not raise: npm install can still work on the upstream file.
        self._dialog()._merge_package_json_dependencies(str(api), str(patches))

    def test_malformed_json_leaves_the_file_untouched(self, tmp_path):
        api, patches = self._setup_dirs(tmp_path, {"dependencies": {}}, {"dependencies": {}})
        (api / "package.json").write_text("{ not json", encoding="utf-8")
        self._dialog()._merge_package_json_dependencies(str(api), str(patches))
        assert (api / "package.json").read_text(encoding="utf-8") == "{ not json"

    def test_the_real_patch_file_produces_the_real_pins(self, tmp_path):
        """Runs the merge against the actual api_patches/package.json shipped in
        the repo, so a bad edit to it is caught here."""
        api = tmp_path / "api"
        api.mkdir()
        (api / "package.json").write_text(
            json.dumps({"version": "9.9.9", "dependencies": {}}), encoding="utf-8"
        )
        self._dialog()._merge_package_json_dependencies(str(api), str(PATCHES))
        out = json.loads((api / "package.json").read_text(encoding="utf-8"))
        assert out["version"] == "9.9.9"
        for key in ("@wppconnect-team/wppconnect", "@ffmpeg-installer/ffmpeg", "fluent-ffmpeg"):
            assert key in out["dependencies"], key


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
