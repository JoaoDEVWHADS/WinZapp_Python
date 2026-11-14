"""Gettext must compile before bundling or deleting previous build artifacts.

Load only the build functions by AST: importing build.py downloads native
assets. Execute those functions against filesystem/subprocess stubs; never
run PyInstaller, a native app, or a network operation.
"""

import ast
import os
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from winzapp_tools import translation_build


def load_build_function(relative, name, namespace):
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[function], type_ignores=[]), relative, "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("onefile", [False, True])
def test_windows_bundles_compiled_resources_before_pyinstaller(tmp_path, monkeypatch, onefile):
    calls = []
    build_dir = tmp_path / "build"
    executable = tmp_path / "result.exe"
    executable.write_bytes(b"stub")
    def prepare(root, destination):
        calls.append(("gettext", root, destination))
        destination.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(translation_build, "prepare_runtime", prepare)
    namespace = {
        "os": os, "shutil": shutil, "ROOT_DIR": str(tmp_path), "BUILD_DIR": str(build_dir),
        "CLIENT_DIR": str(tmp_path / "client"), "ONEFILE": onefile,
        "DIST_DIR": str(tmp_path / "dist"), "PYINST_OUTDIR": str(build_dir / "pyinstaller_out"),
        "PYINST_APP_DIR": str(build_dir / "pyinstaller_out/WinZapp"),
        "PYINST_EXE": str(executable), "ONEFILE_EXE": str(executable),
        "PYINST_INTERNAL": str(tmp_path / "missing_internal"),
        "PYINSTALLER_CMD": ["python", "-m", "PyInstaller"],
        "step": lambda text: None, "_write_version_file": lambda folder: "version.txt",
        "run": lambda cmd, **kwargs: calls.append(("pyinstaller", cmd)),
        "NODE_DIR": str(tmp_path / "node"), "API_DIR": str(tmp_path / "api"),
        "SOUND_LIB_X64": str(tmp_path / "bass"), "AO2_LIB": str(tmp_path / "ao2"),
        "SETTINGS_DEFAULT": str(tmp_path / "settings.json"),
        "HELP_GUIDE_DIR": str(tmp_path / "help_guide"), "OPUS_DLL": None, "FFMPEG_EXE": None,
    }
    load_build_function("build.py", "pyinstaller_compile", namespace)()
    assert calls[0] == ("gettext", tmp_path, build_dir / "languages")
    assert calls[1][0] == "pyinstaller"
    if onefile:
        args = calls[1][1]
        assert f"{build_dir / 'languages'};languages" in args


@pytest.mark.parametrize("function_name", ["pyinstaller_compile", "assemble_staging"])
def test_bad_catalog_does_not_delete_previous_windows_output(tmp_path, monkeypatch, function_name):
    artifact = tmp_path / "previous"
    artifact.mkdir()
    sentinel = artifact / "keep.txt"
    sentinel.write_text("Previous successful build", encoding="utf-8")
    def refuse(*args, **kwargs):
        raise ValueError("Incomplete translations")
    monkeypatch.setattr(translation_build, "prepare_runtime", refuse)
    namespace = {
        "ROOT_DIR": str(tmp_path), "BUILD_DIR": str(tmp_path / "build"),
        "STAGING_DIR": str(artifact), "PYINST_APP_DIR": str(artifact),
    }
    function = load_build_function("build.py", function_name, namespace)
    with pytest.raises(ValueError, match="Incomplete translations"):
        function()
    assert sentinel.read_text(encoding="utf-8") == "Previous successful build"


def test_macos_compiles_the_same_catalogs_before_pyinstaller(tmp_path):
    class StopAfterCompilation(Exception):
        pass
    calls = []
    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        raise StopAfterCompilation
    namespace = {
        "os": os, "sys": sys, "BUILD": str(tmp_path / "macos/build"),
        "ROOT": str(tmp_path), "run": run, "env_with_pydeps": lambda: {"PYTHONPATH": ".pydeps"},
    }
    function = load_build_function("macos/build_app.py", "pyinstaller", namespace)
    with pytest.raises(StopAfterCompilation):
        function()
    assert calls == [([
        sys.executable, "-m", "winzapp_tools.translations", "compile", "--mo-dir",
        str(tmp_path / "macos/build/languages")
    ], {"cwd": str(tmp_path), "env": {"PYTHONPATH": ".pydeps"}})]
