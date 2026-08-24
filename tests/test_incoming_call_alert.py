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


class _Dialog:
    def __init__(self):
        self.closed = False

    def close_from_call_lifecycle(self):
        self.closed = True


class _Bar:
    def __init__(self):
        self.shown = False

    def Show(self):
        self.shown = True

    def Hide(self):
        self.shown = False

    def IsShown(self):
        return self.shown


class _Label:
    def __init__(self):
        self.text = ""

    def SetLabel(self, text):
        self.text = text


class _I18n:
    def t(self, key):
        return {
            "incoming_call_announcement": "{name} está te ligando.",
            "incoming_group_call_announcement": "Chamada em grupo recebida no grupo {name}.",
            "unknown_contact": "Contato desconhecido",
            "unknown_group": "Grupo sem nome",
        }.get(key, key)


class _MainStub:
    _CALL_RINGING_STATES = MainWindow._CALL_RINGING_STATES
    _CALL_EVENT_START_GRACE_SECONDS = MainWindow._CALL_EVENT_START_GRACE_SECONDS
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _group_name_from_chat_dict = staticmethod(MainWindow._group_name_from_chat_dict)
    on_incoming_call_event = MainWindow.on_incoming_call_event
    _expire_incoming_call_alert = MainWindow._expire_incoming_call_alert
    stop_incoming_call_alert = MainWindow.stop_incoming_call_alert
    stop_all_incoming_call_alerts = MainWindow.stop_all_incoming_call_alerts
    _close_incoming_call_dialog = MainWindow._close_incoming_call_dialog
    _sync_incoming_call_bar = MainWindow._sync_incoming_call_bar

    def __init__(self):
        self._active_incoming_calls = {}
        self._incoming_call_watchdogs = {}
        self._incoming_call_dialogs = {}
        self.call_incoming_sound = _Sound()
        self.settings = {"calls": {"alerts_enabled": True, "popup_enabled": True}}
        self.i18n = _I18n()
        self.announcements = []
        self.armed_watchdogs = []
        self.cancelled_watchdogs = []
        self.chats = {}
        self._group_name_cache = {}
        self.popups = []
        self.incoming_call_bar = _Bar()
        self.incoming_call_label = _Label()
        self.layout_calls = 0
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "session-token"
        self._wa_startup_time = 2_000_000_000

    def _arm_incoming_call_watchdog(self, identity):
        self.armed_watchdogs.append(identity)

    def _cancel_incoming_call_watchdog(self, identity):
        self.cancelled_watchdogs.append(identity)

    def _preview_sender_from_jid(self, jid):
        return "Fulano" if jid else ""

    def output(self, text, interrupt=False):
        self.announcements.append((text, interrupt))

    def _show_incoming_call_dialog(self, identity, message):
        self.popups.append((identity, message))

    def Layout(self):
        self.layout_calls += 1


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
    assert stub.popups == [("call-1", "Fulano está te ligando.")]


def test_disabled_call_alerts_ignore_new_offer():
    stub = _MainStub()
    stub.settings["calls"]["alerts_enabled"] = False

    stub.on_incoming_call_event(_offer())

    assert stub.announcements == []
    assert stub.call_incoming_sound.play_calls == 0
    assert stub._active_incoming_calls == {}


def test_offer_from_before_current_session_is_ignored():
    stub = _MainStub()
    event = _offer()
    event["timestamp"] = int(stub._wa_startup_time) - 60

    stub.on_incoming_call_event(event)

    assert stub.announcements == []
    assert stub.call_incoming_sound.play_calls == 0
    assert stub._active_incoming_calls == {}


def test_offer_inside_startup_grace_is_still_live():
    stub = _MainStub()
    event = _offer()
    event["timestamp"] = int(stub._wa_startup_time) - 3

    stub.on_incoming_call_event(event)

    assert stub.call_incoming_sound.play_calls == 1
    assert set(stub._active_incoming_calls) == {"call-1"}


def test_offer_received_while_offline_is_ignored_even_if_recent():
    stub = _MainStub()
    event = _offer()
    event.update({
        "timestamp": int(stub._wa_startup_time) + 1,
        "receivedWhileOffline": True,
    })

    stub.on_incoming_call_event(event)

    assert stub.call_incoming_sound.play_calls == 0
    assert stub._active_incoming_calls == {}


