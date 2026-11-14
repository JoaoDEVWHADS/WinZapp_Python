"""Restart WinZapp from itself: a small batch waits for this process to end,
then starts the same program again with the same arguments. Used when a
change (the connection engine chosen in the pairing dialog) is only picked up
by a fresh start. Pure builders here; the caller launches the script."""

import os
import subprocess
import sys

#: Arguments of this run that must not follow it into the next one.
TRANSIENT_ARGUMENTS = ("--post-update", "--background")

#: How many one-second checks the script makes before giving up (it never
#: starts a second copy over a process that refuses to end). Longer than the
#: 150 s a graceful quit may take.
WAIT_PASSES = 240


def restart_command(executable: str, argv, frozen: bool) -> list:
    """The command line of the next run: this program with this run's
    arguments, less the transient ones."""
    kept = [a for a in list(argv)[1:] if a not in TRANSIENT_ARGUMENTS]
    if frozen:
        return [executable] + kept
    if str(argv[0]).lower().endswith(".exe"):      # a console-script launcher (uv run winzapp)
        return [os.path.abspath(argv[0])] + kept
    return [executable, os.path.abspath(argv[0])] + kept


def quote(argument: str) -> str:
    """One argument for a batch line: quoted, so & ^ ( ) and spaces are
    literal; % is doubled because a batch expands it even inside quotes. The
    script runs without delayed expansion, so ! is literal too."""
    return '"' + argument.replace("%", "%%").replace('"', '""') + '"'


def build_restart_script(pid: int, command: list, log_path: str = "",
                         passes: int = WAIT_PASSES) -> str:
    """The batch text: wait until ``pid`` is gone, then start ``command``."""
    line = " ".join(quote(part) for part in command)

    def note(text):
        return f">> {quote(log_path)} echo {text}\n" if log_path else ""

    return (
        "@echo off\n"
        "set /a WAITED=0\n"
        ":WAIT\n"
        f'tasklist /FI "PID eq {pid}" 2>NUL | find "{pid}" >NUL\n'
        "if errorlevel 1 goto RESTART\n"
        "set /a WAITED+=1\n"
        f"if %WAITED% GEQ {passes} goto GAVE_UP\n"
        # ping, not timeout: timeout refuses a script without console input
        "ping -n 2 127.0.0.1 >NUL\n"
        "goto WAIT\n"
        ":RESTART\n"
        + note("restarting WinZapp") +
        f'start "" {line}\n'
        'del "%~f0"\n'
        "goto :EOF\n"
        ":GAVE_UP\n"
        + note("the previous run did not end - not restarting") +
        'del "%~f0"\n'
        "exit /b 1\n"
    )


def start_restart_waiter(script_path: str, pid: int, command: list, log_path: str = "",
                         environment=None, popen=subprocess.Popen) -> bool:
    """Write and launch the script, hidden. True when it was started; False
    when it could not be written (a path cmd.exe cannot read back) or started."""
    import updater
    from update_relaunch import relaunch_environment

    safe_command = [updater._console_safe_path(part) if os.path.isabs(part) else part
                    for part in command]
    script = build_restart_script(
        pid, safe_command, updater._console_safe_path(log_path) if log_path else "")
    try:
        if not updater._write_installer_script(script_path, script):
            return False
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                 | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        popen(["cmd.exe", "/c", updater._console_safe_path(script_path)],
              env=relaunch_environment(os.environ if environment is None else environment),
              creationflags=flags, close_fds=True)
        return True
    except (OSError, ValueError):
        return False


def restart_this_program(script_path: str, log_path: str = "") -> bool:
    """Arrange the restart of the running program (see the module docstring)."""
    return start_restart_waiter(
        script_path, os.getpid(),
        restart_command(sys.executable, sys.argv, bool(getattr(sys, "frozen", False))), log_path)
