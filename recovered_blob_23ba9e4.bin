import pytest
import unittest.mock
from tests.mocks import MockMainWindow


class TestBug17ConnectHealth:
    """Bug 17: check_connection_status should verify API health, not just token existence."""

    @pytest.fixture
    def mw(self):
        return MockMainWindow()

    def test_returns_false_when_no_token(self, mw, monkeypatch):
        import client.ui.dialogs.connect as connect_mod
        dlg = connect_mod.Connect.__new__(connect_mod.Connect)
        dlg.main_window = mw
        result = dlg.check_connection_status()
        assert result is False

    def test_returns_false_when_api_unreachable(self, mw, monkeypatch):
        mw.settings["privateinfo"]["WA_token"] = "valid_token"
        import client.ui.dialogs.connect as connect_mod
        dlg = connect_mod.Connect.__new__(connect_mod.Connect)
        dlg.main_window = mw

        import requests
        fake_resp = unittest.mock.MagicMock()
        fake_resp.ok = False
        monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=5: fake_resp)

        result = dlg.check_connection_status()
        assert result is False

    def test_returns_true_when_api_healthy(self, mw, monkeypatch):
        mw.settings["privateinfo"]["WA_token"] = "valid_token"
        import client.ui.dialogs.connect as connect_mod
        dlg = connect_mod.Connect.__new__(connect_mod.Connect)
        dlg.main_window = mw

        import requests
        fake_resp = unittest.mock.MagicMock()
        fake_resp.ok = True
        monkeypatch.setattr(requests, "get", lambda url, headers=None, timeout=5: fake_resp)

        result = dlg.check_connection_status()
        assert result is True
