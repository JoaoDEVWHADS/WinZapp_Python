"""uv is an addition to the Python workflow, not a replacement for venv.

build.py used to hardcode venv\\ and so worked from any interpreter; the uv
migration made it build with whichever interpreter runs it. These pin the
rungs that keep every pre-existing invocation working, plus the project
commands `uv sync` installs.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winzapp_tools import build_env, cli  # noqa: E402

ROOT_DIR = r"C:\src\WinZapp"
SYSTEM_PY = r"C:\Python313\python.exe"
LEGACY_VENV_PY = os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe")
UV_VENV_PY = os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe")


def _select(environ=None, running=SYSTEM_PY, in_venv=False, existing=(), has_pyinstaller=True):
    return build_env.select_build_python(
        environ or {}, running, in_venv, ROOT_DIR,
        isfile=lambda p: p in existing, running_has_pyinstaller=has_pyinstaller,
    )


class TestSelectBuildPython:
    def test_winzapp_venv_wins_over_everything(self):
        assert _select(
            {"WINZAPP_VENV": r"D:\venv_build"},
            running=UV_VENV_PY, in_venv=True, existing={LEGACY_VENV_PY},
        ) == os.path.join(r"D:\venv_build", "Scripts", "python.exe")

    def test_uv_run_builds_with_the_uv_environment(self):
        assert _select(running=UV_VENV_PY, in_venv=True, existing={LEGACY_VENV_PY}) == UV_VENV_PY

    def test_explicit_venv_python_builds_with_that_venv(self):
        assert _select(running=LEGACY_VENV_PY, in_venv=True, existing={UV_VENV_PY}) == LEGACY_VENV_PY

    def test_bare_python_still_finds_the_legacy_venv_first(self):
        assert _select(existing={LEGACY_VENV_PY, UV_VENV_PY}) == LEGACY_VENV_PY

    def test_bare_python_falls_back_to_the_uv_venv(self):
        assert _select(existing={UV_VENV_PY}) == UV_VENV_PY

    def test_bare_python_with_no_venv_uses_itself(self):
        assert _select() == SYSTEM_PY

    def test_an_unrelated_active_venv_does_not_shadow_the_repository_venv(self):
        """An editor auto-activating some other environment: build.py
        hardcoded venv\\ before and built anyway, so it still must."""
        other = r"C:\Users\dev\envs\scratch\Scripts\python.exe"
        assert _select(
            running=other, in_venv=True, existing={LEGACY_VENV_PY}, has_pyinstaller=False,
        ) == LEGACY_VENV_PY

    def test_an_active_venv_without_pyinstaller_and_nowhere_else_stays_put(self):
        other = r"C:\Users\dev\envs\scratch\Scripts\python.exe"
        assert _select(running=other, in_venv=True, has_pyinstaller=False) == other

    def test_blank_winzapp_venv_is_ignored(self):
        assert _select({"WINZAPP_VENV": "  "}, existing={LEGACY_VENV_PY}) == LEGACY_VENV_PY


class TestPortableNode:
    def test_only_the_exact_homologated_version_is_kept(self):
        assert build_env.portable_node_needs_replacing("22.22.2", "22.22.2") is False
        # Newer is replaced too: the build decides what every user receives.
        assert build_env.portable_node_needs_replacing("24.15.0", "22.22.2") is True
        assert build_env.portable_node_needs_replacing("22.1.0", "22.22.2") is True
        assert build_env.portable_node_needs_replacing("", "22.22.2") is True

    def test_version_probe_strips_the_prefix(self, tmp_path):
        exe = tmp_path / "node.exe"
        exe.write_bytes(b"")

        def fake_run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, stdout="v22.22.2\n", stderr="")

        assert build_env.portable_node_version(str(exe), run=fake_run) == "22.22.2"

    def test_version_probe_failures_read_as_unknown(self, tmp_path):
        assert build_env.portable_node_version(str(tmp_path / "absent.exe")) == ""
        exe = tmp_path / "node.exe"
        exe.write_bytes(b"")

        def broken(cmd, **kwargs):
            raise OSError("not a valid Win32 application")

        def failing(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

        assert build_env.portable_node_version(str(exe), run=broken) == ""
        assert build_env.portable_node_version(str(exe), run=failing) == ""


class TestProjectCommands:
    def test_pyproject_exposes_the_developer_shortcuts(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        scripts = metadata["project"]["scripts"]
        for name, target in {
            "winzapp": "app",
            "api": "api",
            "setup-api": "setup_api",
            "build-onefile": "build_onefile",
            "build-installer": "build_installer",
            "test": "test",
        }.items():
            assert scripts[name] == f"winzapp_tools.cli:{target}"
            assert callable(getattr(cli, target))

    def test_the_client_runs_from_client_dir_like_the_venv_workflow(self):
        """app_paths._data_root() is os.getcwd()/data in dev mode. Starting
        main.py from the repository root would open a second, empty install
        instead of the one `cd client; python main.py` has been using."""
        cmd, cwd = cli.command_for("app", ["--background"], python="py")
        assert cwd == ROOT / "client"
        assert cmd == ["py", str(ROOT / "client" / "main.py"), "--background"]

    def test_build_commands_forward_extra_arguments(self):
        cmd, cwd = cli.command_for("build_onefile", ["--help"], python="py")
        assert cwd == ROOT
        assert cmd == ["py", str(ROOT / "build.py"), "--onefile", "--help"]


def test_build_script_hands_over_before_touching_site_packages():
    """The hand-over has to happen before SITE_PACKAGES (and the ffmpeg /
    libopus preparation) is computed from the wrong interpreter."""
    source = (ROOT / "build.py").read_text(encoding="utf-8")
    hand_over = source.index("    hand_over_to_build_python(__file__, ROOT_DIR)")
    assert hand_over < source.index("SITE_PACKAGES = ")
    assert hand_over < source.index("OPUS_DLL = ")
    assert hand_over < source.index("args = parser.parse_args()")


def test_build_zip_only_hands_over_before_importing_build():
    """`import build` never runs build.py's __main__ hand-over, and the import
    itself already reads site-packages."""
    source = (ROOT / "build_zip_only.py").read_text(encoding="utf-8")
    assert source.index("hand_over_to_build_python(__file__, _root)") < source.index("\nimport build")


def test_ci_pins_the_uv_version_it_runs():
    offenders = []
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, 1):
            if "uses: astral-sh/setup-uv@" not in line:
                continue
            following = "\n".join(lines[number:number + 6])
            if not re.search(r'^\s+version:\s*"\d+\.\d+\.\d+"', following, re.M):
                offenders.append(f"{path.name}:{number}")
    assert not offenders, f"setup-uv without an exact `version:`: {offenders}"
