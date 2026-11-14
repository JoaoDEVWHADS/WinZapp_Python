"""WinZapp refuses, with an explanation, to start from a network folder.

Reported from a Windows 11 ARM machine in Parallels, whose Downloads folder is
the Mac's (\\\\Mac\\Home\\Downloads): WinZapp extracted there ran npm install
on the share, cmd.exe refused the UNC path as its working directory, and the
user got two pages of npm output and no WinZapp. The database and the Chrome
profile would have lived on the share too. See core/install_location.py,
also for why a drive letter mapped to a share is not refused.
"""

import pytest

import app_paths
from core.install_location import is_unc_path
from main import MainWindow
from main_window import settings as settings_module


class TestIsUncPath:
    @pytest.mark.parametrize("path", [
        r"\\Mac\Home\Downloads\WinZapp (2)\WinZapp",
        r"\\?\UNC\Mac\Home\Downloads\WinZapp",
        r"\\?\unc\Mac\Home\WinZapp",
        "//server/share/WinZapp",
    ])
    def test_unc_paths(self, path):
        assert is_unc_path(path) is True

    @pytest.mark.parametrize("path", [
        r"C:\Users\nuno\WinZapp",
        r"\\?\C:\WinZapp",
        r"\\.\C:\WinZapp",
        # A drive mapped to a share: cmd.exe accepts it and people already run
        # WinZapp from one; refusing it would lock them out before the updater.
        r"Z:\WinZapp",
    ])
    def test_a_drive_letter_mapped_or_not(self, path):
        assert is_unc_path(path) is False

    @pytest.mark.parametrize("path", ["", None, "WinZapp\\data"])
    def test_nothing_to_judge(self, path):
        assert is_unc_path(path) is False


class _I18n:
    def t(self, key):
        return key + " {path}" if key == "network_install_location_message" else key


class _Window:
    _refuse_network_install_location = MainWindow._refuse_network_install_location

    def __init__(self, background_mode=False):
        self.background_mode = background_mode
        self.i18n = _I18n()


@pytest.fixture
def boxes(monkeypatch):
    shown = []
    monkeypatch.setattr(settings_module.wx, "MessageBox",
                        lambda message, title, style: shown.append((message, title)))
    return shown


def _installed_at(monkeypatch, base):
    monkeypatch.setattr(app_paths, "global_dir", lambda *parts: base + r"\data\global")


class TestTheStartupCheck:
    def test_a_network_folder_is_explained_and_the_app_closes(self, monkeypatch, boxes):
        _installed_at(monkeypatch, r"\\Mac\Home\Downloads\WinZapp")

        with pytest.raises(SystemExit):
            _Window()._refuse_network_install_location()

        assert boxes == [(
            r"network_install_location_message \\Mac\Home\Downloads\WinZapp",
            "network_install_location_title",
        )]

    @pytest.mark.parametrize("base", [r"C:\WinZapp", r"Z:\WinZapp"])
    def test_a_drive_letter_starts_normally(self, monkeypatch, boxes, base):
        _installed_at(monkeypatch, base)

        _Window()._refuse_network_install_location()

        assert boxes == []

    def test_in_the_background_it_closes_without_a_dialog(self, monkeypatch, boxes):
        """An autostart at logon has nobody to read a dialog; the log says why."""
        _installed_at(monkeypatch, r"\\Mac\Home\Downloads\WinZapp")

        with pytest.raises(SystemExit):
            _Window(background_mode=True)._refuse_network_install_location()

        assert boxes == []


def test_it_runs_before_anything_is_installed():
    """By source: the check has to come before npm install and before the
    terms dialog, or the user still gets the npm output first."""
    import inspect

    source = inspect.getsource(MainWindow.__init__)
    check = source.index("self._refuse_network_install_location()")
    assert check < source.index("self.ensure_api_modules_installed()")
    assert check < source.index("self._check_terms_acceptance()")
