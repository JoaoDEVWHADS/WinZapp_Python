"""Lifecycle cleanup for WinZapp's per-session PulseAudio modules."""

from __future__ import annotations

import os
import shutil
import subprocess


PULSE_SERVER = "unix:/run/pulse/winzapp-native"
WINZAPP_PREFIX = "winzapp_"


def _pactl_environment() -> dict[str, str]:
    env = os.environ.copy()
    env["PULSE_SERVER"] = PULSE_SERVER
    return env


def cleanup_winzapp_pulse_modules(*, quiet: bool = False) -> int:
    """Unload every WinZapp-owned PulseAudio module.

    This is intentionally best-effort: it is called by shutdown/cleanup
    scripts, and must also succeed when PulseAudio is not installed (Windows)
    or is already stopped. Only module names beginning with ``winzapp_`` are
    touched; the system PulseAudio service and unrelated applications remain
    untouched.
    """
    if os.name == "nt" or shutil.which("pactl") is None:
        return 0
    env = _pactl_environment()
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "modules"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return 0
    if result.returncode != 0:
        return 0

    module_ids: list[str] = []
    for line in result.stdout.splitlines():
        fields = line.split(None, 2)
        if len(fields) < 3:
            continue
        # Module arguments contain sink_name/source_name for our virtual
        # devices. Unloading in reverse order removes remap sources before
        # their backing sinks.
        if "winzapp_" in fields[2]:
            module_ids.append(fields[0])

    removed = 0
    for module_id in reversed(module_ids):
        unload = subprocess.run(
            ["pactl", "unload-module", module_id],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if unload.returncode == 0:
            removed += 1
    if not quiet and removed:
        print(f"Removed {removed} WinZapp PulseAudio module(s).")
    return removed

