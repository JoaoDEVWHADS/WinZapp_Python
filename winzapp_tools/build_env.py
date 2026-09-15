"""Decisions build.py has to make before it can import anything heavy.

Kept out of build.py itself because that script parses argv and downloads
ffmpeg/libopus at import time, so none of its logic can be reached from a
test. Standard library only: a bare system interpreter may run this before
it hands the build over to a virtual environment.
"""

from __future__ import annotations

import os
import subprocess

# Set in the child build.py runs under, so the hand-over happens at most once.
REEXEC_MARKER = "WINZAPP_BUILD_PYTHON_SELECTED"


def _venv_python(venv_dir: str) -> str:
    return os.path.join(venv_dir, "Scripts", "python.exe")


def select_build_python(
    environ,
    running_python: str,
    running_in_virtualenv: bool,
    root_dir: str,
    isfile=os.path.isfile,
    running_has_pyinstaller: bool = True,
) -> str:
    """Return the interpreter the build must run under.

    Every rung is a way somebody already runs build.py, and none may stop
    working because uv became an option:

      1. ``WINZAPP_VENV`` names a virtual environment explicitly
         (build_zip_only.py's ``venv_build``, forks with their own layout).
      2. The running interpreter, when it already is a virtual environment
         that can build: ``uv run build-onefile``, an activated venv, or
         ``venv\\Scripts\\python.exe build.py``. A venv without PyInstaller
         is some unrelated environment an editor happened to activate, and
         build.py used to ignore it and build with ``venv\\`` anyway.
      3. The repository's ``venv\\`` and then uv's ``.venv\\``. ``python
         build.py`` from a bare system interpreter always built with
         ``venv\\`` — build.py hardcoded it — and must keep doing so.
      4. The running interpreter, when there is nothing better.
    """
    explicit = (environ.get("WINZAPP_VENV") or "").strip()
    if explicit:
        return _venv_python(explicit)
    if running_in_virtualenv and running_has_pyinstaller:
        return running_python
    for name in ("venv", ".venv"):
        candidate = _venv_python(os.path.join(root_dir, name))
        if isfile(candidate):
            return candidate
    return running_python


def same_interpreter(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def hand_over_to_build_python(script: str, root_dir: str) -> None:
    """Re-run ``script`` under select_build_python()'s pick, if it isn't this one.

    Must run before the build touches site-packages, whose location depends
    on the interpreter. Every entry point that builds calls it — build.py and
    build_zip_only.py — since importing build.py never runs its __main__.
    Returns only when the current interpreter is the right one.
    """
    import importlib.util
    import sys

    if os.environ.get(REEXEC_MARKER):
        return
    target = select_build_python(
        os.environ,
        sys.executable,
        sys.prefix != sys.base_prefix,
        root_dir,
        running_has_pyinstaller=importlib.util.find_spec("PyInstaller") is not None,
    )
    if same_interpreter(target, sys.executable):
        return
    if not os.path.isfile(target):
        print(f"[ERROR] WINZAPP_VENV points at {target}, which does not exist.")
        sys.exit(1)
    print(f"  [python] Building with {target}", flush=True)
    env = dict(os.environ, **{REEXEC_MARKER: "1"})
    try:
        completed = subprocess.run([target, os.path.abspath(script), *sys.argv[1:]], env=env)
    except KeyboardInterrupt:
        sys.exit(130)
    sys.exit(completed.returncode)


def portable_node_version(node_exe: str, run=subprocess.run) -> str:
    """The version ``node_exe`` reports, without its ``v``; "" if it cannot say."""
    if not os.path.isfile(node_exe):
        return ""
    try:
        probe = run(
            [node_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if probe.returncode != 0:
        return ""
    return (probe.stdout or "").strip().lstrip("vV")


def portable_node_needs_replacing(installed_version: str, homologated_version: str) -> bool:
    """Whether the Node.js a build would bundle is not the homologated one.

    Exact match, not a floor, and deliberately stricter than the app's own
    runtime gate (``node_runtime_needs_download()`` in main.py only upgrades
    an older runtime). A build decides which Node every user receives, and
    WPPConnect Server pins ``engines.node`` exactly: a newer local copy
    — 24.x was what CI shipped until 22.22.2 was homologated — would go on
    being bundled with no warning at all.
    """
    return installed_version != homologated_version
