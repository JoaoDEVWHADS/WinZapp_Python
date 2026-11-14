"""A session restart must not start a browser while WhatsApp is unreachable.

Measured on 2026-09-26, after a laptop slept 2 h 17 min:

    15:37:22  resume; status-session CONNECTED, reconnect-socket-stream 500
              "Attempted to use detached Frame" -> _restart_wpp_session()
    15:37:38  close-session done, start-session POSTed -- DNS still failing
              (NameResolutionError for web.whatsapp.com)
    15:37:41  Node: Authenticated -> Current state: SYNCING
              -> "Checking phone is connected..." and nothing after it
    15:38 ... status-session INITIALIZING every 30 s, "skipping
              /start-session to avoid browser conflict"
    17:42     network back; still INITIALIZING, still offline

wppconnect's waitForInChat() polls WPP.conn.isMainReady() with no exit because
deviceSyncTimeout is pinned to 0, and nothing on the Python side restarts an
INITIALIZING session (the post-resume one is gated off). A session left CLOSED
instead is picked up by the health loop's CLOSED auto-start — so the restart
now leaves it CLOSED, and that auto-start waits for the network.
"""

import ast
import inspect
import textwrap
import time
import types

import pytest
import requests

import connection_state as cs
import main
from main import MainWindow
from main_window import connection as connection_module
from tests.god_modules import patch_main_global


# ── The pure decisions ──────────────────────────────────────────────────────


class TestOfflineStartStillDeferred:
    def test_network_back_lifts_it(self):
        assert cs.offline_start_still_deferred(
            network_up=True, probe_proven=True, deferred_for=10_000) is False

    def test_a_proven_probe_outlasts_the_measured_outage(self):
        """The field outage lasted 2 h 05 min: a proven probe must hold the
        start through it, or it lands back in the offline window it avoids."""
        assert cs.offline_start_still_deferred(
            network_up=False, probe_proven=True, deferred_for=2 * 3600 + 5 * 60) is True

    def test_a_proven_probe_is_still_capped(self):
        """Proof is usually earned on another network; a hotel portal or an
        authenticated proxy only the browser gets through must not keep the
        account offline for good."""
        cap = cs.OFFLINE_START_PROVEN_PROBE_CAP_SECONDS
        assert cap >= 2 * 3600 + 5 * 60
        assert cs.offline_start_still_deferred(
            network_up=False, probe_proven=True, deferred_for=cap - 1) is True
        assert cs.offline_start_still_deferred(
            network_up=False, probe_proven=True, deferred_for=cap) is False

    def test_an_unproven_probe_holds_it_only_up_to_the_cap(self):
        cap = cs.OFFLINE_START_UNPROVEN_PROBE_CAP_SECONDS
        assert cs.offline_start_still_deferred(
            network_up=False, probe_proven=False, deferred_for=cap - 1) is True
        assert cs.offline_start_still_deferred(
            network_up=False, probe_proven=False, deferred_for=cap) is False


class TestCountsTowardProfileHealth:
    def test_a_closed_held_on_purpose_is_not_a_failed_start_cycle(self):
        """Three counted CLOSED readings restore a profile snapshot — 90 s of
        waiting for the network must not be able to do that."""
        assert cs.counts_toward_profile_health("CLOSED", True) is False
        assert cs.counts_toward_profile_health("closed", True) is False

    def test_every_status_the_closed_branch_handles_is_exempt(self):
        """The CLOSED auto-start branch also handles DESTROYED and an empty
        answer; while a start is held on purpose they are not failures either."""
        assert cs.counts_toward_profile_health("DESTROYED", True) is False
        assert cs.counts_toward_profile_health("", True) is False
        assert cs.counts_toward_profile_health(None, True) is False

    def test_everything_else_is_still_observed(self):
        assert cs.counts_toward_profile_health("CLOSED", False) is True
        assert cs.counts_toward_profile_health("CONNECTED", True) is True
        assert cs.counts_toward_profile_health("INITIALIZING", True) is True
        assert cs.counts_toward_profile_health("", False) is True


# ── _restart_wpp_session() ──────────────────────────────────────────────────


