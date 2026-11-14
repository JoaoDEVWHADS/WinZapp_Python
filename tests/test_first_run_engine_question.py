"""MainWindow._check_api_type_first_run(): the first-run connection-engine
question. Cancelling exits before anything is saved; a custom-server settings
dialog that is cancelled rolls back ``wpp_custom_api`` (the address of an
engine with a fixed one stays, the question is not marked as asked).

MainWindow is a wx.Frame, so the unbound method runs against a plain stub; the
question and the settings dialog are replaced, nothing opens a window.
"""

import sys
import types

import pytest

from core import connection_engine as engines
from main import MainWindow
from main_window import settings as settings_module
from ui.dialogs import engine_picker


class _Stub:
    _check_api_type_first_run = MainWindow._check_api_type_first_run
    _apply_engine_choice = MainWindow._apply_engine_choice

    def __init__(self, settings=None, background_mode=False):
        self.settings = settings if settings is not None else {}
        self.background_mode = background_mode
        self.i18n = object()
        self.saved = []
        self.wpp_custom_api, self.wpp_server = False, "http://original"
        self.wpp_ws_server, self.wpp_port = "ws://original", 1234

    def save_settings(self):
        self.saved.append(
            {k: dict(v) for k, v in self.settings.items() if isinstance(v, dict)})


def _choose(monkeypatch, answer):
    asked = []
    monkeypatch.setattr(engine_picker, "ask_first_run",
                        lambda i18n: asked.append(i18n) or answer)
    return asked


def _settings_dialog(monkeypatch, result):
    """A SettingsDialog that 'closes' with ``result``; returns the log."""
    log = []

    class _Notebook:
        def FindPage(self, page):
            return page

        def SetSelection(self, index):
            log.append(("page", index))

    class _Dialog:
        def __init__(self, parent):
            self._notebook, self._conn_page = _Notebook(), "connection"

        def ShowModal(self):
            return result

        def Destroy(self):
            log.append("destroyed")

    monkeypatch.setitem(sys.modules, "ui.dialogs.settings_dialog",
                        types.SimpleNamespace(SettingsDialog=_Dialog))
    return log


def test_closing_the_question_exits_before_anything_is_saved(monkeypatch):
    mw = _Stub()
    _choose(monkeypatch, None)
    with pytest.raises(SystemExit) as exit_info:
        mw._check_api_type_first_run()
    assert exit_info.value.code == 0
    assert mw.saved == [] and mw.settings == {}


def test_nothing_is_asked_in_background_mode_or_twice(monkeypatch):
    asked = _choose(monkeypatch, engines.NEONIZE)
    _Stub(background_mode=True)._check_api_type_first_run()
    _Stub({"general": {"api_type_first_run_asked": True}})._check_api_type_first_run()
    assert asked == []


def test_the_bundled_server_is_saved_and_marked_as_asked(monkeypatch):
    mw = _Stub()
    _choose(monkeypatch, engines.WPPCONNECT)
    mw._check_api_type_first_run()
    assert mw.settings["connection"] == {"wpp_custom_api": False, "wpp_engine": "wppconnect"}
    assert mw.settings["general"]["api_type_first_run_asked"] is True
    assert mw.wpp_custom_api is False and mw.wpp_port == 1234
    assert mw.wpp_engine == engines.WPPCONNECT
    # whoever just saw the engine list is not told about Neonize again
    assert mw.settings["general"]["neonize_offer_asked"] is True


def test_neonize_saves_its_fixed_address_without_the_settings_dialog(monkeypatch):
    mw = _Stub()
    _choose(monkeypatch, engines.NEONIZE)
    log = _settings_dialog(monkeypatch, settings_module.wx.ID_CANCEL)
    mw._check_api_type_first_run()
    assert log == []
    assert mw.settings["connection"] == {
        "wpp_custom_api": True, "wpp_engine": "neonize", "wpp_server": "http://127.0.0.1",
        "wpp_ws_server": "ws://127.0.0.1", "wpp_port": 6300}
    assert mw.wpp_engine == engines.NEONIZE
    assert (mw.wpp_server, mw.wpp_ws_server, mw.wpp_port) == (
        "http://127.0.0.1", "ws://127.0.0.1", 6300)
    assert mw.settings["general"]["api_type_first_run_asked"] is True


def test_a_confirmed_custom_server_is_kept_and_marked_as_asked(monkeypatch):
    mw = _Stub()
    _choose(monkeypatch, engines.CUSTOM)
    log = _settings_dialog(monkeypatch, settings_module.wx.ID_OK)
    mw._check_api_type_first_run()
    assert ("page", "connection") in log and "destroyed" in log
    assert mw.settings["connection"] == {"wpp_custom_api": True, "wpp_engine": "custom"}
    assert mw.settings["general"]["api_type_first_run_asked"] is True


def test_a_cancelled_custom_server_is_rolled_back_and_not_marked_as_asked(monkeypatch):
    mw = _Stub()
    _choose(monkeypatch, engines.CUSTOM)
    _settings_dialog(monkeypatch, settings_module.wx.ID_CANCEL)
    with pytest.raises(SystemExit) as exit_info:
        mw._check_api_type_first_run()
    assert exit_info.value.code == 0
    assert mw.settings["connection"] == {"wpp_custom_api": False, "wpp_engine": "wppconnect"}
    assert mw.wpp_custom_api is False
    assert "api_type_first_run_asked" not in mw.settings.get("general", {})
    assert mw.saved[-1]["connection"] == {"wpp_custom_api": False, "wpp_engine": "wppconnect"}
