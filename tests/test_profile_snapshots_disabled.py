"""Settings > Cópia de segurança: "keep no profile backups".

For someone who would rather re-pair after a broken Chrome profile than give
its restore point 1-2 GB of disk. Off by default. On: no snapshot at a clean
close, none while WinZapp is open, and the ones already on disk are offered
for deletion — only this account's, since the snapshot folder is shared by
every account on the install.
"""

import os
import types

import pytest
import wx

from core import profile_recovery
from core.profile_backup import live_snapshot_policy, size_text, snapshots_disabled
from main import MainWindow
from main_window import session_lifecycle
from tests.test_profile_recovery_wiring import _Stub as _CloseStub
from ui.dialogs import settings_dialog
from ui.dialogs.settings_dialog import SettingsDialog


def _off(value=True, **extra):
    return {"profile_backup": {"snapshots_disabled": value, **extra}}


class TestThePolicy:
    def test_off_by_default(self):
        assert snapshots_disabled({}) is False
        assert snapshots_disabled({"profile_backup": {}}) is False

    def test_only_an_explicit_true_turns_it_on(self):
        """A hand-edited value must never delete a restore point by accident."""
        assert snapshots_disabled(_off(True)) is True
        for value in ("yes", 1, "true", None):
            assert snapshots_disabled(_off(value)) is False

    def test_it_turns_the_backup_while_open_off_too(self):
        on = {"profile_backup": {"live_snapshot_enabled": True}}
        assert live_snapshot_policy(on)[0] is True
        assert live_snapshot_policy(_off(True, live_snapshot_enabled=True))[0] is False

    @pytest.mark.parametrize("num_bytes, text", [
        (2 * 1024 ** 3, "2,0 GB"), (int(1.94 * 1024 ** 3), "1,9 GB"),
        (850 * 1024 ** 2, "850 MB"), (0, "0 MB"), (None, "0 MB"),
    ])
    def test_the_size_is_said_like_this(self, num_bytes, text):
        assert size_text(num_bytes, ",") == text


def _make_generations(global_dir, session, size=10):
    base = profile_recovery.snapshot_dir(str(global_dir), session)
    for suffix in ("", ".prev", ".pending", ".partial"):
        folder = base + suffix
        os.makedirs(os.path.join(folder, "Default"), exist_ok=True)
        with open(os.path.join(folder, "Default", "data"), "wb") as f:
            f.write(b"x" * size)
    return base


class TestDeletingTheCopies:
    def test_every_generation_of_this_session_goes(self, tmp_path):
        base = _make_generations(tmp_path, "mine", size=10)

        assert profile_recovery.snapshots_size_bytes(str(tmp_path), "mine") == 40
        freed = profile_recovery.delete_snapshots(str(tmp_path), "mine")

        assert freed == 40
        for suffix in ("", ".prev", ".pending", ".partial"):
            assert not os.path.exists(base + suffix)
        assert profile_recovery.snapshots_size_bytes(str(tmp_path), "mine") == 0

    def test_another_accounts_copies_stay(self, tmp_path):
        """The snapshot folder is shared by every account on the install."""
        _make_generations(tmp_path, "mine")
        theirs = _make_generations(tmp_path, "theirs")

        profile_recovery.delete_snapshots(str(tmp_path), "mine")

        assert os.path.isdir(theirs) and os.path.isdir(theirs + ".prev")

    def test_not_while_a_copy_is_being_made(self, tmp_path):
        """Under the capture lock: a copy in progress is never deleted from
        under itself; the caller is told it did not happen."""
        base = _make_generations(tmp_path, "mine")
        with profile_recovery._CAPTURE_LOCK:
            assert profile_recovery.delete_snapshots(str(tmp_path), "mine", lock_wait=0.05) is None
        assert os.path.isdir(base)

    def test_what_a_replace_left_aside_goes_too(self, tmp_path):
        """_replace_directory() moves the old copy to `.old`; a process that
        died before sweeping it leaves a whole copy there."""
        base = _make_generations(tmp_path, "mine", size=10)
        for suffix in (".old", ".pending.old"):
            os.makedirs(base + suffix)
            with open(os.path.join(base + suffix, "data"), "wb") as f:
                f.write(b"x" * 5)

        assert profile_recovery.delete_snapshots(str(tmp_path), "mine") == 50
        assert not os.path.exists(base + ".old")
        assert not os.path.exists(base + ".pending.old")

    def test_a_delete_cut_short_never_leaves_a_restore_point_behind(self, tmp_path, monkeypatch):
        """WinZapp closed in the middle of deleting 1-2 GB: what is left must
        not sit under the snapshot's own name, recent enough to be offered as
        a restore point. The next delete finishes the job."""
        base = _make_generations(tmp_path, "mine", size=10)
        monkeypatch.setattr(profile_recovery.shutil, "rmtree", lambda *a, **kw: None)

        profile_recovery.delete_snapshots(str(tmp_path), "mine")

        assert profile_recovery.snapshot_age_seconds(str(tmp_path), "mine") is None
        assert not os.path.exists(base)
        assert os.path.isdir(base + ".deleting")

        monkeypatch.undo()
        assert profile_recovery.delete_snapshots(str(tmp_path), "mine") == 40
        assert not any(os.listdir(os.path.dirname(base)))

    def test_nothing_to_delete(self, tmp_path):
        assert profile_recovery.delete_snapshots(str(tmp_path), "mine") == 0
        assert profile_recovery.delete_snapshots(None, "mine") == 0


