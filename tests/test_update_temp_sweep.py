"""What an update leaves in %TEMP%: which folder is ours, and what is swept.

The installer script deletes the folder a package was extracted into once the
copy has worked (tests/test_update_script_cleanup.py); this is the other half —
the decision of *which* folder that is, and the sweep at the next start for what
older updates, failed installs and killed processes left behind.
"""

import os

import pytest

import update_temp_sweep
from update_package import EXTRACT_PREFIX, discard_package, extraction_root

DAY = 24 * 3600
NOW = 1_800_000_000.0


class TestWhichFolderIsOurs:
    def test_the_extraction_folder_itself(self, tmp_path):
        folder = tmp_path / f"{EXTRACT_PREFIX}ab12"
        assert extraction_root(str(folder)) == str(folder)

    def test_the_single_folder_inside_it_points_back_to_it(self, tmp_path):
        folder = tmp_path / f"{EXTRACT_PREFIX}ab12"
        assert extraction_root(str(folder / "WinZapp")) == str(folder)

    def test_a_trailing_separator_changes_nothing(self, tmp_path):
        folder = tmp_path / f"{EXTRACT_PREFIX}ab12"
        assert extraction_root(str(folder / "WinZapp") + os.sep) == str(folder)

    @pytest.mark.parametrize("path", ["", "C:/Users/me/Documents", "C:/winzapp", "/"])
    def test_anything_else_is_nobodys_to_delete(self, path):
        """The answer decides what a script removes: a path that only looks like
        a package, or the install itself, must come back empty."""
        assert extraction_root(path) == ""

    def test_the_install_directory_is_never_taken_for_one(self, tmp_path):
        assert extraction_root(str(tmp_path / "WinZapp" / "WinZapp")) == ""

    def test_discarding_still_removes_the_whole_folder(self, tmp_path):
        folder = tmp_path / f"{EXTRACT_PREFIX}ab12"
        (folder / "WinZapp").mkdir(parents=True)
        (folder / "WinZapp" / "WinZapp.exe").write_text("x")
        discard_package(str(folder / "WinZapp"))
        assert not folder.exists()


def _make(tmp_path, name, age_days, directory=False):
    path = tmp_path / name
    if directory:
        path.mkdir()
        (path / "WinZapp.exe").write_text("x")
    else:
        path.write_text("x")
    stamp = NOW - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


class TestTheSweep:
    def test_an_old_extracted_release_goes(self, tmp_path):
        old = _make(tmp_path, f"{EXTRACT_PREFIX}old", 5, directory=True)
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 1
        assert not old.exists()

    def test_a_recent_one_stays_because_another_account_may_be_waiting_to_install_it(
        self, tmp_path
    ):
        staged = _make(tmp_path, f"{EXTRACT_PREFIX}new", 1, directory=True)
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 0
        assert staged.exists()

    def test_a_download_that_never_reached_extraction_goes_with_the_folders(self, tmp_path):
        zipped = _make(tmp_path, "winzapp_upd_k3j2.zip", 3)
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 1
        assert not zipped.exists()

    def test_an_installer_script_is_kept_a_week_for_whoever_reads_it(self, tmp_path):
        young = _make(tmp_path, "winzapp_upd_a1.bat", 5)
        old = _make(tmp_path, "winzapp_upd_a2.bat", 9)
        marker = _make(tmp_path, "winzapp_upd_a2.bat.relaunch", 9)
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 2
        assert young.exists() and not old.exists() and not marker.exists()

    def test_nothing_that_is_not_ours_is_touched(self, tmp_path):
        theirs = [
            _make(tmp_path, "winzapp_log.txt", 90),
            _make(tmp_path, "other_ext_old", 90, directory=True),
            _make(tmp_path, "winzapp-audio-leftover", 90),
        ]
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 0
        assert all(path.exists() for path in theirs)

    def test_a_missing_temp_folder_is_not_an_error(self, tmp_path):
        assert update_temp_sweep.sweep_stale_update_temporaries(
            str(tmp_path / "nowhere"), now=NOW
        ) == 0

    def test_a_folder_that_cannot_be_removed_is_not_counted_and_does_not_stop_the_rest(
        self, tmp_path, monkeypatch
    ):
        stuck = _make(tmp_path, f"{EXTRACT_PREFIX}stuck", 9, directory=True)
        other = _make(tmp_path, f"{EXTRACT_PREFIX}other", 9, directory=True)
        real = update_temp_sweep.shutil.rmtree

        def refuse_one(path, **kwargs):
            if path.endswith("stuck"):
                kwargs["onexc"](None, path, PermissionError("antivirus"))
                return
            real(path, **kwargs)

        monkeypatch.setattr(update_temp_sweep.shutil, "rmtree", refuse_one)
        assert update_temp_sweep.sweep_stale_update_temporaries(str(tmp_path), now=NOW) == 1
        assert stuck.exists() and not other.exists()

    def test_it_runs_on_a_thread_of_its_own(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(
            update_temp_sweep, "sweep_stale_update_temporaries",
            lambda: seen.append(update_temp_sweep.threading.current_thread().name),
        )
        update_temp_sweep.start_background_sweep().join(5)
        assert seen == ["winzapp-update-sweep"]
