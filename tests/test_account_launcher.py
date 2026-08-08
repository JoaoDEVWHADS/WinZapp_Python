"""Tests for client/account_launcher.py — spawn command construction (pure)."""

from account_launcher import build_launch_command

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
