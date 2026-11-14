"""With the Neonize bridge (or a custom server) there is no WPPConnect under
client/api/ for WinZapp to manage.

Audit F4, H1: 90 s after opening, the WPPConnect update checker offered an
update to any install that still had client/api/package.json lying around
(every dev checkout, everyone who once ran WPPConnect); accepting it stopped
the live Neonize session and the bridge, built WPPConnect and started a Node
on the bridge's port with the bridge's secret as its key. "Force WPPConnect
reinstall" in the Help menu did the same on demand.
"""
import sys
import types

import pytest

from main import MainWindow
from main_window.updates import UpdatesMixin
from tests.god_modules import main_window_method_source


class _Boom:
    def __init__(self, *args, **kwargs):
        raise AssertionError("a WPPConnect update checker was built")


@pytest.fixture
def no_checker(monkeypatch):
    monkeypatch.setitem(sys.modules, "updater", types.SimpleNamespace(WppUpdateChecker=_Boom))


def _window(custom_api, **extra):
    stopped = []
    window = types.SimpleNamespace(
        wpp_custom_api=custom_api, settings={"general": {"updates_enabled": True}},
        _wpp_update_checker=None, _stop_wpp_server=lambda: stopped.append(True),
        _wpp_staging=None, _wpp_updating=False, stopped=stopped, **extra)
    return window


def test_the_periodic_check_is_skipped(no_checker):
    window = _window(True)
    UpdatesMixin._start_wpp_update_checker(window)
    UpdatesMixin._start_wpp_update_checker(window, force=True)
    assert window._wpp_update_checker is None


def test_the_forced_reinstall_does_nothing(no_checker):
    window = _window(True)
    UpdatesMixin._on_force_reinstall_wpp(window, None)
    assert window._wpp_update_checker is None


def test_an_update_that_gets_through_anyway_is_refused_before_stopping_anything():
    window = _window(True)
    assert UpdatesMixin._update_wpp_server(window, "v2.0.0") is False
    assert window.stopped == []
    assert window._wpp_updating is False


def test_the_bundled_engine_still_builds_the_checker(monkeypatch):
    built = []

    class _Checker:
        def __init__(self, owner):
            built.append(owner)

        def force_check(self):
            pass

    monkeypatch.setitem(sys.modules, "updater", types.SimpleNamespace(WppUpdateChecker=_Checker))
    window = _window(False)
    UpdatesMixin._start_wpp_update_checker(window, force=True)
    assert built == [window]


def test_the_reinstall_recommendation_stays_pending_for_later():
    window = types.SimpleNamespace(
        wpp_custom_api=True, settings={"general": {"wpp_reinstall_notice_pending": True}},
        output=lambda *a, **k: pytest.fail("spoke"), i18n=None)
    MainWindow._show_wpp_reinstall_notice_if_pending(window)
    assert window.settings["general"]["wpp_reinstall_notice_pending"] is True


def test_the_help_menu_does_not_list_the_reinstall_item_without_a_local_wppconnect():
    """By source: the menu is built from wx widgets no stub can run."""
    source = main_window_method_source("_build_menubar")
    assert ("if profile_is_local(self):\n"
            "            help_menu.Append(self._ID_FORCE_REINSTALL_WPP") in source
    assert "wpp_item is not None" in main_window_method_source("_refresh_menubar")
