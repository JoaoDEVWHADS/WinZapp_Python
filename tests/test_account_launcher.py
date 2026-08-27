"""Tests for client/account_launcher.py — spawn command construction (pure)
plus switch_to_account()'s activate-or-spawn decision and spawn-failure
detection.

Before this change, switch_to_account() returned a plain bool that only
ever distinguished "activated an existing process" from everything else —
a Popen() that raised outright and a spawn that started fine were both the
same False, so a caller had no way to tell a genuine failure (missing DLL,
corrupted install, blocked by antivirus) apart from a normal spawn. It now
returns one of three strings ("activated"/"spawned"/"failed"), verified by
polling the spawned process a moment after starting it — see the function's
own docstring.

ipc.request_activate and subprocess.Popen are the only I/O this function
does; both are monkeypatched so these tests need no real second process or
IPC listener.
"""

import subprocess

import pytest

import account_launcher
import ipc
from account_launcher import build_launch_command, switch_to_account

A = "a" * 32


def test_frozen_command():
    cmd = build_launch_command("C:/app/WinZapp.exe", "C:/py/python.exe", A,
                               frozen=True, startup_source="user")
    assert cmd[0] == "C:/app/WinZapp.exe"
    assert "--account" in cmd and A in cmd
    assert "--startup-source" in cmd and "user" in cmd
    assert "--background" not in cmd


def test_frozen_background():
    cmd = build_launch_command("C:/app/WinZapp.exe", "C:/py/python.exe", A,
                               frozen=True, startup_source="autostart", background=True)
    assert cmd[0] == "C:/app/WinZapp.exe"
    assert "--background" in cmd
    assert cmd[cmd.index("--startup-source") + 1] == "autostart"


def test_dev_command_uses_interpreter_and_script():
    cmd = build_launch_command("/repo/client/main.py", "/usr/bin/python3", A,
                               frozen=False, startup_source="user")
    assert cmd[0] == "/usr/bin/python3"
    assert "/repo/client/main.py" in cmd
    assert cmd[cmd.index("--account") + 1] == A


def test_account_value_follows_flag():
    cmd = build_launch_command("x.exe", "py", A, frozen=True, startup_source="user")
    assert cmd[cmd.index("--account") + 1] == A


class _FakeProcess:
    def __init__(self, exit_code=None):
        self.returncode = exit_code

    def poll(self):
        return self.returncode


@pytest.fixture(autouse=True)
def _no_real_delay(monkeypatch):
    """The spawn-verification sleep is real production behaviour (give a
    just-spawned process a moment before polling it) but would make every
    test here pay its cost for nothing — there is no real process on the
    other end."""
    monkeypatch.setattr(account_launcher.time, "sleep", lambda *_a, **_k: None)


class TestSwitchToAccount:
    def test_an_already_running_process_is_activated_not_spawned(self, monkeypatch):
        monkeypatch.setattr(ipc, "request_activate", lambda *a, **k: True)
        monkeypatch.setattr(
            subprocess, "Popen",
            lambda *a, **k: pytest.fail("should not spawn when activation succeeds"),
        )

        assert switch_to_account("gd", A) == "activated"

    def test_a_healthy_spawn_that_is_still_running_reports_spawned(self, monkeypatch):
        monkeypatch.setattr(ipc, "request_activate", lambda *a, **k: False)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProcess(exit_code=None))

        assert switch_to_account("gd", A, frozen=True) == "spawned"

    def test_popen_raising_reports_failed(self, monkeypatch):
        monkeypatch.setattr(ipc, "request_activate", lambda *a, **k: False)

        def _raise(*a, **k):
            raise OSError("no such file")
        monkeypatch.setattr(subprocess, "Popen", _raise)

        assert switch_to_account("gd", A, frozen=True) == "failed"

    def test_a_process_that_exits_immediately_reports_failed(self, monkeypatch):
        """The case this fix actually closes: Popen() itself succeeded, but
        the child crashed (missing DLL, corrupted install, blocked by
        antivirus) before this function ever gets a chance to say so."""
        monkeypatch.setattr(ipc, "request_activate", lambda *a, **k: False)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProcess(exit_code=1))

        assert switch_to_account("gd", A, frozen=True) == "failed"
