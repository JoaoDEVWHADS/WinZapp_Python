"""The update that installs when the app ends (macos/winzapp_mac/install_on_quit.py).

Plain functions that take what sparkle_mac knows as arguments, so they run on
every platform against fakes and a temporary folder. sparkle_mac's own wiring
is tested on the Mac in macos/tests/test_sparkle_mac.py. Nothing here starts
a process: subprocess is replaced.
"""

import os
import pathlib
import sys

import pytest

_MACOS = pathlib.Path(__file__).resolve().parents[1] / "macos"

pytestmark = pytest.mark.skipif(not (_MACOS / "winzapp_mac" / "install_on_quit.py").is_file(),
                                reason="no macOS layer in this checkout")

if str(_MACOS) not in sys.path:
    sys.path.insert(0, str(_MACOS))

from winzapp_mac import install_on_quit as Q  # noqa: E402
from winzapp_mac import update_accounts as A  # noqa: E402

TAG = "v2.1.0.4500alpha"
RUNNING = "v2.1.0.4400alpha"


class _Window:
    def __init__(self, global_dir):
        self.global_dir = global_dir
        self.spoken, self.quit_all = [], []
        self.i18n = type("I", (), {"t": staticmethod(lambda key: key)})()

    def output(self, text, interrupt=False):
        self.spoken.append(text)

    def quit_all_accounts(self):
        self.quit_all.append(True)


class TestRecord:
    def test_no_global_dir_means_no_record(self, tmp_path):
        mw = _Window(None)
        assert Q.armed_path(mw) == ""
        Q.record_armed(mw, TAG)           # must not raise
        Q.forget_armed(mw)

    def test_a_recorded_tag_is_read_back_and_forgotten(self, tmp_path):
        mw = _Window(str(tmp_path))
        Q.record_armed(mw, TAG)
        assert (tmp_path / A.ARMED_FILE).exists()
        assert Q.armed_install(mw, RUNNING, lambda: True) == TAG
        Q.forget_armed(mw)
        assert not (tmp_path / A.ARMED_FILE).exists()

    @pytest.mark.parametrize("tag, running, want", [
        (TAG, True, TAG),
        (TAG, None, TAG),               # launchd could not be asked: the record counts
        (TAG, False, ""),               # cancelled or finished
        (RUNNING, True, ""),            # installed: the app runs it now
    ])
    def test_a_record_counts_only_while_it_holds(self, tmp_path, tag, running, want):
        mw = _Window(str(tmp_path))
        Q.record_armed(mw, tag)
        assert Q.armed_install(mw, RUNNING, lambda: running) == want
        assert (tmp_path / A.ARMED_FILE).exists() is bool(want)

    def test_without_a_record_launchd_is_not_asked(self, tmp_path):
        assert Q.armed_install(_Window(str(tmp_path)), RUNNING,
                               lambda: pytest.fail("asked launchd")) == ""

    def test_a_corrupt_record_is_dropped(self, tmp_path):
        (tmp_path / A.ARMED_FILE).write_text("{not json", encoding="utf-8")
        assert Q.armed_install(_Window(str(tmp_path)), RUNNING, lambda: True) == ""
        assert not (tmp_path / A.ARMED_FILE).exists()


class TestInstallerJob:
    def test_launchd_is_asked_about_sparkles_installer_job(self, monkeypatch):
        asked = []

        class Done:
            returncode, stdout = 0, '{\n\t"PID" = 4242;\n};'
        monkeypatch.setattr(Q.subprocess, "run", lambda cmd, **kw: asked.append(cmd) or Done())
        job = Q.installer_job({"CFBundleIdentifier": "com.example.winzapp"})
        assert job == "com.example.winzapp-sparkle-updater"
        assert Q.installer_running(job) is True
        assert asked == [["launchctl", "list", job]]

    def test_launchd_failing_is_unknown_not_false(self, monkeypatch):
        monkeypatch.setattr(Q.subprocess, "run", lambda cmd, **kw: 1 / 0)
        assert Q.installer_running("job") is None


class TestEndAll:
    def _end(self, mw, armed=TAG, others=("acc2", "acc3")):
        return Q.end_all(mw, lambda m: armed, lambda m: list(others),
                         lambda: "com.example.winzapp-sparkle-updater", lambda: "/app/winzapp")

    def test_ending_one_account_ends_them_all_and_reopens_the_others(self, monkeypatch):
        mw = _Window("x")
        spawned = []
        monkeypatch.setattr(Q.subprocess, "Popen",
                            lambda cmd, **kw: spawned.append((cmd, kw.get("start_new_session"))))
        assert self._end(mw) is True
        assert mw.quit_all == [True] and mw.spoken == ["update_closing_other_accounts"]
        (cmd, detached), = spawned
        assert detached is True and cmd[:2] == ["/bin/sh", "-c"]
        assert cmd[-2:] == ["acc2", "acc3"] and "com.example.winzapp-sparkle-updater" in cmd
        assert str(os.getpid()) in cmd
        # quit_all_accounts() comes back to real_exit() once the others are gone
        assert self._end(mw) is False and len(spawned) == 1

    @pytest.mark.parametrize("armed, others", [("", ["acc2"]), (TAG, [])])
    def test_otherwise_only_this_account_ends(self, monkeypatch, armed, others):
        mw = _Window("x")
        monkeypatch.setattr(Q.subprocess, "Popen", lambda cmd, **kw: pytest.fail("spawned"))
        assert self._end(mw, armed, others) is False and mw.quit_all == []

    def test_a_failure_lets_this_account_end_as_it_would(self):
        def boom(mw):
            raise RuntimeError
        assert Q.end_all(_Window("x"), boom, lambda m: [], lambda: "", lambda: "") is False
