from types import SimpleNamespace
import threading

import pytest
import requests

from core import wpp_connection_recovery as recovery
from main import MainWindow
from main_window import connection
from tests.test_no_offline_during_wpp_update import _Stub


@pytest.fixture(autouse=True)
def ui_callbacks(monkeypatch):
    monkeypatch.setattr(connection.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(connection.wx, "IsMainThread", lambda: True)


def test_reentrant_probe_is_skipped_and_lock_releases_after_failure():
    calls = []
    @recovery.serialized_connection_probe
    def probe(window):
        calls.append("probe")
        probe(window)
        raise ValueError("failed probe")
    window = SimpleNamespace()
    for _ in range(2):
        with pytest.raises(ValueError):
            probe(window)
    assert calls == ["probe", "probe"]


def test_installation_blocks_http_session_probe(monkeypatch):
    monkeypatch.setattr(connection, "api_get", lambda *a, **k: pytest.fail("API is being installed"))
    MainWindow.check_wa_connection_http(SimpleNamespace(_wpp_updating=True))


@pytest.mark.parametrize("outcome", ["accepted", "rejected", "timeout"])
def test_closed_polls_wait_for_pending_attempt_unless_rejected(monkeypatch, outcome):
    now = [100.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: now[0])
    posts = []
    monkeypatch.setattr(connection, "api_get", lambda *a, **k: SimpleNamespace(
        status_code=200, json=lambda: {"status": "CLOSED"}))
    def post(url, **kwargs):
        posts.append(url)
        if outcome == "timeout":
            raise requests.exceptions.Timeout("response lost")
        return SimpleNamespace(status_code=503 if outcome == "rejected" else 200)
    monkeypatch.setattr(connection, "api_post", post)
    window = SimpleNamespace(
        token="session", wpp_server="http://localhost", wpp_port=6300,
        _is_pairing_dialog_active=lambda: False,
        _note_status_for_profile_health=lambda *a: None,
        _unlink_decision_lock=threading.Lock(),
        _set_wa_connected=lambda *a, **k: None,
        _session_restart_owned=lambda: False,
        _self_inflicted_teardown_expected=lambda: False,
        _offline_start_deferral_holds=lambda: False,
        _note_session_start_for_profile_health=lambda: None,
    )
    MainWindow.check_wa_connection_http(window)
    MainWindow.check_wa_connection_http(window)
    assert len(posts) == (2 if outcome == "rejected" else 1)
    now[0] += 61
    MainWindow.check_wa_connection_http(window)
    assert len(posts) == (3 if outcome == "rejected" else 2)


def test_new_api_clears_pending_attempt_from_previous_api():
    window = SimpleNamespace(token="session")
    recovery.note_session_start(window)
    recovery.begin_update_reconnection(window)
    assert not recovery.session_start_pending(window)


def test_update_grace_keeps_sending_paused_until_real_connection():
    window = _Stub()
    recovery.begin_update_reconnection(window)
    window._set_wa_connected(False, "status-session CLOSED")
    assert window.offline_mode and window.spoken == []
    assert window.statuses == ["conectando..."]
    window._set_wa_connected(True, "status-session CONNECTED")
    assert not window.offline_mode
    assert not recovery.update_reconnection_pending(window)


def test_update_grace_expires_and_real_outage_is_announced(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(recovery.time, "monotonic", lambda: now[0])
    window = _Stub()
    recovery.begin_update_reconnection(window)
    window._set_wa_connected(False, "status-session CLOSED")
    now[0] += 91
    window._set_wa_connected(False, "status-session CLOSED")
    assert window.statuses[-1] == "desconectado do WhatsApp"


def test_old_connected_answer_cannot_reopen_sending_during_install():
    window = _Stub(updating=True)
    window._set_wa_connected(False, "socket disconnected")
    window._set_wa_connected(True, "stale HTTP response")
    assert window.offline_mode and not window._wa_connected
