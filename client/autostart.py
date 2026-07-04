"""
Windows autostart-registry helpers and single-instance management for WinZapp.

Registry key used for autostart:
    HKCU\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run  →  "WinZapp"

Single-instance mutex:
    Named mutex "Global\\WinZappSingleInstance" is acquired in the first
    instance and checked in subsequent launches.
"""

import os
import sys
import hashlib
from app_paths import data_path

_AUTORUN_KEY  = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_AUTORUN_NAME = "WinZapp"

def _get_dynamic_mutex_name() -> str:
    try:
        path_hash = hashlib.md5(data_path().encode("utf-8")).hexdigest()
        return f"Global\\WinZappSingleInstance_{path_hash}"
    except Exception:
        return "Global\\WinZappSingleInstance"

# The module-level handle must stay alive for the lifetime of the process;
# Windows releases the mutex when the process exits or the handle is closed.
_mutex_handle = None


# ── Command-line string ───────────────────────────────────────────────────────

def get_autostart_command() -> str:
    """
    Return the command that should be stored in the Run registry value.

    * Compiled (Nuitka/PyInstaller): ``"WinZapp.exe" --background``
    * Development:                   ``"python.exe" "main.py" --background``
    """
    argv0 = os.path.abspath(sys.argv[0])
    # Detect compiled binary: sys.frozen is set by PyInstaller/cx_Freeze,
    # or argv[0] itself is an .exe (Nuitka standalone).
    if getattr(sys, "frozen", False) or argv0.lower().endswith(".exe"):
        return f'"{argv0}" --background'
    else:
        # Source-code run — interpreter + script
        return f'"{sys.executable}" "{argv0}" --background'


# ── Registry helpers ──────────────────────────────────────────────────────────

def is_autostart_enabled() -> bool:
    """Return True if a WinZapp entry exists in the current-user Run key."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_READ
        )
        winreg.QueryValueEx(key, _AUTORUN_NAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def enable_autostart() -> None:
    """
    Write the WinZapp Run registry value.

    Raises ``OSError`` (or a subclass) if the key cannot be written — the
    caller is responsible for showing a user-facing error message.
    """
    import winreg
    cmd = get_autostart_command()
    key = winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE
    )
    winreg.SetValueEx(key, _AUTORUN_NAME, 0, winreg.REG_SZ, cmd)
    winreg.CloseKey(key)


def disable_autostart() -> None:
    """Remove the WinZapp Run registry value (silently ignores missing entries)."""
    import winreg
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _AUTORUN_KEY, 0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(key, _AUTORUN_NAME)
        winreg.CloseKey(key)
    except OSError:
        pass


# ── Single-instance helpers ───────────────────────────────────────────────────

def acquire_single_instance_mutex() -> bool:
    """
    Attempt to create and own the named mutex.

    Returns ``True``  — this is the first (and only) running instance.
    Returns ``False`` — another instance already holds the mutex.
    """
    import ctypes
    global _mutex_handle
    mutex_name = _get_dynamic_mutex_name()
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    # ERROR_ALREADY_EXISTS (183) means a second instance tried to create the mutex
    return ctypes.windll.kernel32.GetLastError() != 183


def activate_existing_window() -> None:
    """
    Enumerate top-level windows, find one whose title starts with "WinZapp",
    restore it (in case it is hidden or minimised), and bring it to the
    foreground.  Safe to call even if no matching window is found.
    """
    import ctypes
    from ctypes import wintypes

    found = [0]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _enum_proc(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
        if buf.value.startswith("WinZapp"):
            found[0] = hwnd
            return False   # stop enumeration
        return True        # keep going

    ctypes.windll.user32.EnumWindows(_enum_proc, 0)

    if found[0]:
        SW_SHOW = 5
        ctypes.windll.user32.ShowWindow(found[0], SW_SHOW)
        ctypes.windll.user32.SetForegroundWindow(found[0])