class _RestartStub:
    _restart_wpp_session = MainWindow._restart_wpp_session
    _RECOVERY_CLOSE_WAIT = MainWindow._RECOVERY_CLOSE_WAIT
    _RESTART_PROFILE_RELEASE_WAIT = MainWindow._RESTART_PROFILE_RELEASE_WAIT
    _WPP_SESSION_RESTART_COOLDOWN = MainWindow._WPP_SESSION_RESTART_COOLDOWN

    def __init__(self, network_up):
        self.token = "sess123:tok"
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.network_up = network_up

    def wait_for_profile_release(self, session_name, timeout=20.0):
        return True

    def _wait_for_status(self, predicate, timeout, stop_when_connected=False):
        return "CLOSED"

    def _probe_whatsapp_host(self):
        return self.network_up


@pytest.fixture
def posted(monkeypatch):
    urls = []

    def _post(url, **kwargs):
        urls.append(url)
        return types.SimpleNamespace(status_code=200, text="{}")

    patch_main_global(monkeypatch, "api_post", _post)
    return urls


class TestRestartLeavesTheSessionClosedWhileOffline:
    def test_no_route_means_no_start_session(self, posted):
        stub = _RestartStub(network_up=False)

        assert stub._restart_wpp_session() is False
        assert any("close-session" in u for u in posted)
        assert not any("start-session" in u for u in posted)
        assert stub._offline_start_deferred_since is not None

    def test_a_reachable_network_starts_it_as_before(self, posted):
        stub = _RestartStub(network_up=True)

        assert stub._restart_wpp_session() is True
        assert any("start-session" in u for u in posted)
        assert getattr(stub, "_offline_start_deferred_since", None) is None

    def test_a_second_deferral_keeps_the_original_clock(self, posted):
        """Otherwise every deferred restart would push the unproven-probe cap
        back and the fallback start would never come."""
        stub = _RestartStub(network_up=False)
        stub._offline_start_deferred_since = 123.0

        stub._restart_wpp_session()

        assert stub._offline_start_deferred_since == 123.0

    def test_the_restart_still_ends_its_own_teardown_window(self, posted):
        """The health loop's CLOSED auto-start is what picks the session up
        later, so the restart must not leave its re-entry flag set."""
        stub = _RestartStub(network_up=False)
        stub._restart_wpp_session()
        assert stub._restarting_wpp_session is False


# ── _offline_start_deferral_holds() ─────────────────────────────────────────


class _HoldStub:
    _offline_start_deferral_holds = MainWindow._offline_start_deferral_holds

    def __init__(self, *, since, network_up, proven):
        self.token = "synthetic-session:key"
        self.wpp_server = "http://synthetic.invalid"
        self.wpp_port = 6300
        self._offline_start_deferred_since = since
        self.network_up = network_up
        self._whatsapp_probe_proven = proven
        self.probes = 0

    def _probe_whatsapp_host(self):
        self.probes += 1
        return self.network_up


class TestOfflineStartDeferralHolds:
    def test_nothing_deferred_means_no_probe_at_all(self):
        """Asked on every CLOSED reading — must not add a network round trip
        to the ordinary case."""
        stub = _HoldStub(since=None, network_up=False, proven=True)
        assert stub._offline_start_deferral_holds() is False
        assert stub.probes == 0

    def test_holds_while_the_network_is_down(self):
        stub = _HoldStub(since=time.monotonic(), network_up=False, proven=True)
        assert stub._offline_start_deferral_holds() is True
        assert stub._offline_start_deferred_since is not None

    def test_lifts_and_clears_once_the_network_answers(self):
        stub = _HoldStub(since=time.monotonic() - 7000, network_up=True, proven=True)
        assert stub._offline_start_deferral_holds() is False
        assert stub._offline_start_deferred_since is None

    def test_an_unproven_probe_gives_up_after_the_cap(self):
        past_cap = time.monotonic() - cs.OFFLINE_START_UNPROVEN_PROBE_CAP_SECONDS - 1
        stub = _HoldStub(since=past_cap, network_up=False, proven=False)
        assert stub._offline_start_deferral_holds() is False
        assert stub._offline_start_deferred_since is None

    def test_a_proven_probe_gives_up_after_its_own_cap(self, caplog):
        """And log.log does not claim the network came back: it did not."""
        past_cap = time.monotonic() - cs.OFFLINE_START_PROVEN_PROBE_CAP_SECONDS - 1
        stub = _HoldStub(since=past_cap, network_up=False, proven=True)
        with caplog.at_level("INFO"):
            assert stub._offline_start_deferral_holds() is False
        assert stub._offline_start_deferred_since is None
        assert "network still unreachable" in caplog.text
        assert "network back" not in caplog.text

    def test_the_log_says_back_only_when_it_answered(self, caplog):
        stub = _HoldStub(since=time.monotonic() - 60, network_up=True, proven=False)
        with caplog.at_level("INFO"):
            stub._offline_start_deferral_holds()
        assert "network back" in caplog.text


