"""Tests for the guard around a local HTTP 401/403 on /status-session.

check_wa_connection_http() used to call _on_disconnect() -- drop the token
and wipe the whole local database -- on a *single* 401/403 response from our
own local Node server, with none of the protection the sibling
"unlinked status string" path applies (startup grace via never having
connected this run yet, _auto_restart_grace_active(), several consecutive
confirmations spread over minutes). Reported live: a paired account got
wiped before the app had even finished loading the chat list on a cold
start.

A 401/403 here is weaker evidence of a real WhatsApp-side unlink than a
notLogged/QRCODE reading: it never reaches WhatsApp at all, since our own
auth middleware rejected the request before WPPConnect saw it -- which can
just as easily mean the local session/secret-key state on a freshly started
or just-switched-to Node process is not ready yet.

_handle_local_auth_rejected() now routes this through the exact same
connection_state.classify_unlink_candidate() strike/timing machinery the
notLogged/QRCODE path uses, sharing the same counters so a healthy reading
in between resets both.
"""

import threading

import pytest

from main import MainWindow


class _Recorder:
    def __init__(self):
        self.played = 0

    def play(self):
        self.played += 1


class _I18n:
    @staticmethod
    def t(key):
        return key


class _Stub:
    _LOGOUT_CONFIRM_STRIKES = MainWindow._LOGOUT_CONFIRM_STRIKES
    _RESUME_FAIL_STRIKES = MainWindow._RESUME_FAIL_STRIKES
    _handle_local_auth_rejected = MainWindow._handle_local_auth_rejected
    _act_on_unlink_decision = MainWindow._act_on_unlink_decision

    def __init__(self, *, paired=True, restart_grace_active=False, still_linked=False):
        self.settings = {"privateinfo": {"paired": paired}}
        self._wa_connect_announced = False
        self._wa_connected = True
        self._unlink_decision_lock = threading.Lock()
        self._restart_grace_active = restart_grace_active
        self._still_linked = still_linked
        self.still_linked_probe_calls = 0
        self.error_sound = _Recorder()
        self.i18n = _I18n()
        self.app_name = "WinZapp"
        self.disconnect_calls = []
        self._last_strike_ts = 0.0

    def _auto_restart_grace_active(self):
        return self._restart_grace_active

    def _still_linked_on_server(self):
        self.still_linked_probe_calls += 1
        return self._still_linked

    def _on_disconnect(self, wipe=True):
        self.disconnect_calls.append(wipe)


