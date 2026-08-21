"""Regression test for GitHub issue #33: "Oversensitive Offline Mode
Trigger causing Frequent Disconnections".

WebSocketClient.on_disconnect() used to wait only 5 seconds, with the socket
still down, before silently flipping the app to auto-offline mode — too
short to ride out an ordinary Wi-Fi power-save/NAT-rebind blip or a brief
hiccup against the local WPPConnect server, both of which python-socketio's
own reconnection backoff (2s, doubling up to 60s) can resolve on its own
given a bit more time. The confirm delay is now 20 seconds instead.
"""

from core.websocket_client import WebSocketClient


class TestDisconnectConfirmTimeout:
    def test_confirm_delay_is_no_longer_five_seconds(self):
        assert WebSocketClient._DISCONNECT_CONFIRM_SECONDS != 5.0

    def test_confirm_delay_gives_socketio_reconnection_backoff_real_room(self):
        # python-socketio's own backoff here starts at 2s and doubles, so a
        # confirm delay under ~15s barely gives it a couple of attempts.
        assert WebSocketClient._DISCONNECT_CONFIRM_SECONDS >= 15.0

    def test_on_disconnect_schedules_timer_using_the_class_constant(self):
        import inspect

        src = inspect.getsource(WebSocketClient.on_disconnect)
        assert "self._DISCONNECT_CONFIRM_SECONDS" in src
        assert "5.0" not in src
