"""Tests for on_wpp_qrcode()/on_wpp_phone_code() ignoring events from a
session other than this client's own (self.instance_name).

Reported live: after WinZapp auto-repaired a session (closed the old,
invalid token via /close-session — which answered HTTP 200 — and started a
fresh one that paired successfully), qrCode events kept arriving every
~20s for several more minutes, re-triggering the "session needs re-pairing"
flow and, once the pairing dialog's widgets had already been destroyed, an
unhandled RuntimeError on every one. The wppconnect.log for the same
incident showed why: /close-session answering 200 did not actually stop the
OLD session's underlying browser/QR-polling loop — it kept running
("Waiting for QRCode Scan (Attempt 12)...") as an orphaned session for
several more minutes, alongside the new, already-connected one, and kept
emitting its own qrCode events the whole time.

WPPConnect's qrCode/phoneCode payloads carry a "session" field identifying
which session generated them (confirmed by the codebase's own two prior
uses of this exact guard, in on_wpp_session_logged and on_wpp_status_find:
"Ignore events for other sessions (multi-session server scenario)") — but
on_wpp_qrcode/on_wpp_phone_code never checked it, so a stale session's
events were treated identically to the real, currently active session's own.

WebSocketClient is exercised as a plain function bound onto a small stub —
same approach as tests/test_qrcode_auto_repair_dialog.py.
"""

import pytest

from core.websocket_client import WebSocketClient


class _Stub:
    on_wpp_qrcode      = WebSocketClient.on_wpp_qrcode
    on_wpp_phone_code  = WebSocketClient.on_wpp_phone_code

    def __init__(self, instance_name="abc123"):
        self.instance_name = instance_name
        self.connect = None
        self._phone_code_value = None
        self.qrcode_update_calls = []

    def on_qrcode_update(self, info):
        self.qrcode_update_calls.append(info)

    class _FakeEvent:
        def __init__(self):
            self.set_calls = 0

        def set(self):
            self.set_calls += 1

    def __getattr__(self, name):
        # Lazily provide _phone_code_event as a fresh fake on first touch,
        # mirroring the real attribute's role (a threading.Event set() call).
        if name == "_phone_code_event":
            self._phone_code_event = self._FakeEvent()
            return self._phone_code_event
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _synchronous_call_after(monkeypatch):
    monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


class TestOnWppQrcodeIgnoresOtherSessions:
    def test_matching_session_is_processed(self):
        stub = _Stub(instance_name="current-session")

        stub.on_wpp_qrcode({"data": "base64img", "session": "current-session"})

        assert len(stub.qrcode_update_calls) == 1

    def test_no_session_field_is_processed_as_before(self):
        """Some payload shapes may omit "session" entirely — must not
        become an accidental universal block."""
        stub = _Stub(instance_name="current-session")

        stub.on_wpp_qrcode({"data": "base64img"})

        assert len(stub.qrcode_update_calls) == 1

    def test_stale_other_session_is_ignored(self):
        stub = _Stub(instance_name="current-session")

        stub.on_wpp_qrcode({"data": "base64img", "session": "old-orphaned-session"})

        assert stub.qrcode_update_calls == []


class TestOnWppPhoneCodeIgnoresOtherSessions:
    def test_matching_session_updates_the_code(self):
        stub = _Stub(instance_name="current-session")

        stub.on_wpp_phone_code({"data": "ABCD-1234", "session": "current-session"})

        assert stub._phone_code_value == "ABCD-1234"
        assert stub._phone_code_event.set_calls == 1

    def test_stale_other_session_does_not_touch_the_code(self):
        stub = _Stub(instance_name="current-session")

        stub.on_wpp_phone_code({"data": "ZZZZ-9999", "session": "old-orphaned-session"})

        assert stub._phone_code_value is None