@pytest.fixture(autouse=True)
def _no_wx(monkeypatch):
    """wx.CallAfter/wx.MessageBox would need a running app; run inline and
    no-op the message box."""
    monkeypatch.setattr("main.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr("main.wx.MessageBox", lambda *a, **kw: None)
    monkeypatch.setattr("main.wx.OK", 0, raising=False)
    monkeypatch.setattr("main.wx.ICON_ERROR", 0, raising=False)


def _feed(stub, times, monkeypatch, *, span=None):
    """Feed *times* consecutive 401 readings, spread over *span* seconds of
    fake wall clock (well past connection_state.STRIKE_MIN_INTERVAL_SECONDS
    apart by default, so every reading counts)."""
    import connection_state as cs
    span = cs.STRIKE_MIN_INTERVAL_SECONDS * 2 * times if span is None else span
    step = span / max(times - 1, 1)
    for i in range(times):
        monkeypatch.setattr("main.time.time", lambda i=i: 10_000.0 + i * step)
        stub._handle_local_auth_rejected(401)


class TestUnpaired:
    def test_goes_straight_to_pairing_no_wipe_decision_needed(self):
        """Nothing to lose: _on_disconnect() itself is what shows the pairing
        dialog, called with its default (wipe=True) since the database is
        empty by definition."""
        s = _Stub(paired=False)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == [True]


class TestAutoRestartGrace:
    def test_does_not_disconnect_while_a_restart_is_settling(self):
        s = _Stub(restart_grace_active=True)
        for _ in range(10):
            s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == []

    def test_resets_the_tally(self):
        s = _Stub(restart_grace_active=True)
        s._logout_strikes = 99
        s._resume_fail_strikes = 99
        s._logout_first_seen = 123.0
        s._handle_local_auth_rejected(401)
        assert s._logout_strikes == 0
        assert s._resume_fail_strikes == 0
        assert s._logout_first_seen is None


class TestNeverConnectedThisRun:
    """The cold-start case from the report: the app has not announced a live
    connection yet, so this must never reach the destructive wipe path,
    only the non-destructive pairing-dialog-after-a-long-timeout path."""

    def test_a_single_401_never_disconnects(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = False
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == []

    def test_only_a_long_run_of_401s_shows_pairing_without_wiping(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = False
        _feed(s, s._RESUME_FAIL_STRIKES, monkeypatch)
        assert s.disconnect_calls == [False]

    def test_a_huge_strike_count_still_never_wipes_before_connecting(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = False
        s._logout_strikes = 100_000
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == []


class TestConnectedThisRunThenRejected:
    def test_a_single_401_does_not_confirm_a_logout(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == []

    def test_enough_consecutive_401s_confirm_and_wipe(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == [True]
        assert s.error_sound.played == 1

    def test_it_fires_at_most_once(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == [True]
        s._handle_local_auth_rejected(401)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == [True]


class TestHealthyReadingResetsTheSharedTally:
    """The 401 path shares its strike counters with the notLogged/QRCODE
    path (check_wa_connection_http resets them on any non-unlinked status),
    so a successful poll in between must clear a 401 streak too."""

    def test_resetting_the_shared_counters_clears_a_401_streak(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        for _ in range(s._LOGOUT_CONFIRM_STRIKES - 1):
            s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == []

        # A healthy status-session reading resets the same attributes
        # check_wa_connection_http() itself resets on any non-unlinked status.
        s._logout_strikes = 0
        s._resume_fail_strikes = 0
        s._last_strike_ts = 0.0
        s._logout_first_seen = None

        monkeypatch.setattr("main.time.time", lambda: 99_999.0)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == [], "must restart the tally, not confirm immediately"


class TestStrikeMinInterval:
    def test_readings_too_close_together_do_not_count(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES + 3, monkeypatch, span=1.0)
        assert s.disconnect_calls == []


class TestStillLinkedVetoesTheWipe:
    """The final, independent check before any destructive action: even
    once strikes/timing say LOGOUT, host-device answering with a real phone
    number proves the session is not actually unlinked -- whatever local
    401s said was wrong."""

    def test_a_still_linked_phone_vetoes_the_wipe(self, monkeypatch):
        s = _Stub(still_linked=True)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == []
        assert s.still_linked_probe_calls == 1

    def test_the_veto_resets_the_tally_instead_of_leaving_it_primed(self, monkeypatch):
        s = _Stub(still_linked=True)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s._logout_strikes == 0
        assert s._resume_fail_strikes == 0
        assert s._logout_first_seen is None

    def test_the_probe_only_runs_once_confirmed_not_on_every_reading(self, monkeypatch):
        s = _Stub(still_linked=False)
        s._wa_connect_announced = True
        for _ in range(s._LOGOUT_CONFIRM_STRIKES - 1):
            s._handle_local_auth_rejected(401)
        assert s.still_linked_probe_calls == 0

    def test_the_probe_is_not_consulted_for_resume_failed(self, monkeypatch):
        """The still-linked veto only guards the destructive LOGOUT outcome
        -- RESUME_FAILED never wipes anything in the first place, so there
        is nothing for the extra probe to protect against."""
        s = _Stub(still_linked=True)
        s._wa_connect_announced = False
        _feed(s, s._RESUME_FAIL_STRIKES, monkeypatch)
        assert s.disconnect_calls == [False]
        assert s.still_linked_probe_calls == 0
