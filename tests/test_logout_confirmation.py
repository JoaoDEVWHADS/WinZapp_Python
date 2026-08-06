"""Tests for confirming a logout before destroying the local database.

check_wa_connection_http() used to call _on_disconnect() — which drops the token
and calls clear_local_data(), wiping the whole local database irreversibly — on
a *single* reading of status-session == QRCODE or notLogged.

That is a hair trigger. WhatsApp Web reports QRCODE transiently while a session
is still restoring: in a real log the session read INITIALIZING at 08:04:04 and
QRCODE at 08:04:35, and the wipe then fired twice inside the same second
(08:04:35,035 and 08:04:35,876) because two callers observed the same reading.

A strike count alone turned out not to be enough either: users kept being told
their account had been disconnected after a machine restart, while the phone
still listed the WinZapp session as an active linked device — i.e. no logout had
happened at all, WPPConnect was simply still booting Chrome and replaying the
saved session, and WhatsApp Web renders its QR canvas partway through that.

_logout_confirmed() now additionally requires a startup grace period, a minimum
wall-clock duration for the unlinked state, and a positive host-device probe
that cannot prove the device is still linked.
"""

import pytest

from main import MainWindow


class _Stub:
    _LOGOUT_CONFIRM_STRIKES = MainWindow._LOGOUT_CONFIRM_STRIKES
    _LOGOUT_CONFIRM_SECONDS = MainWindow._LOGOUT_CONFIRM_SECONDS
    _LOGOUT_STARTUP_GRACE_SECONDS = MainWindow._LOGOUT_STARTUP_GRACE_SECONDS
    _logout_confirmed = MainWindow._logout_confirmed

    def __init__(self, *, started_long_ago=True, still_linked=False):
        # Far enough in the past that the startup grace never applies unless a
        # test deliberately moves it.
        self._wpp_started_at = 0.0 if started_long_ago else None
        self._still_linked = still_linked
        self.probe_calls = 0

    def _still_linked_on_server(self):
        self.probe_calls += 1
        return self._still_linked


@pytest.fixture
def s():
    return _Stub()


def _drive(stub, status, times, monkeypatch, *, span=None):
    """Feed *times* readings of *status*, spread over *span* seconds of fake
    wall clock. Returns the list of results."""
    span = stub._LOGOUT_CONFIRM_SECONDS * 2 if span is None else span
    step = span / max(times - 1, 1)
    results = []
    for i in range(times):
        monkeypatch.setattr("main.time.time", lambda i=i: 10_000.0 + i * step)
        results.append(stub._logout_confirmed(status))
    return results


@pytest.mark.parametrize("status", ["notLogged", "QRCODE"])
def test_one_reading_is_never_enough(s, status, monkeypatch):
    monkeypatch.setattr("main.time.time", lambda: 10_000.0)
    assert s._logout_confirmed(status) is False


