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
  - sys._MEIPASS -> <exe_dir>/_internal  (Python runtime; NOT where external assets live)
  - sys.executable  -> the exe inside <exe_dir>
  External assets (sounds/, languages/, node/, api/, lib/) live in <exe_dir>, NOT in _internal.
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

    PyInstaller onefile: all assets are extracted to sys._MEIPASS (a temp dir
      that is NOT a subdirectory of the exe's directory).

    PyInstaller onedir: Python runtime goes into _internal/ (= sys._MEIPASS),
      but external assets (sounds/, languages/, node/, api/, lib/) live next to
      the exe — i.e. in the *parent* of sys._MEIPASS.  We detect this case by
      checking whether sys._MEIPASS is a direct child of the exe directory.

    Nuitka onefile / dev mode: no sys._MEIPASS; use _outer_exe_dir().
    """
    if hasattr(sys, "_MEIPASS"):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        meipass_parent = os.path.dirname(os.path.abspath(sys._MEIPASS))
        if os.path.normcase(meipass_parent) == os.path.normcase(exe_dir):
            # onedir: _MEIPASS == <exe_dir>/_internal — external assets are in exe_dir
            return exe_dir
        # onefile: _MEIPASS is a temp extraction dir — everything is there
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