class TestAtClose:
    def test_a_clean_close_takes_no_copy(self, monkeypatch):
        captured = []
        monkeypatch.setattr(profile_recovery, "capture_snapshot",
                            lambda *a, **kw: captured.append(a) or True)
        stub = _CloseStub()
        stub.settings.update(_off(True))

        MainWindow._capture_profile_snapshot(stub, "sess123", True, None)

        assert captured == []
        assert any("copies turned off" in line for line in stub.audits)

    def test_with_copies_on_it_still_does(self, monkeypatch):
        captured = []
        monkeypatch.setattr(profile_recovery, "capture_snapshot",
                            lambda *a, **kw: captured.append(a) or True)
        stub = _CloseStub()
        stub.settings.update(_off(False))

        MainWindow._capture_profile_snapshot(stub, "sess123", True, None)

        assert len(captured) == 1


# ── The dialog offers to free the space ─────────────────────────────────────


class _Check:
    def __init__(self, value):
        self.value = value

    def GetValue(self):
        return self.value


class _Owner:
    """The two MainWindow methods the dialog calls, recorded."""

    def __init__(self, size):
        self.size = size
        self.deleted = 0
        self.i18n = types.SimpleNamespace(t=lambda key: "{size}" if "question" in key else ",")

    def profile_snapshots_size(self):
        return self.size

    def delete_profile_snapshots(self):
        self.deleted += 1


class _Dialog:
    _offer_to_delete_profile_snapshots = SettingsDialog._offer_to_delete_profile_snapshots

    def __init__(self, ticked, loaded, size):
        self._no_profile_snapshots_check = _Check(ticked)
        self._snapshots_disabled_loaded = loaded
        self.main_window = _Owner(size)


@pytest.fixture
def answer(monkeypatch):
    asked = []
    reply = {"value": wx.NO}

    def _box(message, title, style, parent=None):
        asked.append((message, style))
        return reply["value"]

    monkeypatch.setattr(settings_dialog.wx, "MessageBox", _box)
    return types.SimpleNamespace(asked=asked, reply=reply)


class TestTheOffer:
    def test_turning_it_on_asks_and_yes_deletes(self, answer):
        answer.reply["value"] = wx.YES
        dialog = _Dialog(ticked=True, loaded=False, size=2 * 1024 ** 3)

        dialog._offer_to_delete_profile_snapshots()

        assert answer.asked[0][0] == "2,0 GB"
        assert answer.asked[0][1] & wx.NO_DEFAULT
        assert dialog.main_window.deleted == 1

    def test_no_keeps_them(self, answer):
        dialog = _Dialog(ticked=True, loaded=False, size=1024)

        dialog._offer_to_delete_profile_snapshots()

        assert len(answer.asked) == 1 and dialog.main_window.deleted == 0

    def test_nothing_on_disk_nothing_asked(self, answer):
        dialog = _Dialog(ticked=True, loaded=False, size=0)
        dialog._offer_to_delete_profile_snapshots()
        assert answer.asked == []

    def test_already_on_when_the_dialog_opened(self, answer):
        dialog = _Dialog(ticked=True, loaded=True, size=1024)
        dialog._offer_to_delete_profile_snapshots()
        assert answer.asked == []

    def test_apply_then_ok_asks_once(self, answer):
        dialog = _Dialog(ticked=True, loaded=False, size=1024)
        dialog._offer_to_delete_profile_snapshots()   # Apply
        dialog._offer_to_delete_profile_snapshots()   # OK
        assert len(answer.asked) == 1

    def test_a_window_without_the_methods_is_never_asked(self, answer):
        """The GUI round-trip frames have no snapshots: ticking the box there
        must not open a modal box in CI."""
        dialog = _Dialog(ticked=True, loaded=False, size=1024)
        dialog.main_window = types.SimpleNamespace(i18n=dialog.main_window.i18n)
        dialog._offer_to_delete_profile_snapshots()
        assert answer.asked == []


class TestTheDeleteIsAnnounced:
    class _Window:
        delete_profile_snapshots = MainWindow.delete_profile_snapshots
        _live_snapshot_session = MainWindow._live_snapshot_session

        def __init__(self):
            self.token = "sess123:tok"
            self.global_dir = "/g"
            self.spoken = []
            self.i18n = types.SimpleNamespace(
                t=lambda key: (key + " {size}") if key == "profile_backup_deleted" else (
                    "," if key == "decimal_separator" else key))

        def output(self, text, interrupt=False):
            self.spoken.append((text, interrupt))

    @pytest.fixture(autouse=True)
    def _inline(self, monkeypatch):
        class _Thread:
            def __init__(self, target=None, **_kw):
                self._target = target

            def start(self):
                self._target()

        monkeypatch.setattr(session_lifecycle.threading, "Thread", _Thread)
        monkeypatch.setattr(session_lifecycle.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))

    def test_it_says_how_much_was_freed_without_interrupting(self, monkeypatch):
        monkeypatch.setattr(profile_recovery, "delete_snapshots",
                            lambda g, s: 850 * 1024 ** 2)
        window = self._Window()

        window.delete_profile_snapshots()

        assert window.spoken == [("profile_backup_deleted 850 MB", False)]

    def test_a_copy_in_progress_is_said_too(self, monkeypatch):
        monkeypatch.setattr(profile_recovery, "delete_snapshots", lambda g, s: None)
        window = self._Window()

        window.delete_profile_snapshots()

        assert window.spoken == [("profile_backup_delete_failed", False)]
