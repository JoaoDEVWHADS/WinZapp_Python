import subprocess

from core import app_restart


def test_a_frozen_restart_repeats_the_arguments_less_the_transient_ones():
    command = app_restart.restart_command(
        r"C:\W\WinZapp.exe", [r"C:\W\WinZapp.exe", "--account", "2", "--background", "--post-update"], True)
    assert command == [r"C:\W\WinZapp.exe", "--account", "2"]


def test_a_source_restart_runs_the_script_with_the_interpreter():
    command = app_restart.restart_command(r"C:\py\python.exe", ["main.py", "--x"], False)
    assert command[0] == r"C:\py\python.exe" and command[1].endswith("main.py") and command[2:] == ["--x"]


def test_a_console_script_launcher_is_started_by_itself():
    command = app_restart.restart_command(r"C:\py\python.exe", [r"C:\v\winzapp.exe", "--x"], False)
    assert command[0].endswith("winzapp.exe") and command[1:] == ["--x"]


def test_the_script_waits_for_the_pid_then_starts_the_program(tmp_path):
    script = app_restart.build_restart_script(
        4242, [r"C:\Program Files\W\WinZapp.exe", "--account", "2"], str(tmp_path / "log.txt"), passes=7)
    assert 'tasklist /FI "PID eq 4242"' in script
    assert 'start "" "C:\\Program Files\\W\\WinZapp.exe" "--account" "2"' in script
    assert "GEQ 7" in script
    assert "timeout" not in script and "ping -n 2" in script
    # the program is only started after the wait, never in the give-up branch
    assert script.index(":RESTART") < script.index('start ""') < script.index(":GAVE_UP")


def test_special_characters_stay_literal_in_the_start_line():
    script = app_restart.build_restart_script(1, [r"C:\A&B 100%\Win^Zapp!.exe"])
    assert 'start "" "C:\\A&B 100%%\\Win^Zapp!.exe"' in script
    assert "EnableDelayedExpansion" not in script


def test_the_launch_is_hidden_with_a_console_for_the_script(tmp_path):
    seen = {}

    def popen(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs

    path = tmp_path / "restart.bat"
    assert app_restart.start_restart_waiter(
        str(path), 1, ["WinZapp.exe"], environment={"PATH": "x", "_PYI_APPLICATION_HOME_DIR": "y"},
        popen=popen)
    assert path.read_text(encoding="ascii").startswith("@echo off")
    assert seen["args"][:2] == ["cmd.exe", "/c"]
    assert "_PYI_APPLICATION_HOME_DIR" not in seen["kwargs"]["env"]
    assert "stdin" not in seen["kwargs"]
    assert seen["kwargs"]["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0) == 0


def test_a_launch_that_cannot_start_reports_false(tmp_path):
    def popen(*args, **kwargs):
        raise OSError("no")

    assert app_restart.start_restart_waiter(str(tmp_path / "r.bat"), 1, ["x"], popen=popen) is False


def test_a_script_that_cannot_be_written_reports_false(tmp_path, monkeypatch):
    import updater
    monkeypatch.setattr(updater, "_write_installer_script", lambda path, script: False)
    started = []
    assert app_restart.start_restart_waiter(
        str(tmp_path / "r.bat"), 1, ["x"], popen=lambda *a, **k: started.append(a)) is False
    assert started == []
