"""
Path helpers that work in both dev mode and Nuitka onefile.

In Nuitka onefile mode:
  - sys.executable  -> inner extracted exe  (e.g. %LOCALAPPDATA%\\WinZapp\\WinZapp.exe)
  - sys.argv[0]     -> outer bootstrap exe  (e.g. C:\\install\\WinZapp.exe)

All external assets (sounds/, languages/, lib/, data/) live next to the OUTER exe.
We therefore derive all paths from sys.argv[0], not sys.executable.

- resource_path(): read-only assets (sounds, languages).
  In dev mode  -> next to this file (client/).
  In onefile   -> directory of the outer (bootstrap) exe.

- data_path(): writable user data (data/).
  In dev mode  -> os.getcwd()/data/
  In onefile   -> same directory as the outer exe, under data/
"""

import os
import sys


def _is_frozen() -> bool:
    # Nuitka injects __compiled__ into each compiled module's globals.
    return hasattr(sys, "frozen") or "__compiled__" in globals()


def _outer_exe_dir() -> str:
    """
    Return the directory that contains the outer (user-facing) exe.

    In Nuitka onefile mode the bootstrap exe preserves the original command
    line, so sys.argv[0] holds the outer exe path even while sys.executable
    points to the inner extracted exe.
    """
    if _is_frozen():
        if sys.argv and sys.argv[0]:
            return os.path.dirname(os.path.abspath(sys.argv[0]))
        # Fallback (should not normally happen)
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(*parts: str) -> str:
    """Absolute path to a read-only asset file or directory."""
    return os.path.join(_outer_exe_dir(), *parts)


def data_path(*parts: str) -> str:
    """Absolute path inside the writable data directory."""
    if _is_frozen():
        return os.path.join(_outer_exe_dir(), "data", *parts)
    return os.path.join(os.getcwd(), "data", *parts)
