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
import time

# Long enough to catch a spawn that fails almost immediately (missing DLL,
# corrupted install, blocked by antivirus) without noticeably freezing the
# UI for what is otherwise a rare, deliberate user action.
_SPAWN_VERIFY_DELAY = 0.3


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
                      frozen: bool | None = None) -> str:
    """Switch to ``account_id``: activate its running process if any, else spawn.

    Returns "activated" if an existing process answered the IPC request,
    "spawned" if a new process was started and either was still running a
    moment later or had already exited cleanly (see the poll() check for why
    exit code 0 counts as success), or "failed" if the spawn itself raised or
    the process died with a nonzero code almost immediately (missing DLL,
    corrupted install, blocked by
    antivirus). Before this, both "spawned fine" and "failed to spawn" were
    the same plain False — a caller had no way to tell a genuine failure
    apart from a normal spawn, so a crashed target silently left the user
    with no indication the switch never actually happened. The current
    window stays open (1b) unless the caller decides otherwise.
    """
    import ipc

    if ipc.request_activate(global_dir, account_id, source="user"):
        return "activated"
    if frozen is None:
        frozen = getattr(sys, "frozen", False)
    try:
        proc = subprocess.Popen(build_launch_command(
            sys.argv[0], sys.executable, account_id, frozen, startup_source="user"))
    except Exception:
        logging.exception("[switch_to_account] failed to spawn %s", account_id)
        return "failed"

    time.sleep(_SPAWN_VERIFY_DELAY)
    # A clean exit is NOT a failure. The spawned process legitimately exits 0
    # when it loses the single-instance race: it fails to take the mutex,
    # forwards its own ipc.request_activate() and quits (see main.py's
    # startup path). That happens exactly when our request_activate above
    # lost to a stale socket or a busy target — i.e. the switch DID work, and
    # reporting "failed" there would show the user an error box on top of a
    # window that just came to the front. Only a nonzero code means the
    # process actually died on us (missing DLL, corrupted install, AV block).
    if proc.poll() not in (None, 0):
        logging.error(
            "[switch_to_account] %s exited immediately after spawning (code=%s)",
            account_id, proc.returncode,
        )
        return "failed"
    return "spawned"