def test_popup_can_be_disabled_without_disabling_spoken_and_sound_alert():
    stub = _MainStub()
    stub.settings["calls"]["popup_enabled"] = False

    stub.on_incoming_call_event(_offer())

    assert stub.announcements == [("Fulano está te ligando.", True)]
    assert stub.call_incoming_sound.play_calls == 1
    assert stub.popups == []
    assert stub.incoming_call_bar.shown is True
    assert stub.incoming_call_label.text == "Fulano está te ligando."


def test_in_window_stop_button_clears_non_popup_call_surface():
    stub = _MainStub()
    stub.settings["calls"]["popup_enabled"] = False
    stub.on_incoming_call_event(_offer())

    stub.stop_all_incoming_call_alerts()

    assert stub._active_incoming_calls == {}
    assert stub.incoming_call_bar.shown is False
    assert stub.call_incoming_sound.stop_calls == 1


def test_group_offer_announces_group_name_without_changing_personal_resolution():
    stub = _MainStub()
    group_jid = "120363427511142886@g.us"
    stub.chats[group_jid] = {
        "remoteJid": group_jid,
        "groupMetadata": {"subject": "Família"},
    }

    event = _offer(peer="5511888888888@lid")
    event.update({"isGroup": True, "groupJid": group_jid})
    stub.on_incoming_call_event(event)

    assert stub.announcements == [
        ("Chamada em grupo recebida no grupo Família.", True)
    ]


def test_answered_or_ended_state_stops_the_tone():
    stub = _MainStub()
    stub.on_incoming_call_event(_offer())
    dialog = _Dialog()
    stub._incoming_call_dialogs["call-1"] = dialog

    stub.on_incoming_call_event({"event": "state", "state": "HANDLED_REMOTELY", "id": "call-1"})

    assert stub._active_incoming_calls == {}
    assert stub.call_incoming_sound.stop_calls == 1
    assert stub.cancelled_watchdogs == ["call-1"]
    assert dialog.closed is True
    assert stub._incoming_call_dialogs == {}


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


def test_stop_button_only_stops_the_local_alert():
    stub = _MainStub()
    stub._active_incoming_calls["call-1"] = "peer@s.whatsapp.net"

    stub.stop_incoming_call_alert("call-1")

    assert stub._active_incoming_calls == {}
    assert stub.call_incoming_sound.stop_calls == 1
    assert stub.announcements == []


def test_websocket_normalizes_nested_call_payload(monkeypatch):
    delivered = []
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *args: fn(*args))
    stub = SimpleNamespace(
        instance_name="session-a",
        main_window=SimpleNamespace(on_incoming_call_event=delivered.append),
    )
    stub._belongs_to_this_session = WebSocketClient._belongs_to_this_session.__get__(stub)
    stub._clean_jid = WebSocketClient._clean_jid.__get__(stub)
    stub._call_timestamp_seconds = WebSocketClient._call_timestamp_seconds

    WebSocketClient.on_wpp_incoming_call(stub, {
        "session": "session-a",
        "data": {
            "event": "offer",
            "state": "INCOMING_RING",
            "id": "abc",
            "peerJid": {"_serialized": "5511999999999@c.us"},
            "groupJid": {"_serialized": "120363427511142886@g.us"},
            "isVideo": True,
            "offerTime": 2_000_000_001_000,
            "observedAt": 2_000_000_002,
        },
    })

    assert delivered == [{
        "event": "offer",
        "state": "INCOMING_RING",
        "id": "abc",
        "peerJid": "5511999999999@s.whatsapp.net",
        "groupJid": "120363427511142886@g.us",
        "isVideo": True,
        "isGroup": False,
        "timestamp": 2_000_000_001,
        "observedAt": 2_000_000_002,
        "receivedWhileOffline": False,
    }]


def test_call_timestamp_normalizer_handles_seconds_millis_and_micros():
    normalize = WebSocketClient._call_timestamp_seconds

    assert normalize(2_000_000_001) == 2_000_000_001
    assert normalize(2_000_000_001_000) == 2_000_000_001
    assert normalize(2_000_000_001_000_000) == 2_000_000_001
    assert normalize("invalid") == 0
    assert normalize(True) == 0
