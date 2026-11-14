"""Destructive recovery needs a readable CLOSED and unchanged session ownership."""

from types import SimpleNamespace

import pytest

import connection_state as cs
from main_window import connection
from main_window.connection import ConnectionMixin


class Response:
    def __init__(self, payload=None, status=200, error=None):
        self.payload, self.status_code, self.error = payload, status, error

    def json(self):
        if self.error:
            raise self.error
        return self.payload


class RecoveryStub:
    _raw_session_status = ConnectionMixin._raw_session_status
    _wait_for_status = ConnectionMixin._wait_for_status
    _restart_session_once = ConnectionMixin._restart_session_once
    _restart_wpp_session = ConnectionMixin._restart_wpp_session
    _force_whatsapp_session_restart = ConnectionMixin._force_whatsapp_session_restart
    _run_recovery_attempts = ConnectionMixin._run_recovery_attempts
    _RECOVERY_POLL = 1
    _RECOVERY_CLOSE_WAIT = 2
    _RECOVERY_MAX_ATTEMPTS = 2
    _RECOVERY_SETTLE_TIMEOUT = 2
    _RECOVERY_COOLDOWN = 1
    _WPP_SESSION_RESTART_COOLDOWN = 120
    _RESTART_PROFILE_RELEASE_WAIT = 25

    def __init__(self):
        self.token = "session:key"
        self.wpp_server = "http://synthetic.invalid"
        self.wpp_port = 6300
        self.ws = object()
        self.releases = []
        self._wa_connected = False
        self._recovery_restart_active = False

    def _is_pairing_dialog_active(self):
        return getattr(self, "pairing_shown", False)

    def wait_for_profile_release(self, session_name, timeout=20):
        self.releases.append(session_name)
        return True

    def _probe_whatsapp_host(self):
        return True

    def _shutdown_audit(self, text):
        pass


