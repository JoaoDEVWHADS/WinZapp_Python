"""Real health polls must discard superseded HTTP observations inside the poll."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

import connection_state as cs
from main_window import account_link, connection
from main_window.connection import ConnectionMixin
from main_window.account_link import AccountLinkMixin


class Response:
    def __init__(self, payload, on_json=lambda: None, status=200):
        self.payload, self.on_json, self.status_code = payload, on_json, status

    def json(self):
        self.on_json()
        return self.payload


class PollStub:
    check_wa_connection_http = ConnectionMixin.check_wa_connection_http
    check_whatsapp_reachable = ConnectionMixin.check_whatsapp_reachable
    _offline_start_deferral_holds = ConnectionMixin._offline_start_deferral_holds
    _handle_local_auth_rejected = ConnectionMixin._handle_local_auth_rejected
    _act_on_unlink_decision = AccountLinkMixin._act_on_unlink_decision
    _OFFLINE_PROBE_STRIKES = 2
    _HTTP_PROBE_STRIKES = 2
    _LIVE_WPP_EVENT_FRESHNESS_SECONDS = 45
    _DEAD_BROWSER_RESTART_STRIKES = 3
    _LOGOUT_CONFIRM_STRIKES = 4
    _RESUME_FAIL_STRIKES = 20
    _STILL_LINKED_VETO_LIMIT = 3

    def __init__(self):
        self.token, self.wpp_server, self.wpp_port = "old:key", "http://synthetic.invalid", 6300
        self.ws = object()
        self._unlink_decision_lock = nullcontext()
        self.settings = {"privateinfo": {"paired": True}}
        self.writes, self.verdicts, self.starts, self.disconnects = [], [], [], []
        self.db = SimpleNamespace(set_metadata=lambda *args: self.writes.append(args))
        self.hook = lambda stage: None
        self.seed_new_session()

    def seed_new_session(self):
        self._wa_connected = False
        self._wa_http_fail_strikes = 7
        self._offline_probe_strikes = 7
        self._offline_probe_first_strike_ts = 99
        self._dead_browser_strikes = 7
        self._offline_start_deferred_since = 123
        self._logout_strikes = 4
        self._resume_fail_strikes = 4
        self._last_strike_ts = 0
        self._logout_handled = False
        self.my_jid = "new@c.us"
        self._wpp_pending_start_until = 555
        self._wpp_pending_start_token = "new:key"

    def snapshot(self):
        return {name: getattr(self, name) for name in (
            "_wa_connected", "_wa_http_fail_strikes", "_offline_probe_strikes",
            "_offline_probe_first_strike_ts", "_dead_browser_strikes",
            "_offline_start_deferred_since", "_logout_strikes", "_resume_fail_strikes",
            "_last_strike_ts", "_logout_handled", "my_jid", "_wpp_pending_start_until")}

    def _set_wa_connected(self, value, *args, **kwargs):
        self._wa_connected = value
        self.verdicts.append(value)

    def _is_pairing_dialog_active(self):
        return False

    def _session_restart_owned(self):
        return getattr(self, "_recovery_restart_active", False)

    def _self_inflicted_teardown_expected(self):
        return False

    def _auto_restart_grace_active(self):
        return False

    def _note_status_for_profile_health(self, status):
        pass

    def _note_session_start_for_profile_health(self):
        self.starts.append("noted")

    def _prove_whatsapp_probe_once(self):
        self.hook("proof")

    def _probe_whatsapp_host(self):
        self.hook("host_probe")
        return True

    def _nudge_whatsapp_socket_stream(self):
        self.hook("nudge")
        return False

    def resolve_self_lid(self):
        self.hook("resolve")

    def save_settings(self):
        self.writes.append("settings")

    def _still_linked_on_server(self):
        self.hook("unlink_probe")
        return cs.LINK_PROBE_UNKNOWN

    def _on_disconnect(self, wipe=True):
        self.disconnects.append(wipe)

    def _restart_wpp_session(self):
        self.starts.append("restart")


CHANGES = ("token", "server", "port", "socket", "shutdown", "update")


def replace_owner(window, change):
    names = {"token": ("token", "new:key"), "server": ("wpp_server", "http://other.invalid"),
             "port": ("wpp_port", 7400), "socket": ("ws", object()),
             "shutdown": ("_shutting_down", True), "update": ("_wpp_updating", True)}
    setattr(window, *names[change])
    window.seed_new_session()


@pytest.fixture
def poll_api(monkeypatch):
    window = PollStub()
    calls, queue, workers = [], [], []
    scenario = SimpleNamespace(stage="", status="CONNECTED", reachable=True, workers=workers)

    class Worker:
        def __init__(self, target, **kwargs):
            workers.append(target)

        def start(self):
            pass

    def get(url, **kwargs):
        calls.append((url, kwargs["headers"]["Authorization"]))
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "status-session":
            window.hook("status_get")
            if scenario.stage == "status_error":
                window.hook("status_error")
                raise TimeoutError("synthetic")

            def parsed():
                window.hook("status_json")
                if scenario.stage == "status_json_error":
                    window.hook("status_json_error")
                    raise ValueError("synthetic")

            return Response({"status": scenario.status}, parsed)
        if endpoint == "check-connection-session":
            window.hook("reach_get")
            return Response({"status": scenario.reachable}, lambda: window.hook("reach_json"))
        assert endpoint == "host-device"
        window.hook("host_get")
        return Response({"response": {"phoneNumber": {"_serialized": "old@c.us"}}},
                        lambda: window.hook("host_json"))

    def post(url, **kwargs):
        calls.append((url, kwargs["headers"]["Authorization"]))
        window.hook("start_post")
        return Response({}, status=500 if scenario.stage == "start_post" else 200)

    monkeypatch.setattr(connection, "api_get", get)
    monkeypatch.setattr(connection, "api_post", post)
    monkeypatch.setattr(connection, "time", SimpleNamespace(time=lambda: 1000, monotonic=lambda: 1000))
    monkeypatch.setattr(connection, "threading", SimpleNamespace(Thread=Worker))
    monkeypatch.setattr(account_link.wx, "CallAfter", lambda fn, *args: queue.append(lambda: fn(*args)))
    return window, scenario, calls, queue


@pytest.mark.parametrize("change", CHANGES)
@pytest.mark.parametrize("stage", ["status_get", "status_json", "status_error", "status_json_error",
    "reach_get", "reach_json", "host_probe", "nudge", "proof", "host_get", "host_json", "resolve",
    "deferral", "start_post"])
def test_poll_discards_superseded_observation_at_each_io(poll_api, change, stage):
    window, scenario, calls, queue = poll_api
    scenario.stage = stage
    scenario.status = "CLOSED" if stage in ("deferral", "start_post") else "CONNECTED"
    scenario.reachable = stage != "nudge"
    captured = []

    def hook(point):
        if point == stage or (stage == "deferral" and point == "host_probe"):
            replace_owner(window, change)
            captured.append((window.snapshot(), len(window.verdicts), len(window.writes)))

    window.hook = hook
    window.check_wa_connection_http()
    assert len(captured) == 1
    snapshot, verdict_count, write_count = captured[0]
    assert window.snapshot() == snapshot
    assert len(window.verdicts) == verdict_count
    assert len(window.writes) == write_count
    assert window.starts == []
    assert queue == []
    assert all("/api/old:key/" in url and auth == "Bearer old:key" for url, auth in calls)


def test_ordinary_poll_can_confirm_connected_while_recovery_owns_browser(poll_api):
    window, scenario, calls, queue = poll_api
    window._recovery_restart_active = True
    window.check_wa_connection_http()
    assert window._wa_connected is True
    assert window.my_jid == "old@c.us"
    assert ("my_jid", "old@c.us") in window.writes
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == [
        "status-session", "check-connection-session", "host-device"]


def test_unchanged_closed_poll_lifts_deferral_and_starts_once(poll_api):
    window, scenario, calls, queue = poll_api
    scenario.status = "CLOSED"
    window.check_wa_connection_http()
    assert window._offline_start_deferred_since is None
    assert window.starts == ["noted"]
    assert calls[-1][0].endswith("/api/old:key/start-session")


def test_a_terminal_bridge_failure_is_never_auto_started_again(poll_api):
    """The neonize bridge reports "terminalFailure" (neonize_bridge/session_lifecycle.py
    TERMINAL) after a ban, an outdated client or a replaced stream. Reporting
    CLOSED there made this 30 s poll call start-session for ever; any status
    outside CLOSED/DESTROYED/"" takes the "active state" branch instead: offline,
    no start, and not one of the unlinked states either (no logout wipe)."""
    window, scenario, calls, queue = poll_api
    scenario.status = "terminalFailure"
    assert "terminalFailure" not in cs.UNLINKED_STATES
    for _ in range(3):
        window.check_wa_connection_http()
    assert window._wa_connected is False
    assert window.starts == [] and window.disconnects == []
    assert [url.rsplit("/", 1)[-1] for url, _ in calls] == ["status-session"] * 3


@pytest.mark.parametrize("stage,expected_strikes", [("status_error", 8), ("status_json_error", 1)])
def test_current_owner_keeps_existing_http_failure_budget(poll_api, stage, expected_strikes):
    window, scenario, calls, queue = poll_api
    scenario.stage = stage
    window.check_wa_connection_http()
    assert window._wa_http_fail_strikes == expected_strikes
    assert window._wa_connected is False
    assert window.starts == []


def test_current_owner_still_records_a_real_negative_reachability(poll_api):
    window, scenario, calls, queue = poll_api
    scenario.reachable = False
    window._offline_probe_strikes = 0
    window._dead_browser_strikes = 0
    window.check_wa_connection_http()
    assert window._offline_probe_strikes == 1
    assert window._dead_browser_strikes == 1
    assert window.verdicts == [False]
    assert window.writes == []


@pytest.mark.parametrize("change", CHANGES)
def test_unlink_host_probe_cannot_latch_or_queue_for_new_owner(poll_api, change):
    window, scenario, calls, queue = poll_api
    window.hook = lambda point: replace_owner(window, change) if point == "unlink_probe" else None
    window._act_on_unlink_decision(cs.LOGOUT, log_label="synthetic")
    assert window._logout_handled is False
    assert queue == []


def test_queued_pairing_decision_checks_ownership_when_it_runs(poll_api):
    window, scenario, calls, queue = poll_api
    window._act_on_unlink_decision(cs.RESUME_FAILED, log_label="synthetic")
    assert len(queue) == 1
    replace_owner(window, "token")
    queue[0]()
    assert window.disconnects == []


def test_scheduled_dead_browser_restart_keeps_original_owner(poll_api):
    window, scenario, calls, queue = poll_api
    scenario.reachable = False
    window.check_wa_connection_http()
    assert len(scenario.workers) == 1
    replace_owner(window, "token")
    scenario.workers[0]()
    assert window.starts == []
