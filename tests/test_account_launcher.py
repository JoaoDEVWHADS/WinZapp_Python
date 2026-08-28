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

    def test_a_clean_exit_is_not_a_failure(self, monkeypatch):
        """Exit code 0 means the child lost the single-instance race: it could
        not take the mutex, forwarded its own ipc.request_activate() and quit.
        That happens precisely when our own request_activate lost to a stale
        socket or a busy target — so the switch DID work, and calling it
        "failed" would put an error box on top of a window that just came to
        the front."""
        monkeypatch.setattr(ipc, "request_activate", lambda *a, **k: False)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: _FakeProcess(exit_code=0))

        assert switch_to_account("gd", A, frozen=True) == "spawned"


class _MainWindowStub:
    """Only what the two MainWindow methods under test actually touch.

    ConversationsPanel/MainWindow are wx classes that cannot be instantiated
    without a running wx.App, so the unbound methods are bound onto this
    plain object — the pattern the rest of this suite uses.
    """

    def __init__(self):
        self.global_dir = "gd"
        self.account_id = A
        self.app_name = "WinZapp"
        self.app_settings = None
        self.settings = {"general": {"switch_behavior": "single"}}
        self.hidden_to_tray = False
        self.message_boxes = []
        self.exited = False

    def hide_to_tray(self):
        self.hidden_to_tray = True

    def real_exit(self):
        self.exited = True

    class _I18n:
        @staticmethod
        def t(key):
            return "{app_name} Error" if key == "error" else key

    i18n = _I18n()


@pytest.fixture
def stub(monkeypatch):
    """Bind the two real methods onto the stub and neutralise wx."""
    import main

    s = _MainWindowStub()
    monkeypatch.setattr(
        main.wx, "MessageBox",
        lambda msg, caption="", style=0, *a, **k: s.message_boxes.append(msg),
    )
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    s._switch_to_account = main.MainWindow._switch_to_account.__get__(s)
    s._offer_switch_when_unpaired = main.MainWindow._offer_switch_when_unpaired.__get__(s)
    return s


class TestAFailedSwitchIsVisibleAndNonDestructive:
    """The behaviour this PR actually delivers to the user. switch_to_account()
    returning "failed" is only useful if the callers act on it — and both of
    them previously did something irreversible on the assumption the switch
    had worked."""

    def test_a_failed_switch_does_not_hide_to_tray(self, stub, monkeypatch):
        """Hiding into a switch that never happened leaves the user with no
        visible window and no idea why the button did nothing."""
        import main
        monkeypatch.setattr(main, "switch_to_account", lambda *a, **k: "failed",
                            raising=False)
        monkeypatch.setattr(account_launcher, "switch_to_account",
                            lambda *a, **k: "failed")

        stub._switch_to_account("b" * 32)

        assert stub.hidden_to_tray is False
        assert stub.message_boxes, "the user must be told the switch failed"

    def test_a_successful_switch_still_hides_to_tray(self, stub, monkeypatch):
        """The guard must not cost the normal path its behaviour."""
        monkeypatch.setattr(account_launcher, "switch_to_account",
                            lambda *a, **k: "spawned")

        stub._switch_to_account("b" * 32)

        assert stub.hidden_to_tray is True
        assert not stub.message_boxes
