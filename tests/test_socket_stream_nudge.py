"""Tests for the WhatsApp socket-stream nudge fired when status-session says
CONNECTED but the live isConnected() probe disagrees.

Reported live: after the OS resumes from sleep, WinZapp got stuck offline
forever — status-session kept reporting the WPPConnect session object as
"CONNECTED" (a value cached at session creation), but check_whatsapp_reachable()
(the live isConnected() probe) never came back true again, and nothing ever
retried it. Root cause: WhatsApp Web's own multi-device socket is normally
reopened via WPP.whatsapp.Cmd.openSocketStream(), triggered by the page's own
visibility/focus/online DOM events — a headless, never-focused Chrome page
never fires those on its own after a suspend/resume cycle, so the socket that
went down during sleep had no trigger left to reconnect it.

MainWindow._nudge_whatsapp_socket_stream() POSTs to a new WPPConnect endpoint
(reconnect-socket-stream) that calls that same internal command directly.
check_wa_connection_http() now calls it exactly once whenever it detects the
CONNECTED-but-unreachable mismatch, before falling back to offline mode.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a small
stub — same approach as tests/test_message_bookmarks.py.
"""

import pytest

from main import MainWindow


class _Stub:
    _nudge_whatsapp_socket_stream = MainWindow._nudge_whatsapp_socket_stream

    def __init__(self):
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "test-token"


class TestNudgeWhatsappSocketStream:
    def test_posts_to_the_reconnect_endpoint_with_the_bearer_token(self, monkeypatch):
        calls = []

        def _fake_post(url, headers=None, timeout=None, **kw):
            calls.append((url, headers, timeout))
            class _Resp:
                status_code = 200
                text = "{}"
            return _Resp()

        monkeypatch.setattr("main.requests.post", _fake_post)
        s = _Stub()
        assert s._nudge_whatsapp_socket_stream() is True

        assert len(calls) == 1
        url, headers, timeout = calls[0]
        assert url == "http://127.0.0.1:6300/api/test-token/reconnect-socket-stream"
        assert headers["Authorization"] == "Bearer test-token"
        # Every call now carries a correlation id the Node side reuses in its
        # own log line (core/api_client.py). Asserting the whole dict equal
        # would break on that by design.
        assert headers["X-Request-Id"]
        assert timeout == 10

    def test_never_raises_when_the_request_fails(self, monkeypatch):
        def _fake_post(*a, **kw):
            raise ConnectionError("boom")

        monkeypatch.setattr("main.requests.post", _fake_post)
        s = _Stub()
        assert s._nudge_whatsapp_socket_stream() is False  # must not raise

    def test_returns_false_on_a_non_2xx_response(self, monkeypatch):
        """The server-side symptom that led here: a detached-Frame error
        makes page.evaluate() throw, and the endpoint answers with a 500 —
        that has to be distinguishable from a real success so the caller can
        escalate to _restart_wpp_session()."""
        def _fake_post(*a, **kw):
            class _Resp:
                status_code = 500
                text = '{"status":"error","message":"Attempted to use detached Frame"}'
            return _Resp()

        monkeypatch.setattr("main.requests.post", _fake_post)
        s = _Stub()
        assert s._nudge_whatsapp_socket_stream() is False
