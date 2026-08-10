"""Tests for core.utils.get_downloads_folder() — used to default every
"Save As" dialog (documents, audio, status media) to the user's Downloads
folder, per the user's request, while the standard wx.FileDialog picker
still lets them navigate anywhere else.

Resolves Windows' FOLDERID_Downloads shell API rather than assuming
``~/Downloads`` — that plain join is wrong for a user who redirected their
Downloads folder elsewhere (e.g. to OneDrive), which the shell API
correctly follows.
"""

import os

from core.utils import get_downloads_folder


class TestGetDownloadsFolder:
    def test_returns_a_real_existing_directory_on_this_machine(self):
        # This test runs on real Windows dev/CI machines with a real
        # Downloads folder — exercise the actual API, not a mock, so a
        # regression in the ctypes/GUID plumbing itself gets caught.
        path = get_downloads_folder()
        assert os.path.isdir(path)

    def test_falls_back_to_home_downloads_when_the_api_call_fails(self, monkeypatch):
        import core.utils as utils_module
        monkeypatch.setattr(utils_module.sys, "platform", "linux")
        expected = os.path.join(os.path.expanduser("~"), "Downloads")
        assert get_downloads_folder() == expected

    def test_a_broken_shell_api_falls_back_instead_of_raising(self, monkeypatch):
        import ctypes
        import core.utils as utils_module

        class _BrokenShell32:
            def SHGetKnownFolderPath(self, *a, **kw):
                raise OSError("simulated shell API failure")

        monkeypatch.setattr(ctypes, "windll", type("W", (), {"shell32": _BrokenShell32()})(), raising=False)

        expected = os.path.join(os.path.expanduser("~"), "Downloads")
        assert get_downloads_folder() == expected