# ── Proving the probe ───────────────────────────────────────────────────────


class _ProbeStub:
    _probe_whatsapp_host = MainWindow._probe_whatsapp_host


class _Session:
    """The probe's session, answering from the test instead of the network."""

    def __init__(self, head):
        self.head = head


class TestProbeProof:
    def test_an_answer_proves_the_probe(self, monkeypatch):
        monkeypatch.setattr(connection_module, "_probe_session",
                            _Session(lambda *a, **kw: None))
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is True
        assert stub._whatsapp_probe_proven is True

    def test_no_route_proves_nothing(self, monkeypatch):
        def _fail(*a, **kw):
            raise requests.exceptions.ConnectionError("no dns")

        monkeypatch.setattr(connection_module, "_probe_session", _Session(_fail))
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is False
        assert getattr(stub, "_whatsapp_probe_proven", False) is False


class TestAnInterceptedCertificateIsNotAnOutage:
    """An antivirus that scans HTTPS re-signs web.whatsapp.com with a root only
    Windows' store holds. Verified against certifi that is an SSLError — a
    ConnectionError subclass, so "no route" — and the offline start deferral
    held a working machine's session closed for up to ten minutes.

    Simulated at the transport, with no network: every adapter answers with a
    certificate failure unless it carries the context core.tls_trust built
    from the system store, which is the one thing that verifies on such a
    machine.
    """

    @pytest.fixture
    def intercepted(self, monkeypatch):
        import ssl

        from core import tls_trust

        system_context = ssl.create_default_context()
        monkeypatch.setattr(tls_trust, "system_ssl_context", lambda: system_context)
        sent = []

        def _send(adapter, request, **kwargs):
            sent.append(request.url)
            if getattr(adapter, "_ssl_context", None) is system_context:
                response = requests.Response()
                response.status_code = 302
                response.url = request.url
                response.request = request
                return response
            raise requests.exceptions.SSLError(
                "certificate verify failed: unable to get local issuer certificate"
            )

        monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _send)
        # Built again under the simulation, not reused from an earlier test.
        monkeypatch.setattr(connection_module, "_probe_session", None)
        return sent

    def test_the_probe_verifies_through_the_system_store(self, intercepted):
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is True
        assert stub._whatsapp_probe_proven is True
        assert intercepted == ["https://web.whatsapp.com/"]

    def test_the_certifi_session_is_what_read_it_as_offline(self, intercepted, monkeypatch):
        """The simulation is faithful to the bug, and the classification is
        untouched: on the bundled CA list the same machine is still "no
        route". Only where the certificate is checked moved."""
        monkeypatch.setattr(connection_module, "_probe_session", requests.Session())
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is False
        assert getattr(stub, "_whatsapp_probe_proven", False) is False


