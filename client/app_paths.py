"""
Path helpers that work in dev mode, Nuitka onefile, and PyInstaller onefile/onedir.

In Nuitka onefile mode:
  - sys.executable  -> inner extracted exe  (e.g. %LOCALAPPDATA%\\WinZapp\\WinZapp.exe)
  - sys.argv[0]     -> outer bootstrap exe  (e.g. C:\\install\\WinZapp.exe)
  All external assets live next to the outer exe.

In PyInstaller onefile mode:
  - sys._MEIPASS    -> temp extraction dir (e.g. %TEMP%\\_MEIxxxxxx)
  - sys.executable  -> the onefile .exe at its original location
  All bundled assets are extracted to sys._MEIPASS.

In PyInstaller onedir mode:
  - Assets live in _internal/ next to the exe.
  - sys._MEIPASS is NOT set; paths are relative to sys.executable.
"""

import os
import sys


def _is_frozen() -> bool:
    return hasattr(sys, "frozen") or "__compiled__" in globals()


def _outer_exe_dir() -> str:
    """Return the directory containing the app executable (for updates, etc.)."""
    if _is_frozen():
        if sys.argv and sys.argv[0]:
            return os.path.dirname(os.path.abspath(sys.argv[0]))
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _get_base_dir() -> str:
    """Return the base directory for read-only assets.

    In PyInstaller onefile mode assets are extracted to sys._MEIPASS (temp).
    In all other frozen modes they live next to the exe (_outer_exe_dir).
    """
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return _outer_exe_dir()


def resource_path(*parts: str) -> str:
    """Absolute path to a read-only asset file or directory."""
    return os.path.join(_get_base_dir(), *parts)


def data_path(*parts: str) -> str:
    """Absolute path inside the writable data directory."""
    if _is_frozen():
        if hasattr(sys, "_MEIPASS"):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.path.dirname(sys.executable)
        return os.path.join(base, "data", *parts)
    return os.path.join(os.getcwd(), "data", *parts)


def log_path(*parts: str) -> str:
    """Absolute path inside the writable logs directory."""
    if _is_frozen():
        if hasattr(sys, "_MEIPASS"):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(sys.argv[0])) if sys.argv and sys.argv[0] else os.path.dirname(sys.executable)
        return os.path.join(base, "logs", *parts)
    return os.path.join(os.getcwd(), "logs", *parts)
