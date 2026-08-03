"""Tests for MainWindow._restart_wpp_session() — the escalation path when the
Puppeteer page itself has structurally died (Puppeteer's own "Attempted to
use detached Frame" error) after a suspend/resume cycle, and no amount of
nudging (_nudge_whatsapp_socket_stream) can ever succeed on it again.

_restart_wpp_session() calls close-session then start-session on the *same*
running WPPConnect Node process — not a full app/process restart. Since the
session already has a valid stored token, start-session silently restores
the existing WhatsApp session (exactly what already happens on every normal
WinZapp restart), without a new QR code.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a small
stub — same approach as tests/test_message_bookmarks.py.
"""

import time

import pytest

from main import MainWindow


class _Stub:
    _restart_wpp_session = MainWindow._restart_wpp_session
    _auto_restart_grace_active = MainWindow._auto_restart_grace_active
    _WPP_SESSION_RESTART_COOLDOWN = MainWindow._WPP_SESSION_RESTART_COOLDOWN
    _AUTO_RESTART_LOGOUT_GRACE_SECONDS = MainWindow._AUTO_RESTART_LOGOUT_GRACE_SECONDS

    def __init__(self):
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "test-token"


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """_restart_wpp_session() sleeps 2s between close and start — skip that
    in tests."""
    monkeypatch.setattr("main.time.sleep", lambda *_: None)


class TestRestartWppSession:
    def test_calls_close_session_then_start_session(self, monkeypatch):
        calls = []

        def _fake_post(url, json=None, headers=None, timeout=None, **kw):
            calls.append(url)
            class _Resp:
                status_code = 200
            return _Resp()

        monkeypatch.setattr("main.requests.post", _fake_post)
        s = _Stub()
        s._restart_wpp_session()

        assert calls == [
            "http://127.0.0.1:6300/api/test-token/close-session",
            "http://127.0.0.1:6300/api/test-token/start-session",
        ]

    def test_start_session_still_runs_if_close_session_fails(self, monkeypatch):
        calls = []

        def _fake_post(url, **kw):
            calls.append(url)
            if url.endswith("/close-session"):
                raise ConnectionError("boom")
            class _Resp:
                status_code = 200
            return _Resp()

        monkeypatch.setattr("main.requests.post", _fake_post)
        s = _Stub()
        s._restart_wpp_session()  # must not raise

        assert calls == [
            "http://127.0.0.1:6300/api/test-token/close-session",
            "http://127.0.0.1:6300/api/test-token/start-session",
        ]

    def test_respects_the_cooldown_between_restarts(self, monkeypatch):
        calls = []
        monkeypatch.setattr("main.requests.post", lambda url, **kw: calls.append(url))
        s = _Stub()

        s._restart_wpp_session()
        assert len(calls) == 2

        s._restart_wpp_session()  # immediately again — still within cooldown
        assert len(calls) == 2, "a second restart inside the cooldown window must be a no-op"

    def test_restarts_again_once_the_cooldown_has_elapsed(self, monkeypatch):
        calls = []
        monkeypatch.setattr("main.requests.post", lambda url, **kw: calls.append(url))
        s = _Stub()

        s._restart_wpp_session()
        assert len(calls) == 2

        s._last_wpp_session_restart_ts = time.time() - (s._WPP_SESSION_RESTART_COOLDOWN + 1)
        s._restart_wpp_session()
        assert len(calls) == 4

    def test_reentrant_call_while_already_restarting_is_a_no_op(self, monkeypatch):
        calls = []
        monkeypatch.setattr("main.requests.post", lambda url, **kw: calls.append(url))
        s = _Stub()
        s._restarting_wpp_session = True

        s._restart_wpp_session()

        assert calls == []


class TestAutoRestartGraceWindow:
    """The mechanism that keeps _restart_wpp_session() safe to call
    automatically: check_wa_connection_http()'s "confirmed logout" path
    (which wipes the whole local database via _on_disconnect()) must never
    fire as a side effect of our own restart discovering the stored token
    had already gone bad — see _restart_wpp_session()'s docstring for the
    real incident this prevents.
    """

    def test_no_restart_ever_happened_grace_is_not_active(self, monkeypatch):
        s = _Stub()
        assert s._auto_restart_grace_active() is False

    def test_grace_is_active_right_after_a_restart_attempt(self, monkeypatch):
        monkeypatch.setattr("main.requests.post", lambda *a, **kw: None)
        s = _Stub()
        s._restart_wpp_session()
        assert s._auto_restart_grace_active() is True

    def test_grace_expires_after_the_configured_window(self, monkeypatch):
        monkeypatch.setattr("main.requests.post", lambda *a, **kw: None)
        s = _Stub()
        s._restart_wpp_session()
        s._auto_session_restart_ts = time.time() - (s._AUTO_RESTART_LOGOUT_GRACE_SECONDS + 1)
        assert s._auto_restart_grace_active() is False

    def test_grace_is_set_even_when_the_cooldown_blocks_the_actual_restart(self, monkeypatch):
        """The timestamp is set unconditionally, synchronously, before the
        cooldown/re-entrancy checks — a health check landing on another
        thread right after "decided to restart" must see the window active
        immediately, not after whatever delay the restart's own HTTP calls
        take."""
        calls = []
        monkeypatch.setattr("main.requests.post", lambda url, **kw: calls.append(url))
        s = _Stub()
        s._restarting_wpp_session = True  # forces the early-return path

        s._restart_wpp_session()

        assert calls == []
        assert s._auto_restart_grace_active() is True