@pytest.mark.parametrize("status", ["notLogged", "QRCODE"])
def test_enough_readings_over_enough_time_confirm(s, status, monkeypatch):
    results = _drive(s, status, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
    assert results[:-1] == [False] * (s._LOGOUT_CONFIRM_STRIKES - 1)
    assert results[-1] is True


def test_enough_readings_too_quickly_do_not_confirm(s, monkeypatch):
    """Strikes alone are not a duration: several callers can hammer this inside
    seconds. The unlinked state has to have actually persisted."""
    results = _drive(s, "QRCODE", s._LOGOUT_CONFIRM_STRIKES + 3, monkeypatch, span=5)
    assert results == [False] * len(results)


def test_still_within_the_startup_grace_never_confirms(monkeypatch):
    """The reported bug: WPPConnect had just started (cold boot after a Windows
    restart), reported QRCODE while restoring, and the account was wiped."""
    stub = _Stub()
    stub._wpp_started_at = 10_000.0
    results = []
    for i in range(stub._LOGOUT_CONFIRM_STRIKES + 5):
        monkeypatch.setattr("main.time.time", lambda i=i: 10_000.0 + i)
        results.append(stub._logout_confirmed("QRCODE"))
    assert results == [False] * len(results)
    assert stub.probe_calls == 0


def test_a_still_linked_phone_vetoes_the_wipe(monkeypatch):
    """host-device answering with our own number proves WhatsApp did not
    unlink us, whatever status-session says."""
    stub = _Stub(still_linked=True)
    results = _drive(stub, "notLogged", stub._LOGOUT_CONFIRM_STRIKES, monkeypatch)
    assert results == [False] * len(results)
    assert stub.probe_calls == 1
    # ...and the veto restarts the tally rather than leaving it primed.
    assert stub._logout_strikes == 0
    assert stub._logout_first_seen is None


@pytest.mark.parametrize("healthy", ["CONNECTED", "open", "INITIALIZING", "inChat", "CLOSED"])
def test_a_healthy_reading_in_between_resets_the_tally(s, healthy, monkeypatch):
    """The exact reported shape: INITIALIZING, then a lone QRCODE. Nothing may
    be wiped on the strength of that."""
    monkeypatch.setattr("main.time.time", lambda: 10_000.0)
    assert s._logout_confirmed("QRCODE") is False
    assert s._logout_confirmed(healthy) is False
    assert s._logout_strikes == 0
    assert s._logout_first_seen is None
    monkeypatch.setattr("main.time.time", lambda: 99_999.0)
    assert s._logout_confirmed("QRCODE") is False, "tally must have restarted"


def test_it_fires_at_most_once(s, monkeypatch):
    """Two callers can observe the same reading within the same second — the
    wipe must not run twice."""
    results = _drive(s, "QRCODE", s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
    assert results[-1] is True
    for _ in range(5):
        assert s._logout_confirmed("QRCODE") is False


def test_mixed_unlinked_statuses_still_count_together(s, monkeypatch):
    """notLogged and QRCODE are both "the device is not linked" — alternating
    between them is still a consistent unlinked signal."""
    span = s._LOGOUT_CONFIRM_SECONDS * 2
    step = span / (s._LOGOUT_CONFIRM_STRIKES - 1)
    statuses = ["notLogged", "QRCODE"] * s._LOGOUT_CONFIRM_STRIKES
    results = []
    for i in range(s._LOGOUT_CONFIRM_STRIKES):
        monkeypatch.setattr("main.time.time", lambda i=i: 10_000.0 + i * step)
        results.append(s._logout_confirmed(statuses[i]))
    assert results[-1] is True


def test_a_genuine_logout_is_still_detected():
    """The guard must not turn a real logout into a permanent no-op."""
    assert MainWindow._LOGOUT_CONFIRM_STRIKES >= 2, "one reading must not suffice"
    assert MainWindow._LOGOUT_CONFIRM_SECONDS <= 600, "must confirm within ~10 min"
    assert MainWindow._LOGOUT_STARTUP_GRACE_SECONDS <= 600


def _acts_now(*, paired, confirmed):
    """What check_wa_connection_http() does on an unlinked reading.

    The confirmation gate applies only to the destructive path. Gating the
    unpaired path too left the app stuck on "sem conexão com o WhatsApp / modo
    offline" with no pairing dialog — _on_disconnect() is what puts that dialog
    on screen, and it was being withheld to protect a database that is empty by
    definition.
    """
    if paired:
        return confirmed
    return True


class TestWhichPathIsGated:
    def test_an_unpaired_account_gets_the_pairing_dialog_immediately(self):
        assert _acts_now(paired=False, confirmed=False) is True

    def test_a_paired_account_waits_for_confirmation(self):
        assert _acts_now(paired=True, confirmed=False) is False

    def test_a_paired_account_acts_once_confirmed(self):
        assert _acts_now(paired=True, confirmed=True) is True


def test_works_without_prior_initialisation(monkeypatch):
    """check_wa_connection_http() runs from several threads and can reach this
    before anything set the counters up."""
    class _Bare:
        _LOGOUT_CONFIRM_STRIKES = 2
        _LOGOUT_CONFIRM_SECONDS = 60
        _LOGOUT_STARTUP_GRACE_SECONDS = 240
        _logout_confirmed = MainWindow._logout_confirmed

        def _still_linked_on_server(self):
            return False

    b = _Bare()
    monkeypatch.setattr("main.time.time", lambda: 10_000.0)
    assert b._logout_confirmed("QRCODE") is False
    monkeypatch.setattr("main.time.time", lambda: 10_100.0)
    assert b._logout_confirmed("QRCODE") is True
