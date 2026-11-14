"""macOS versions of client/autostart.py's Windows-only functions.

Single instance: an exclusive flock on a lock file inside the account's
data folder (the Windows code keys its named mutex on data_path() too), held
for the life of the process — the kernel drops it when the process dies, so
a crash never leaves a stale lock behind.

Autostart: a per-user LaunchAgent that runs WinZapp with --background at
login, the equivalent of the HKCU Run value.
"""

import fcntl
import os
import plistlib
import subprocess
import sys


def _label():
    """The app's bundle identifier (set at build time), so each build's
    login item is its own; a development run uses the default."""
    try:
        from Foundation import NSBundle
        ident = NSBundle.mainBundle().bundleIdentifier()
        if ident and getattr(sys, "frozen", False):
            return str(ident)
    except Exception:
        pass
    return "com.winzapp.macos"


LABEL = _label()
PLIST = os.path.expanduser(f"~/Library/LaunchAgents/{LABEL}.plist")

_lock_fh = None


def acquire_single_instance_mutex() -> bool:
    global _lock_fh
    from app_paths import data_path
    path = os.path.join(data_path(), ".instance.lock")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = open(path, "a+")
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    except OSError:
        return True  # can't lock (odd filesystem): behave like first instance
    _lock_fh = fh
    return True


def _program_arguments():
    if getattr(sys, "frozen", False):
        return [sys.executable, "--background"]
    launcher = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "launcher.py")
    return [sys.executable, launcher, "--background"]


def get_autostart_command() -> str:
    return " ".join(f'"{a}"' for a in _program_arguments())


def is_autostart_enabled() -> bool:
    return os.path.exists(PLIST)


def enable_autostart() -> None:
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    with open(PLIST, "wb") as fh:
        plistlib.dump({
            "Label": LABEL,
            "ProgramArguments": _program_arguments(),
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }, fh)


def disable_autostart() -> None:
    if os.path.exists(PLIST):
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"],
                       capture_output=True)
        os.remove(PLIST)


def activate_existing_window() -> None:
    # Superseded by ipc.request_activate(); kept so callers don't break.
    pass


def install():
    import autostart
    autostart.acquire_single_instance_mutex = acquire_single_instance_mutex
    autostart.get_autostart_command = get_autostart_command
    autostart.is_autostart_enabled = is_autostart_enabled
    autostart.enable_autostart = enable_autostart
    autostart.disable_autostart = disable_autostart
    autostart.activate_existing_window = activate_existing_window