@pytest.fixture
def recovery_api(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    posts, gets = [], []
    api = SimpleNamespace(response=Response({"status": "CLOSED"}), close_status=200,
                          close_error=None, on_get=None)

    def get(url, **kwargs):
        gets.append(url)
        if api.on_get:
            api.on_get()
        if isinstance(api.response, Exception):
            raise api.response
        return api.response

    def post(url, **kwargs):
        posts.append(url.rsplit("/", 1)[-1])
        if url.endswith("/close-session") and api.close_error:
            raise api.close_error
        return Response(status=api.close_status if url.endswith("/close-session") else 200)

    monkeypatch.setattr(connection, "api_get", get)
    monkeypatch.setattr(connection, "api_post", post)
    monkeypatch.setattr(connection, "time", SimpleNamespace(
        monotonic=lambda: clock.now, time=lambda: clock.now,
        sleep=lambda seconds: setattr(clock, "now", clock.now + seconds)))
    return SimpleNamespace(api=api, clock=clock, posts=posts, gets=gets)


@pytest.mark.parametrize("reply", [
    TimeoutError("synthetic timeout"), Response(status=500), Response(status=403),
    Response({}), Response({"status": ""}), Response({"status": None}),
    Response({"status": True}), Response([]), Response("bad shape"),
    Response(error=ValueError("bad JSON")),
])
def test_unreadable_session_status_is_unknown(recovery_api, reply):
    recovery_api.api.response = reply
    assert RecoveryStub()._raw_session_status() is None


@pytest.mark.parametrize("path", ["wake", "general"])
@pytest.mark.parametrize("close_status", [200, 503])
@pytest.mark.parametrize("reply", [TimeoutError("timeout"), Response(status=500),
                                  Response({}), Response({"status": "CLOSING"})])
def test_unknown_or_incomplete_close_never_releases_or_starts(recovery_api, path, close_status, reply):
    stub = RecoveryStub()
    recovery_api.api.close_status = close_status
    recovery_api.api.response = reply
    if path == "wake":
        stub._restart_session_once(stub.token)
    else:
        stub._restart_wpp_session()
    assert recovery_api.posts == ["close-session"]
    assert stub.releases == []


@pytest.mark.parametrize("path", ["wake", "general"])
def test_lost_close_response_can_progress_after_explicit_closed(recovery_api, path):
    stub = RecoveryStub()
    recovery_api.api.close_error = TimeoutError("close response lost")
    if path == "wake":
        stub._restart_session_once(stub.token)
    else:
        stub._restart_wpp_session()
    assert recovery_api.posts == ["close-session", "start-session"]
    assert stub.releases == ["session"]


def test_closed_wait_does_not_confuse_first_unreadable_poll_with_closed(recovery_api):
    replies = iter([Response(status=500), Response({"status": "CLOSING"}),
                    Response({"status": "CLOSED"})])
    recovery_api.api.on_get = lambda: setattr(recovery_api.api, "response", next(replies))
    stub = RecoveryStub()
    assert stub._wait_for_status(cs.session_closed_after_flush, 4, False) == "CLOSED"
    assert len(recovery_api.gets) == 3


def change_context(stub, change):
    if change in ("_shutting_down", "_wpp_updating", "_user_offline",
                  "_pairing_in_progress", "_profile_restore_in_flight", "pairing_shown"):
        setattr(stub, change, True)
    elif change == "empty_token":
        stub.token = ""
    elif change == "new_token":
        stub.token = "session:new-key"
    elif change == "new_socket":
        stub.ws = object()
    elif change == "new_server":
        stub.wpp_server = "http://another.synthetic.invalid"
    else:
        stub.wpp_port += 1


@pytest.mark.parametrize("path", ["wake", "general"])
@pytest.mark.parametrize("change", ["_shutting_down", "_wpp_updating", "_user_offline",
    "_pairing_in_progress", "_profile_restore_in_flight", "pairing_shown",
    "empty_token", "new_token", "new_socket", "new_server", "new_port"])
def test_release_wait_cannot_restart_superseded_session(recovery_api, path, change):
    stub = RecoveryStub()
    token = stub.token

    def release(session_name, timeout=20):
        stub.releases.append(session_name)
        change_context(stub, change)
        return True

    stub.wait_for_profile_release = release
    if path == "wake":
        stub._restart_session_once(token)
    else:
        stub._restart_wpp_session()
        assert stub._restarting_wpp_session is False
    assert recovery_api.posts == ["close-session"]
    assert stub.releases == ["session"]


@pytest.mark.parametrize("path", ["wake", "general"])
def test_status_wait_context_change_aborts_before_profile_work(recovery_api, path):
    stub = RecoveryStub()
    recovery_api.api.on_get = lambda: setattr(stub, "token", "new-session:key")
    if path == "wake":
        stub._restart_session_once(stub.token)
    else:
        stub._restart_wpp_session()
    assert recovery_api.posts == ["close-session"]
    assert stub.releases == []


def test_general_restart_rechecks_context_after_slow_host_probe(recovery_api):
    stub = RecoveryStub()

    def probe():
        stub._shutting_down = True
        return True

    stub._probe_whatsapp_host = probe
    assert stub._restart_wpp_session() is False
    assert recovery_api.posts == ["close-session"]


def test_recovery_cancelled_in_attempt_does_not_settle_or_retry(recovery_api):
    stub = RecoveryStub()
    attempts = []

    def restart(token, attempt):
        attempts.append(attempt)
        stub._shutting_down = True

    stub._restart_session_once = restart
    stub._wait_for_status = lambda *a, **k: pytest.fail("cancelled recovery may not poll")
    stub._force_whatsapp_session_restart()
    assert attempts == [1]
    assert stub._recovery_restart_active is False


def test_user_offline_blocks_recovery_before_any_destructive_call(recovery_api):
    stub = RecoveryStub()
    stub._user_offline = True
    stub._force_whatsapp_session_restart()
    stub._restart_session_once(stub.token)
    assert stub._restart_wpp_session() is False
    assert recovery_api.posts == []
    assert stub.releases == []
