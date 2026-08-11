"""Session-scoping guard for WebSocketClient._belongs_to_this_session.

Locks in the cross-account event-leak fix: a shared WPPConnect Server
broadcasts every session's events to every connected Socket.IO client, so
WinZapp must drop events whose ``session`` (top-level or nested inside
``response`` for ``received-message``) does not match this client's own
``instance_name``. Before this guard was corrected, a `received-message`
carried its session *inside* the response object while the guard only read
the top level — so it returned True for every event and each account
processed the other accounts' conversations.
"""

import logging
import sys
import types

# websocket_client.py imports wx/socketio at module top; the guard under test
# is pure logic that touches neither. Stub them out so the test stays headless
# on machines without the wxPython desktop stack (CI/Linux containers).
for _name in ("wx", "socketio"):
    if _name not in sys.modules:
        sys.modules[_name] = types.ModuleType(_name)

from core.websocket_client import WebSocketClient


class _Stub:
    """Minimal stand-in: the guard only touches instance_name + logging."""

    def __init__(self, instance_name):
        self.instance_name = instance_name


def _guard(instance_name, info):
    """Bind the unbound method onto a stub (homegrown MainWindow pattern)."""
    stub = _Stub(instance_name)
    return WebSocketClient._belongs_to_this_session(stub, info)


def test_accepts_event_from_own_session_top_level():
    assert _guard("sess-A", {"session": "sess-A", "data": {}}) is True


def test_accepts_event_with_session_prefix():
    # Server session names may carry a ":"-suffixed token; only the prefix
    # before the colon is compared, mirroring instance_name handling.
    assert _guard("sess-A", {"session": "sess-A:abc123"}) is True


def test_rejects_event_from_other_session_top_level():
    assert _guard("sess-A", {"session": "sess-B", "data": {}}) is False


def test_rejects_event_from_other_session_nested_in_response():
    # received-message shape after the server patch: session inside response.
    info = {"response": {"session": "sess-B", "body": "oi"}}
    assert _guard("sess-A", info) is False


def test_accepts_own_session_nested_in_response():
    info = {"response": {"session": "sess-A", "body": "oi"}}
    assert _guard("sess-A", info) is True


def test_top_level_session_wins_over_nested_response():
    # If both are present, the top level is authoritative.
    info = {"session": "sess-A", "response": {"session": "sess-B"}}
    assert _guard("sess-A", info) is True


def test_accepts_event_without_any_session(caplog):
    # Events that genuinely carry no session info (some broadcast payloads)
    # stay accepted for backwards compatibility with pre-patch servers.
    with caplog.at_level(logging.INFO):
        assert _guard("sess-A", {"data": []}) is True
    assert "Ignored event" not in caplog.text


def test_rejects_are_logged(caplog):
    with caplog.at_level(logging.INFO):
        assert _guard("sess-A", {"session": "sess-B"}) is False
    assert "Ignored event for session 'sess-B'" in caplog.text


def test_accepts_everything_when_instance_name_is_blank():
    # First pairing: client has no identity yet, dropping events would
    # deadlock the QR/pairing flow.
    assert _guard("", {"session": "sess-X"}) is True
    assert _guard(None, {"session": "sess-X"}) is True


def test_non_dict_payload_is_accepted():
    assert _guard("sess-A", None) is True
    assert _guard("sess-A", "not-a-dict") is True