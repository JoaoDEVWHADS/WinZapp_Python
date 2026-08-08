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


# ── Active-account state (multi-account scoping) ─────────────────────────────
# Set exactly once, very early in __main__ (see account_bootstrap), BEFORE any
# data_path()/log_path() call. When an account is active, per-account data lives
# under <writable>/data/accounts/<id>/; global data under <writable>/data/global/.
#
# Strict bootstrap: if no account is set, data_path()/log_path() raise, so a
# start-ordering bug can never silently make two processes share one flat data
# dir. The only exception is the legacy-flat opt-in, used by the migration and
# by pre-existing tests that address the historical flat layout directly.
_active_account_id = None
_allow_legacy_flat = False


def set_active_account(account_id):
    global _active_account_id
    _active_account_id = account_id


def active_account_id():
    return _active_account_id


def set_allow_legacy_flat(value):
    """Opt into the historical flat data/ layout (migration + legacy tests)."""
    global _allow_legacy_flat
    _allow_legacy_flat = bool(value)


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


def _writable_base_dir() -> str:
    """Return the directory external writable data/logs live under when frozen."""
    if hasattr(sys, "_MEIPASS"):
        return os.path.dirname(sys.executable)
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.path.dirname(sys.executable)


def _data_root() -> str:
    """The writable 'data' directory root (holds global/ and accounts/)."""
    if _is_frozen():
        return os.path.join(_writable_base_dir(), "data")
    return os.path.join(os.getcwd(), "data")


def global_dir(*parts: str) -> str:
    """Absolute path inside the GLOBAL (per-install) data directory.

    Holds cross-account state: accounts.json, app.json, node_coord/, locks,
    migration.journal, bootstrap.log. Never requires an active account.
    """
    return os.path.join(_data_root(), "global", *parts)


def accounts_root(*parts: str) -> str:
    """Absolute path inside the accounts/ root (sibling of global/)."""
    return os.path.join(_data_root(), "accounts", *parts)


def bootstrap_log_path() -> str:
    """Log used during bootstrap, BEFORE an account is chosen (global)."""
    return os.path.join(global_dir(), "bootstrap.log")


def _account_dir() -> str:
    """Resolve the current process's per-account data dir, or handle legacy.

    Strict bootstrap: raises RuntimeError if no account is active, unless the
    legacy-flat opt-in is set (migration / pre-existing flat-layout tests),
    in which case the historical flat <data>/ dir is returned.
    """
    if _active_account_id is not None:
        return os.path.join(_data_root(), "accounts", _active_account_id)
    if _allow_legacy_flat:
        return _data_root()
    raise RuntimeError(
        "app_paths: no active account set (call set_active_account() during "
        "bootstrap, or set_allow_legacy_flat(True) for migration/legacy)"
    )


def data_path(*parts: str) -> str:
    """Absolute path inside the CURRENT ACCOUNT's writable data directory."""
    return os.path.join(_account_dir(), *parts)


def log_path(*parts: str) -> str:
    """Absolute path inside the current account's logs directory.

    Legacy flat layout keeps the historical top-level 'logs' dir; per-account
    layout nests logs under accounts/<id>/logs/.
    """
    if _active_account_id is None and _allow_legacy_flat:
        if _is_frozen():
            return os.path.join(_writable_base_dir(), "logs", *parts)
        return os.path.join(os.getcwd(), "logs", *parts)
    return os.path.join(_account_dir(), "logs", *parts)
