"""Local runtime installation must follow the explicit API-type choice."""

import inspect

from main import MainWindow


class _SettingsStub:
    def __init__(self, *, asked, custom=False):
        self.settings = {
            "general": {"api_type_first_run_asked": asked},
            "connection": {"wpp_custom_api": custom},
        }


def test_local_api_requires_an_explicit_first_run_choice():
    assert MainWindow._local_api_selected(
        _SettingsStub(asked=False, custom=False)
    ) is False


def test_explicit_local_choice_enables_local_runtime_setup():
    assert MainWindow._local_api_selected(
        _SettingsStub(asked=True, custom=False)
    ) is True


def test_remote_choice_disables_local_runtime_setup():
    assert MainWindow._local_api_selected(
        _SettingsStub(asked=True, custom=True)
    ) is False


def test_every_local_install_entry_point_has_the_guard():
    for name in (
        "find_headless_shell",
        "ensure_api_modules_installed",
        "_ensure_api_modules_installed",
        "ensure_headless_shell_installed",
        "ensure_wpp_version",
        "ensure_wpp_running",
        "_start_wpp_update_checker",
    ):
        source = inspect.getsource(getattr(MainWindow, name))
        assert "_local_api_selected()" in source, name


def test_api_choice_precedes_any_startup_install_check():
    source = inspect.getsource(MainWindow.__init__)
    choice = source.index("self._check_api_type_first_run()")
    install = source.index("self.ensure_api_modules_installed()", choice)
    assert choice < install
