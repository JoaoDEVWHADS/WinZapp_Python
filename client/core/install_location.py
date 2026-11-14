"""Whether WinZapp is running from a network folder where it cannot work.

WinZapp keeps its data, the WPPConnect Server it installs with npm and the
Chrome profile holding the WhatsApp login next to the program (app_paths).
From a UNC path (\\\\server\\share\\...) the install cannot even finish, and
the failure a user sees explains nothing: `npm install` runs package install
scripts through cmd.exe, which refuses a UNC path as its current directory,
falls back to C:\\Windows, and the script is then "not found". Reported from
a Windows 11 ARM machine in Parallels, whose Downloads folder is the Mac's
(\\\\Mac\\Home\\Downloads): a wall of npm output, twice, and no WinZapp.

Only a UNC path is refused. A drive letter mapped to a share (a VirtualBox
shared folder, a company H: drive) is left alone on purpose: cmd.exe accepts
it, people already run WinZapp from one, and refusing it would close WinZapp
on them at the next start — before the updater, so no later fix could reach
them either.

The fix for the user is to install it (WinZappInstaller puts it under
%LOCALAPPDATA%) or move the folder to a local disk; this module only answers
the question, so MainWindow can say so before anything is installed.
"""

from __future__ import annotations


def is_unc_path(path: str) -> bool:
    """True for \\\\server\\share\\..., //server/share/... or \\\\?\\UNC\\...;
    False for a drive letter (mapped or not) and for \\\\?\\C:\\..."""
    if not path:
        return False
    norm = str(path).replace("/", "\\")
    upper = norm.upper()
    if upper.startswith("\\\\?\\UNC\\"):
        return True
    if upper.startswith("\\\\?\\") or upper.startswith("\\\\.\\"):
        return False
    return norm.startswith("\\\\")
