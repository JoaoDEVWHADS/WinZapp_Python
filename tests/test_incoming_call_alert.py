"""Accessible incoming-call alert lifecycle."""

from types import SimpleNamespace

import wx

from core.websocket_client import WebSocketClient
from main import MainWindow


class _Sound:
    def __init__(self):
        self.play_calls = 0
        self.stop_calls = 0

    def play(self):
        self.play_calls += 1

    def stop(self):
        self.stop_calls += 1


class _I18n:
    def t(self, key):
        return {
            "incoming_call_announcement": "{name} está te ligando.",
            "unknown_contact": "Contato desconhecido",
        }.get(key, key)


class _MainStub:
    _CALL_RINGING_STATES = MainWindow._CALL_RINGING_STATES
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    on_incoming_call_event = MainWindow.on_incoming_call_event
    _expire_incoming_call_alert = MainWindow._expire_incoming_call_alert

    def __init__(self):
        self._active_incoming_calls = {}
        self._incoming_call_watchdogs = {}
        self.call_incoming_sound = _Sound()
        self.i18n = _I18n()
        self.announcements = []
        self.armed_watchdogs = []
        self.cancelled_watchdogs = []

    def _arm_incoming_call_watchdog(self, identity):
        self.armed_watchdogs.append(identity)

    def _cancel_incoming_call_watchdog(self, identity):
        self.cancelled_watchdogs.append(identity)

    def _preview_sender_from_jid(self, jid):
        return "Fulano" if jid else ""

    def output(self, text, interrupt=False):
        self.announcements.append((text, interrupt))


def _offer(call_id="call-1", peer="5511999999999@s.whatsapp.net"):
    return {
        "event": "offer",
        "state": "INCOMING_RING",
        "id": call_id,
        "peerJid": peer,
    }


def test_offer_announces_and_starts_loop_only_once():
    stub = _MainStub()

    stub.on_incoming_call_event(_offer())
    stub.on_incoming_call_event(_offer())

    assert stub.announcements == [("Fulano está te ligando.", True)]
    assert stub.call_incoming_sound.play_calls == 1
    assert stub.armed_watchdogs == ["call-1"]
    assert stub._active_incoming_calls == {
        "call-1": "5511999999999@s.whatsapp.net"
    }


def test_answered_or_ended_state_stops_the_tone():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer())

    stub.on_incoming_call_event({"event": "state", "state": "HANDLED_REMOTELY", "id": "call-1"})

    assert stub._active_incoming_calls == {}
    assert stub.call_incoming_sound.stop_calls == 1
    assert stub.cancelled_watchdogs == ["call-1"]


def test_ringing_state_update_does_not_stop_the_tone():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer())

    stub.on_incoming_call_event({
        "event": "state", "state": "INCOMING_RING", "id": "call-1"
    })

    assert set(stub._active_incoming_calls) == {"call-1"}
    assert stub.call_incoming_sound.stop_calls == 0


def test_numeric_received_call_state_keeps_the_tone_playing():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer())

    stub.on_incoming_call_event({
        "event": "state", "state": "3", "id": "call-1"
    })

    assert set(stub._active_incoming_calls) == {"call-1"}
    assert stub.call_incoming_sound.stop_calls == 0


def test_watchdog_stops_a_call_when_no_terminal_event_arrives():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer())

    stub._expire_incoming_call_alert("call-1")

    assert stub._active_incoming_calls == {}
    assert stub.call_incoming_sound.stop_calls == 1


def test_one_ended_call_does_not_silence_another_ringing_call():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer("call-1"))
    stub.on_incoming_call_event(_offer("call-2", "5511888888888@s.whatsapp.net"))

    stub.on_incoming_call_event({"event": "ended", "state": "ENDED", "id": "call-1"})

    assert set(stub._active_incoming_calls) == {"call-2"}
    assert stub.call_incoming_sound.stop_calls == 0


def test_websocket_normalizes_nested_call_payload(monkeypatch):
    delivered = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args: fn(*args))
    stub = SimpleNamespace(
        instance_name="session-a",
        main_window=SimpleNamespace(on_incoming_call_event=delivered.append),
    )
    stub._belongs_to_this_session = WebSocketClient._belongs_to_this_session.__get__(stub)
    stub._clean_jid = WebSocketClient._clean_jid.__get__(stub)

    WebSocketClient.on_wpp_incoming_call(stub, {
        "session": "session-a",
        "data": {
            "event": "offer",
            "state": "INCOMING_RING",
            "id": "abc",
            "peerJid": {"_serialized": "5511999999999@c.us"},
            "isVideo": True,
        },
    })

    assert delivered == [{
        "event": "offer",
        "state": "INCOMING_RING",
        "id": "abc",
        "peerJid": "5511999999999@s.whatsapp.net",
        "isVideo": True,
        "isGroup": False,
    }]
