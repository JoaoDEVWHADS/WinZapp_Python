"""Unreadable shutdown polls cannot authorize a clean profile snapshot."""

from types import SimpleNamespace

import pytest

from core import profile_recovery
from main_window import session_lifecycle, wpp_server
from main_window.session_lifecycle import SessionLifecycleMixin
from main_window.wpp_server import WppServerMixin


class Reply:
    def __init__(self, payload=None, status=200, error=None):
        self.payload, self.status_code, self.error = payload, status, error

    def json(self):
        if self.error:
            raise self.error
        return self.payload


class ShutdownStub:
    _wait_for_session_flushed = SessionLifecycleMixin._wait_for_session_flushed
    _capture_profile_snapshot = SessionLifecycleMixin._capture_profile_snapshot
    _stop_wpp_server = WppServerMixin._stop_wpp_server
    _SHUTDOWN_FLUSH_TIMEOUT = 2
    _SHUTDOWN_FLUSH_POLL = 1
    _WPP_GRACEFUL_STOP_SECONDS = 10

    def __init__(self):
        self.token, self.wpp_server, self.wpp_port = "synthetic:key", "http://synthetic.invalid", 6300
        self.wpp_process = SimpleNamespace(poll=lambda: None, pid=12345)
        self._wa_connected = True
        self.global_dir = "synthetic-never-read"
        self.settings = {}
        self.audit = []

    def _shutdown_audit(self, text):
        self.audit.append(text)

    def _yield_to_in_progress_self_restart(self):
        pass

    def _raw_session_status(self):
        return "CONNECTED"

    def _wait_for_token_persisted(self, token):
        pass

    def wait_for_profile_release(self, *args, **kwargs):
        return True

    def _login_store_fingerprint(self, *args):
        return "synthetic"


@pytest.fixture
def shutdown_api(monkeypatch):
    clock = SimpleNamespace(now=0.0)
    calls, snapshots, kills = [], [], []
    state = SimpleNamespace(replies=[Reply({"status": "CLOSED"})])
    window = ShutdownStub()
    window.wpp_process.terminate = lambda: kills.append("terminate")

    def get(url, **kwargs):
        calls.append((url, kwargs["timeout"]))
        reply = state.replies[0]
        if len(state.replies) > 1:
            state.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    fake_time = SimpleNamespace(monotonic=lambda: clock.now,
        sleep=lambda delay: setattr(clock, "now", clock.now + delay))
    monkeypatch.setattr(session_lifecycle, "time", fake_time)
    monkeypatch.setattr(wpp_server, "time", fake_time)
    monkeypatch.setattr(session_lifecycle, "api_get", get)
    monkeypatch.setattr(wpp_server, "api_post", lambda *a, **k: Reply(status=200))
    monkeypatch.setattr(wpp_server, "subprocess", SimpleNamespace(
        DEVNULL=None, CREATE_NO_WINDOW=0, run=lambda *a, **k: kills.append(a)))
    monkeypatch.setattr(session_lifecycle, "_profile_is_local", lambda window: True)
    monkeypatch.setattr(session_lifecycle, "_snapshots_disabled", lambda settings: False)
    monkeypatch.setattr(session_lifecycle, "_close_snapshot_max_age", lambda settings: 0)
    monkeypatch.setattr(profile_recovery, "capture_snapshot", lambda *a, **k: snapshots.append(a))
    monkeypatch.setattr(profile_recovery, "discard_pending_snapshot", lambda *a, **k: None)
    return SimpleNamespace(clock=clock, calls=calls, snapshots=snapshots, kills=kills,
                           state=state, window=window)


UNKNOWN = [Reply(error=ValueError("synthetic JSON failure")), Reply([]), Reply("bad"),
    Reply({}), Reply({"status": None}), Reply({"status": ""}), Reply({"status": True}),
    Reply({"status": ["CLOSED"]}), Reply(status=500), TimeoutError("synthetic")]


@pytest.mark.parametrize("reply", UNKNOWN)
def test_unknown_flush_waits_only_within_budget_and_returns_false(shutdown_api, reply):
    shutdown_api.state.replies = [reply]
    window = shutdown_api.window
    assert window._wait_for_session_flushed(window.token) is False
    assert shutdown_api.clock.now == 2
    assert len(shutdown_api.calls) == 2
    assert [timeout for _, timeout in shutdown_api.calls] == [2, 1]
    assert any("TIMEOUT" in text for text in window.audit)


@pytest.mark.parametrize("first", UNKNOWN + [Reply({"status": "CLOSING"})])
@pytest.mark.parametrize("closed", ["CLOSED", "DESTROYED"])
def test_unreadable_or_closing_can_later_confirm_explicit_closed(shutdown_api, first, closed):
    shutdown_api.state.replies = [first, Reply({"status": closed})]
    window = shutdown_api.window
    assert window._wait_for_session_flushed(window.token) is True
    assert len(shutdown_api.calls) == 2


@pytest.mark.parametrize("reply", UNKNOWN)
def test_real_stop_and_snapshot_consumer_refuse_unknown_flush(shutdown_api, reply):
    shutdown_api.state.replies = [reply]
    window = shutdown_api.window
    window._stop_wpp_server()
    assert shutdown_api.snapshots == []
    assert len(shutdown_api.kills) == 1
    assert any("FLUSH FAIL" in text for text in window.audit)


def test_real_stop_captures_snapshot_only_after_explicit_closed(shutdown_api):
    window = shutdown_api.window
    window._stop_wpp_server()
    assert shutdown_api.snapshots == [("synthetic-never-read", "synthetic")]
    assert any("FLUSH OK" in text for text in window.audit)
