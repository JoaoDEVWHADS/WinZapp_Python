"""
Per-account process launcher for WinZapp multi-account (client/account_launcher.py)
===================================================================================

Builds the argv to (re)launch WinZapp bound to a specific account, and drives
the activation-first switch (plan Zad 4.1): to switch accounts we first ask an
already-running process for that account to come to the foreground via IPC, and
only spawn a fresh process if none is running. last_foreground is NOT set here —
the target process sets it after its window is ready (GPT r4 #4 / r6 #2).

build_launch_command is pure (no wx / no spawn) so it is unit-tested directly.
"""

from __future__ import annotations

import logging
import subprocess
import sys


def build_launch_command(argv0: str, executable: str, account_id: str,
                         frozen: bool, startup_source: str = "user",
                         background: bool = False) -> list[str]:
    """Return the argv list to launch WinZapp for ``account_id``.

    Mirrors autostart.get_autostart_command(): a frozen build launches the exe
    directly; a source checkout launches the interpreter + main.py. Always
    carries --account and --startup-source; --background only when requested.
    """
    if frozen:
        cmd = [argv0]
    else:
        cmd = [executable, argv0]
    cmd += ["--account", account_id, "--startup-source", startup_source]
    if background:
        cmd.append("--background")
    return cmd


def switch_to_account(global_dir: str, account_id: str,
                      frozen: bool | None = None) -> bool:
    """Switch to ``account_id``: activate its running process if any, else spawn.

    Returns True if an existing process was activated, False if a new one was
    spawned (or spawn failed — see log). The current window stays open (1b).
    """
    import ipc

    if ipc.request_activate(global_dir, account_id, source="user"):
        return True
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    try:
        subprocess.Popen(build_launch_command(
            sys.argv[0], sys.executable, account_id, frozen, startup_source="user"))
    except Exception:
        logging.exception("[switch_to_account] failed to spawn %s", account_id)
    return False
