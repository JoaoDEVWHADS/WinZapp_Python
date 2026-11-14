"""Disconnected recovery is one queued worker, never HTTP on the wx queue."""

from types import SimpleNamespace

import pytest

from core import connection_lifecycle as lifecycle
from main_window import sending
from main_window.sending import SendingMixin


@pytest.fixture
def scheduled(monkeypatch):
    targets = []

    class Worker:
        def __init__(self, target, **kwargs):
            targets.append(target)

        def start(self):
            pass

    monkeypatch.setattr(lifecycle, "threading", SimpleNamespace(
        Thread=Worker, Lock=lifecycle.threading.Lock))
    monkeypatch.setattr(sending.wx, "CallAfter", lambda *a, **k: pytest.fail("HTTP queued on wx"))
    return targets


def window_stub():
    events = []
    window = SimpleNamespace(token="session:key", wpp_server="http://synthetic.invalid",
        wpp_port=6300, ws=object(), check_wa_connection_http=lambda: events.append("check"),
        _set_wa_connected=lambda connected, *a: events.append(connected))
    return window, events


def response(reason=None):
    payload = {"status": "Disconnected"}
    if reason:
        payload["reason"] = reason
    return SimpleNamespace(status_code=404, json=lambda: payload)


def test_disconnected_classifier_schedules_one_worker_without_gui_http(scheduled):
    window, events = window_stub()
    assert SendingMixin._check_wa_connection_closed(window, response()) is True
    assert events == [False]
    assert len(scheduled) == 1
    SendingMixin._check_wa_connection_closed(window, response())
    assert len(scheduled) == 1
    scheduled[0]()
    assert events == [False, False, "check"]
    assert lifecycle.schedule_connection_check(window) is True
    assert len(scheduled) == 2


def test_probe_timeout_does_not_schedule_or_flip_connection(scheduled):
    window, events = window_stub()
    assert SendingMixin._check_wa_connection_closed(window, response("probe_timeout")) is True
    assert scheduled == []
    assert events == []


@pytest.mark.parametrize("change", ["shutdown", "update", "offline", "token", "socket"])
def test_queued_check_yields_to_a_changed_session(scheduled, change):
    window, events = window_stub()
    assert lifecycle.schedule_connection_check(window) is True
    if change == "token":
        window.token = "new-session:key"
    elif change == "socket":
        window.ws = object()
    else:
        setattr(window, {"shutdown": "_shutting_down", "update": "_wpp_updating",
                         "offline": "_user_offline"}[change], True)
    scheduled[0]()
    assert events == []
    assert not window._connection_check_worker_lock.locked()


def test_failed_check_releases_slot_for_later_recovery(scheduled):
    window, events = window_stub()

    def fail():
        raise ValueError("synthetic failure")

    window.check_wa_connection_http = fail
    lifecycle.schedule_connection_check(window)
    scheduled[0]()
    window.check_wa_connection_http = lambda: events.append("check")
    assert lifecycle.schedule_connection_check(window) is True
    scheduled[1]()
    assert events == ["check"]


def test_failure_to_start_worker_does_not_keep_the_slot_locked(monkeypatch):
    window, _ = window_stub()

    class BrokenWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("synthetic thread start failure")

    monkeypatch.setattr(lifecycle, "threading", SimpleNamespace(
        Thread=BrokenWorker, Lock=lifecycle.threading.Lock))
    assert lifecycle.schedule_connection_check(window) is False
    assert not window._connection_check_worker_lock.locked()