class TestAStoreThatCannotBuildTheChainIsNotAnOutageEither:
    """The inverse machine: Windows' root updates switched off by policy, or an
    isolated image, so the system store cannot build web.whatsapp.com's chain
    while certifi's bundled list can. Moving the probe to the system store
    alone would have read that machine as offline — and the probe feeds the
    automatic offline mode, the startup grace, the restart deferral and the
    resume. An SSLError there is retried once on http_pool's certifi session;
    either verifying means reachable."""

    @staticmethod
    def _sessions(monkeypatch, system, bundled):
        calls = []

        def _answer(name, outcome):
            def _head(url, **kwargs):
                calls.append(name)
                if outcome is not None:
                    raise outcome
            return _head

        monkeypatch.setattr(connection_module, "_probe_session",
                            _Session(_answer("system", system)))
        monkeypatch.setattr(connection_module, "_http_session",
                            _Session(_answer("bundled", bundled)))
        return calls

    def test_the_system_store_refusing_and_certifi_verifying_is_reachable(self, monkeypatch):
        calls = self._sessions(
            monkeypatch,
            system=requests.exceptions.SSLError("unable to get local issuer certificate"),
            bundled=None,
        )
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is True
        assert stub._whatsapp_probe_proven is True
        assert calls == ["system", "bundled"]

    def test_the_system_store_verifying_asks_nothing_more(self, monkeypatch):
        calls = self._sessions(monkeypatch, system=None,
                               bundled=AssertionError("must not be asked"))
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is True
        assert calls == ["system"]

    def test_both_refusing_is_the_answer_a_certificate_failure_always_had(self, monkeypatch):
        calls = self._sessions(
            monkeypatch,
            system=requests.exceptions.SSLError("system: certificate verify failed"),
            bundled=requests.exceptions.SSLError("certifi: certificate verify failed"),
        )
        stub = _ProbeStub()
        assert stub._probe_whatsapp_host() is False
        assert getattr(stub, "_whatsapp_probe_proven", False) is False
        assert calls == ["system", "bundled"]

    def test_certifi_finding_no_route_is_still_offline(self, monkeypatch):
        calls = self._sessions(
            monkeypatch,
            system=requests.exceptions.SSLError("certificate verify failed"),
            bundled=requests.exceptions.ConnectTimeout("timed out"),
        )
        assert _ProbeStub()._probe_whatsapp_host() is False
        assert calls == ["system", "bundled"]

    def test_a_route_failure_is_not_retried(self, monkeypatch):
        """Only a certificate refusal earns the second try: no DNS is no DNS
        on either list, and a second HEAD would only double the wait."""
        calls = self._sessions(monkeypatch,
                               system=requests.exceptions.ConnectionError("no dns"),
                               bundled=AssertionError("must not be asked"))
        assert _ProbeStub()._probe_whatsapp_host() is False
        assert calls == ["system"]


class _ProofStub:
    _prove_whatsapp_probe_once = MainWindow._prove_whatsapp_probe_once
    _PROBE_PROOF_RETRY_SECONDS = MainWindow._PROBE_PROOF_RETRY_SECONDS

    def _probe_whatsapp_host(self):
        return True


@pytest.fixture
def threads(monkeypatch):
    started = []

    class _Thread:
        def __init__(self, target=None, daemon=None, name=None, **kw):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(main.threading, "Thread", _Thread)
    return started


class TestProveWhatsappProbeOnce:
    def test_fires_one_background_probe(self, threads):
        stub = _ProofStub()
        stub._prove_whatsapp_probe_once()
        assert len(threads) == 1

    def test_a_proven_probe_is_never_probed_again(self, threads):
        stub = _ProofStub()
        stub._whatsapp_probe_proven = True
        stub._prove_whatsapp_probe_once()
        assert threads == []

    def test_a_failed_proof_is_retried_only_after_the_interval(self, threads):
        """Called on every CONNECTED poll — one HEAD per 30 s would be noise."""
        stub = _ProofStub()
        stub._prove_whatsapp_probe_once()
        stub._prove_whatsapp_probe_once()
        assert len(threads) == 1
        stub._whatsapp_probe_proof_at -= stub._PROBE_PROOF_RETRY_SECONDS
        stub._prove_whatsapp_probe_once()
        assert len(threads) == 2


# ── Wiring inside check_wa_connection_http() ────────────────────────────────


def _health_check_tree():
    src = textwrap.dedent(inspect.getsource(MainWindow.check_wa_connection_http))
    return ast.parse(src)


def _called(tree, attr):
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == attr]


class TestHealthCheckWiring:
    def test_the_closed_branch_asks_the_deferral(self):
        tree = _health_check_tree()
        assert len(_called(tree, "_offline_start_deferral_holds")) == 1

    def test_the_deferral_is_asked_only_when_nothing_else_blocks(self):
        """It probes the network; the other four guards are free."""
        src = textwrap.dedent(inspect.getsource(MainWindow.check_wa_connection_http))
        assert "if not block and self._offline_start_deferral_holds():" in src

    def test_profile_health_is_fed_through_the_filter(self):
        tree = _health_check_tree()
        assert len(_called(tree, "counts_toward_profile_health")) == 1

    def test_a_connected_reading_clears_the_deferral_and_proves_the_probe(self):
        tree = _health_check_tree()
        assert len(_called(tree, "_prove_whatsapp_probe_once")) == 1
        cleared = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(getattr(t, "attr", "") == "_offline_start_deferred_since"
                    for t in n.targets)
            and isinstance(n.value, ast.Constant) and n.value.value is None
        ]
        assert len(cleared) == 1
