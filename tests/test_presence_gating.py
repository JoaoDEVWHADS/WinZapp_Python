"""Tests for online-presence being gated on a live WhatsApp connection.

`self.token` is set at startup from the stored WA_token, long before — and
independently of — the session actually being usable. `_send_presence` checked
only that, so the 20-second keep-alive kept POSTing to a session that was
CLOSED on the Node side. In a real run that produced an endless train of HTTP
500s with the response discarded and nothing logged, for a session that could
not possibly accept presence.

The 500 itself was the Node side's fault: `/api/:session/set-online-presence`
reached its controller without the `statusConnection` middleware, so
`req.client` was undefined, `req.client.setOnlinePresence()` threw a TypeError,
and the controller's blanket catch reported it as a server error rather than
the 404 `{status: 'Disconnected'}` most routes return. The adjacent
`subscribe-presence` had the same gap and is fixed with it.

Other upstream POST routes are also unguarded (start-all, restore-sessions,
reconnect-socket-stream, get-media-by-message, chatwoot). Some of those are
legitimately reachable without a live session and some may not be; deciding
that for upstream's route table is a separate question, so these tests assert
only the two routes WinZapp actually changed.

A failed call is not free: wa-js's `markAvailable()` pins `Stream.available`
via `Object.defineProperty` for the page's lifetime, so a successful
`markAvailable(false)` followed by a failing `markAvailable(true)` can leave
the page stuck advertising "offline" while messaging still works.
"""

import os

import pytest

from main import MainWindow


class _Stub:
    _send_presence = MainWindow._send_presence

    def __init__(self, token="sess:tok", connected=True):
        self.token = token
        self._wa_connected = connected
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300


class _Posts(list):
    """A recording list that also carries the status code to hand back."""

    status = {"code": 200}


@pytest.fixture
def posts(monkeypatch):
    calls = _Posts()
    calls.status = {"code": 200}

    def _fake_post(url, **kwargs):
        calls.append({"url": url, "json": kwargs.get("json")})

        class _Resp:
            status_code = calls.status["code"]

        return _Resp()

    import main as main_module

    monkeypatch.setattr(main_module, "api_post", _fake_post)
    return calls


class TestPresenceIsGatedOnTheConnection:
    def test_it_sends_while_connected(self, posts):
        _Stub(connected=True)._send_presence("available")

        assert len(posts) == 1
        assert posts[0]["json"] == {"isOnline": True}
        assert posts[0]["url"].endswith("/set-online-presence")

    def test_unavailable_maps_to_is_online_false(self, posts):
        _Stub(connected=True)._send_presence("unavailable")
        assert posts[0]["json"] == {"isOnline": False}

    def test_it_is_silent_when_not_connected(self, posts):
        """The keep-alive fires every 20 s while the window has focus. Without
        this gate an unpaired or dropped session generated a 500 every 20 s
        for as long as the app stayed focused."""
        _Stub(connected=False)._send_presence("available")
        assert posts == []

    def test_a_token_alone_is_not_enough(self, posts):
        """self.token is restored at startup regardless of session health — it
        was the only thing checked before."""
        stub = _Stub(token="sess:tok", connected=False)
        stub._send_presence("available")
        assert posts == []

    def test_no_token_is_still_a_no_op(self, posts):
        _Stub(token="", connected=True)._send_presence("available")
        assert posts == []

    def test_a_missing_connection_attribute_is_treated_as_disconnected(self, posts):
        """_wa_connected does not exist until well into __init__; presence
        must not fire before then."""
        stub = _Stub(connected=True)
        del stub._wa_connected
        stub._send_presence("available")
        assert posts == []


class TestTheResponseIsNoLongerDiscarded:
    def test_an_error_status_is_logged(self, posts, caplog):
        """A presence that never once succeeded used to look exactly like one
        that always did."""
        posts.status["code"] = 500
        with caplog.at_level("WARNING"):
            _Stub(connected=True)._send_presence("available")

        assert "set-online-presence" in caplog.text
        assert "500" in caplog.text

    def test_success_is_not_logged_as_a_problem(self, posts, caplog):
        posts.status["code"] = 200
        with caplog.at_level("WARNING"):
            _Stub(connected=True)._send_presence("available")

        assert "set-online-presence" not in caplog.text

    def test_a_transport_failure_never_propagates(self, monkeypatch):
        """This runs on a throwaway daemon thread; an escaping exception would
        be an unraisable traceback on the user's console and nothing else."""
        import main as main_module

        def _boom(url, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(main_module, "api_post", _boom)

        _Stub(connected=True)._send_presence("available")  # must not raise


class TestBothPresenceRoutesGuardTheConnection:
    """Source-level check on the patched WPPConnect route table, in the style
    this suite already uses for the node_modules patches. Both presence
    controllers dereference req.client unconditionally, so reaching them
    without a live session can only throw."""

    @staticmethod
    def _routes_source():
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(
            repo_root, "client", "api_patches", "src", "routes", "index.ts"
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    @pytest.mark.parametrize(
        "route", ["set-online-presence", "subscribe-presence"]
    )
    def test_the_route_declares_status_connection(self, route):
        source = self._routes_source()
        start = source.index(f"'/api/:session/{route}'")
        block = source[start : source.index(");", start)]
        assert "statusConnection" in block, (
            f"{route} reaches its controller without statusConnection, so a "
            f"missing session becomes a 500 instead of a 404 Disconnected"
        )
