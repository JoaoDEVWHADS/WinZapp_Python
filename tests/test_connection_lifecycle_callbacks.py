"""Old socket callbacks and foreign messages must not change current liveness."""

from types import SimpleNamespace

import pytest

from core import websocket_client as sockets
from core.websocket_client import WebSocketClient


@pytest.fixture
def callbacks(monkeypatch):
    timers, queue, workers = [], [], []

    class Timer:
        def __init__(self, seconds, callback):
            self.seconds, self.callback = seconds, callback
            self.cancelled = False
            timers.append(self)

        def start(self):
            pass

        def cancel(self):
            self.cancelled = True

    class Worker:
        def __init__(self, target, **kwargs):
            workers.append(target)

        def start(self):
            pass

    monkeypatch.setattr(sockets, "threading", SimpleNamespace(Timer=Timer, Thread=Worker))
    monkeypatch.setattr(sockets.wx, "CallAfter", lambda fn, *a: queue.append(lambda: fn(*a)))
    return SimpleNamespace(timers=timers, queue=queue, workers=workers)


def socket_stub():
    verdicts, checks, live, messages = [], [], [], []
    window = SimpleNamespace(
        token="session:key", _wa_connected=True, _sync_completed=True,
        _set_wa_connected=lambda *args: verdicts.append(args),
        check_wa_connection_http=lambda: checks.append("check"),
        trigger_sync_if_needed=lambda: checks.append("sync"),
        _note_live_wpp_event=lambda: live.append("live"),
    )
    client = SimpleNamespace(
        main_window=window, _session_token=window.token, instance_name="session",
        sio=SimpleNamespace(connected=False), _disconnect_timer=None, _disconnect_epoch=0,
        _DISCONNECT_CONFIRM_SECONDS=WebSocketClient._DISCONNECT_CONFIRM_SECONDS,
        _normalize_wpp_message=lambda value: dict(value),
        on_messages_upsert=lambda value: messages.append(value),
    )
    for name in ("on_disconnect", "on_connect", "_recheck_connection_after_connect",
                 "_belongs_to_this_session", "on_wpp_message_received"):
        setattr(client, name, getattr(WebSocketClient, name).__get__(client))
    window.ws = client
    return client, SimpleNamespace(verdicts=verdicts, checks=checks, live=live, messages=messages)


def test_replaced_socket_cannot_apply_its_queued_disconnect(callbacks):
    old, results = socket_stub()
    old.on_disconnect()
    callbacks.timers[0].callback()  # already in the wx queue; cancel is too late
    old.main_window.ws = SimpleNamespace(sio=SimpleNamespace(connected=True))
    callbacks.queue[0]()
    assert results.verdicts == []


def test_reconnect_invalidates_queued_timer_even_after_another_drop(callbacks):
    client, results = socket_stub()
    client.on_disconnect()
    callbacks.timers[0].callback()
    client.sio.connected = True
    client.on_connect()
    client.sio.connected = False
    client.on_disconnect()
    callbacks.queue[0]()
    assert results.verdicts == []
    assert callbacks.timers[0].cancelled
    callbacks.timers[1].callback()
    callbacks.queue[1]()
    assert results.verdicts == [(False, "socket disconnected", False)]


@pytest.mark.parametrize("change", ["shutdown", "empty_token", "new_token"])
def test_disconnect_timer_yields_to_session_change(callbacks, change):
    client, results = socket_stub()
    client.on_disconnect()
    if change == "shutdown":
        client.main_window._shutting_down = True
    else:
        client.main_window.token = "" if change == "empty_token" else "session:new-key"
    callbacks.timers[0].callback()
    callbacks.queue[0]()
    assert results.verdicts == []


def test_pairing_client_already_assigned_to_window_can_confirm_real_drop(callbacks):
    client, results = socket_stub()
    client.main_window._pairing_in_progress = True
    client.on_disconnect()
    assert callbacks.timers[0].seconds == client._DISCONNECT_CONFIRM_SECONDS
    callbacks.timers[0].callback()
    callbacks.queue[0]()
    assert results.verdicts == [(False, "socket disconnected", False)]


def test_replaced_connect_worker_does_not_check_or_reset_sync(callbacks):
    client, results = socket_stub()
    client.on_connect()
    client.main_window.ws = object()
    callbacks.workers[0]()
    assert results.checks == []
    assert client.main_window._sync_completed is True


def test_client_replaced_during_http_check_does_not_reset_new_sync(callbacks):
    client, results = socket_stub()
    client.main_window.check_wa_connection_http = lambda: setattr(client.main_window, "ws", object())
    client._recheck_connection_after_connect()
    assert client.main_window._sync_completed is True
    assert results.checks == []


@pytest.mark.parametrize("payload", [None, {}, {"session": "other", "response": {"body": "x"}},
                                        {"response": {"session": "other", "body": "x"}}])
def test_foreign_or_empty_message_cannot_prove_this_session_live(callbacks, payload):
    client, results = socket_stub()
    client.on_wpp_message_received(payload)
    assert results.live == []
    assert results.messages == []


@pytest.mark.parametrize("session", ["session", None])
def test_own_and_legacy_untagged_message_still_note_liveness(callbacks, session):
    client, results = socket_stub()
    payload = {"response": {"body": "x"}}
    if session:
        payload["session"] = session
    client.on_wpp_message_received(payload)
    assert results.live == ["live"]
    assert len(results.messages) == 1


@pytest.mark.parametrize("session", ["session", None])
@pytest.mark.parametrize("response", ["bad", ["bad"], [{"body": "x"}], 42])
def test_truthy_non_message_response_cannot_refresh_liveness(callbacks, session, response):
    client, results = socket_stub()
    payload = {"response": response}
    if session:
        payload["session"] = session
    client.on_wpp_message_received(payload)
    assert results.live == []
    assert results.messages == []


@pytest.mark.parametrize("session", ["session", None])
@pytest.mark.parametrize("result", [None, [], ValueError("synthetic normalization failure")])
def test_failed_normalization_cannot_refresh_liveness(callbacks, session, result):
    client, results = socket_stub()

    def normalize(value):
        if isinstance(result, Exception):
            raise result
        return result

    client._normalize_wpp_message = normalize
    payload = {"response": {"body": "x"}}
    if session:
        payload["session"] = session
    client.on_wpp_message_received(payload)
    assert results.live == []
    assert results.messages == []


def test_a_drop_is_logged_with_the_reason_python_socketio_gives(callbacks, caplog):
    import logging
    client, _results = socket_stub()
    with caplog.at_level(logging.INFO):
        client.on_disconnect("ping timeout")
        client.on_disconnect()
    lines = [r.getMessage() for r in caplog.records if "WebSocket disconnected" in r.getMessage()]
    assert lines == ["[WebSocketClient] WebSocket disconnected (ping timeout).",
                     "[WebSocketClient] WebSocket disconnected (no reason given)."]
