"""Own reactions from linked devices must not be mistaken for WinZapp echoes."""

import threading
import time

from core.websocket_client import WebSocketClient


class _MainWindow:
    def __init__(self, pending=None):
        self._pending_own_reactions = dict(pending or {})
        self._pending_own_reactions_lock = threading.Lock()


def _client(pending=None):
    client = WebSocketClient.__new__(WebSocketClient)
    client.main_window = _MainWindow(pending)
    return client


def _reaction(target_id="message-1", emoji="👍"):
    return {
        "key": {"fromMe": True, "id": "reaction-1"},
        "messageType": "reactionMessage",
        "message": {
            "reactionMessage": {
                "key": {"id": target_id},
                "text": emoji,
            }
        },
    }


def test_reaction_from_phone_is_not_suppressed_without_a_local_send():
    client = _client()

    assert client._consume_own_reaction_echo(_reaction()) is False


def test_matching_local_reaction_echo_is_suppressed_once():
    signature = ("message-1", "👍")
    client = _client({signature: time.monotonic()})

    assert client._consume_own_reaction_echo(_reaction()) is True
    # The same reaction may arrive through both received-message and the
    # dedicated onreactionmessage event; both copies must stay suppressed.
    assert client._consume_own_reaction_echo(_reaction()) is True


def test_different_phone_reaction_is_not_suppressed():
    client = _client({("message-1", "👍"): time.monotonic()})

    assert client._consume_own_reaction_echo(_reaction(emoji="😂")) is False


def test_expired_local_marker_does_not_hide_a_phone_reaction():
    signature = ("message-1", "👍")
    client = _client({signature: time.monotonic() - 61})

    assert client._consume_own_reaction_echo(_reaction()) is False
    assert signature not in client.main_window._pending_own_reactions
