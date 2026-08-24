"""A recent WPPConnect Socket.IO event now short-circuits
check_whatsapp_reachable() straight to True, without consulting either the
/check-connection-session probe or the outbound host-reachability probe.

Reported live: the user's home internet dropped, they switched to mobile
data, and messages kept arriving in an open group (with sound) for several
minutes — proof WPPConnect's own connection to WhatsApp was fine the whole
time — while the app kept insisting it was offline. WinZapp's Socket.IO
client talks to the LOCAL WPPConnect server over loopback, which never
drops just because the machine's own internet route changed, so live
Socket.IO traffic is a stronger and more direct signal than an independent
outbound HTTP probe that can get stuck (e.g. behind a stale negative DNS
cache entry) even after the real network has already recovered.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so check_whatsapp_reachable() and _note_live_wpp_event() are
exercised as plain functions against a small stub — same approach as
tests/test_session_probe_strikes.py.
"""

import time

from main import MainWindow


class _Stub:
    _OFFLINE_PROBE_STRIKES = MainWindow._OFFLINE_PROBE_STRIKES
    _LIVE_WPP_EVENT_FRESHNESS_SECONDS = MainWindow._LIVE_WPP_EVENT_FRESHNESS_SECONDS
    check_whatsapp_reachable = MainWindow.check_whatsapp_reachable
    _note_live_wpp_event = MainWindow._note_live_wpp_event

    def __init__(self, last_live_ts=0.0):
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "test-token"
        self._wa_connected = False
        self._offline_probe_strikes = 3  # would already read as offline otherwise
        self._last_live_wpp_event_ts = last_live_ts
        self.session_probe_calls = 0
        self.host_probes = 0

    def _probe_whatsapp_host(self):
        self.host_probes += 1
        return False  # would report offline if this were ever consulted


def _fake_session_probe_never_called(monkeypatch, stub):
    def _boom(*a, **kw):
        stub.session_probe_calls += 1
        raise AssertionError("check-connection-session must not be queried")

    monkeypatch.setattr("main.requests.get", _boom)


class TestLiveEventShortCircuitsReachability:
    def test_a_fresh_live_event_reports_reachable_without_any_probe(self, monkeypatch):
        stub = _Stub(last_live_ts=time.time())
        _fake_session_probe_never_called(monkeypatch, stub)

        assert stub.check_whatsapp_reachable() is True
        assert stub.host_probes == 0
        assert stub._offline_probe_strikes == 0

    def test_an_event_right_at_the_freshness_edge_still_counts(self, monkeypatch):
        stub = _Stub(last_live_ts=time.time() - (MainWindow._LIVE_WPP_EVENT_FRESHNESS_SECONDS - 1))
        _fake_session_probe_never_called(monkeypatch, stub)

        assert stub.check_whatsapp_reachable() is True

    def test_a_stale_event_falls_through_to_the_normal_probes(self, monkeypatch):
        stub = _Stub(last_live_ts=time.time() - (MainWindow._LIVE_WPP_EVENT_FRESHNESS_SECONDS + 1))

        class _Resp:
            status_code = 200
            def json(self):
                return {"status": True}

        monkeypatch.setattr("main.requests.get", lambda *a, **kw: _Resp())

        result = stub.check_whatsapp_reachable()

        # Falls through to the host probe (stubbed to report unreachable) —
        # proving the stale timestamp did NOT short-circuit anything.
        assert stub.host_probes == 1
        assert result is False

    def test_no_live_event_ever_seen_falls_through_normally(self, monkeypatch):
        stub = _Stub(last_live_ts=0.0)

        class _Resp:
            status_code = 200
            def json(self):
                return {"status": True}

        monkeypatch.setattr("main.requests.get", lambda *a, **kw: _Resp())

        stub.check_whatsapp_reachable()

        assert stub.host_probes == 1


class TestNoteLiveWppEvent:
    def test_stamps_the_current_time(self):
        stub = _Stub()
        before = time.time()

        stub._note_live_wpp_event()

        assert before <= stub._last_live_wpp_event_ts <= time.time()
