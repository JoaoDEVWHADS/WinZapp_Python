"""WebSocketClient's most frequent/reliable event handlers must stamp
main_window._note_live_wpp_event() — see check_whatsapp_reachable() and
issue investigation for "app stuck offline while messages kept arriving
live" (home internet dropped, mobile data picked up the slack, but the
app's own outbound reachability probe stayed stuck failing for minutes
even though WPPConnect's local Socket.IO stream never stopped delivering).

WebSocketClient itself isn't instantiated here (its __init__ builds a real
socketio.Client and an I18n instance) — only the handler methods under test
are bound onto a plain stub, same "Stub-binding" pattern used throughout
this suite for wx-bound classes.
"""

from core.websocket_client import WebSocketClient, ack_to_status


class _FakeMainWindow:
    def __init__(self):
        self.live_event_calls = 0
        self.unread_updates = []

    def _note_live_wpp_event(self):
        self.live_event_calls += 1

    def on_chat_unread_update(self, *args):
        self.unread_updates.append(args)


class _Stub:
    on_wpp_ack = WebSocketClient.on_wpp_ack
    on_chats_update = WebSocketClient.on_chats_update
    on_wpp_message_received = WebSocketClient.on_wpp_message_received
    _belongs_to_this_session = WebSocketClient._belongs_to_this_session

    def __init__(self):
        self.main_window = _FakeMainWindow()
        self.instance_name = ""

    # Methods on_wpp_ack/on_wpp_message_received reach for past this point —
    # exercising only the "did we note liveness" side effect, not the rest.
    def _update_message_status(self, *a, **kw):
        pass


class TestLiveEventNoting:
    def test_ack_event_notes_liveness(self):
        stub = _Stub()

        stub.on_wpp_ack({"ack": 1, "id": "3EB0AA"})

        assert stub.main_window.live_event_calls == 1

    def test_chats_update_notes_liveness(self):
        stub = _Stub()

        stub.on_chats_update({"data": [{"remoteJid": "1@s.whatsapp.net", "unreadCount": 0}]})

        assert stub.main_window.live_event_calls == 1

    def test_a_foreign_session_event_does_not_note_liveness(self):
        """_belongs_to_this_session() rejects events tagged for a different
        WPPConnect instance (multi-account) before the liveness stamp — a
        message meant for another account's session proves nothing about
        this one's connectivity."""
        stub = _Stub()
        stub.instance_name = "my-session"

        stub.on_chats_update({"session": "someone-elses-session", "data": []})

        assert stub.main_window.live_event_calls == 0

    def test_manual_unread_sentinel_is_normalized_for_both_transitions(self, monkeypatch):
        monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda fn, *args: fn(*args))
        stub = _Stub()

        stub.on_chats_update({
            "data": [{
                "remoteJid": "1@s.whatsapp.net",
                "unreadCount": -1,
                "previousUnreadCount": 0,
            }]
        })
        stub.on_chats_update({
            "data": [{
                "remoteJid": "1@s.whatsapp.net",
                "unreadCount": 0,
                "previousUnreadCount": -1,
            }]
        })

        assert stub.main_window.unread_updates == [
            ("1@s.whatsapp.net", 1, 0),
            ("1@s.whatsapp.net", 0, 1),
        ]

    def test_ack_to_status_still_works_untouched(self):
        # Sanity: the import path used above still resolves correctly.
        assert ack_to_status(1) == 2
