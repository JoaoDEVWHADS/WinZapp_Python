"""Tests for confirming a logout before destroying the local database.

check_wa_connection_http() used to call _on_disconnect() — which drops the token
and calls clear_local_data(), wiping the whole local database irreversibly — on
a *single* reading of status-session == QRCODE or notLogged.

That is a hair trigger. WhatsApp Web reports QRCODE transiently while a session
is still restoring: in a real log the session read INITIALIZING at 08:04:04 and
QRCODE at 08:04:35, and the wipe then fired twice inside the same second
(08:04:35,035 and 08:04:35,876) because two callers observed the same reading.

_logout_confirmed() now requires consecutive unlinked readings and fires at most
once. The health checker polls every ~30 s, so a genuine logout is still caught
inside a minute.
"""

import pytest

from main import MainWindow


class _Stub:
    _LOGOUT_CONFIRM_STRIKES = MainWindow._LOGOUT_CONFIRM_STRIKES
    _logout_confirmed = MainWindow._logout_confirmed


@pytest.fixture
def s():
    return _Stub()


@pytest.mark.parametrize("status", ["notLogged", "QRCODE"])
def test_one_reading_is_never_enough(s, status):
    assert s._logout_confirmed(status) is False


@pytest.mark.parametrize("status", ["notLogged", "QRCODE"])
def test_consecutive_readings_confirm(s, status):
    for _ in range(_Stub._LOGOUT_CONFIRM_STRIKES - 1):
        assert s._logout_confirmed(status) is False
    assert s._logout_confirmed(status) is True


@pytest.mark.parametrize("healthy", ["CONNECTED", "open", "INITIALIZING", "inChat", "CLOSED"])
def test_a_healthy_reading_in_between_resets_the_tally(s, healthy):
    """The exact reported shape: INITIALIZING, then a lone QRCODE. Nothing may
    be wiped on the strength of that."""
    assert s._logout_confirmed("QRCODE") is False
    assert s._logout_confirmed(healthy) is False
    assert s._logout_confirmed("QRCODE") is False, "tally must have restarted"


def test_it_fires_at_most_once(s):
    """Two callers can observe the same reading within the same second — the
    wipe must not run twice."""
    for _ in range(_Stub._LOGOUT_CONFIRM_STRIKES - 1):
        s._logout_confirmed("QRCODE")
    assert s._logout_confirmed("QRCODE") is True
    for _ in range(5):
        assert s._logout_confirmed("QRCODE") is False


def test_mixed_unlinked_statuses_still_count_together(s):
    """notLogged and QRCODE are both "the device is not linked" — alternating
    between them is still a consistent unlinked signal."""
    assert s._logout_confirmed("notLogged") is False
    assert s._logout_confirmed("QRCODE") is True


def test_a_genuine_logout_is_still_detected_promptly():
    """The guard must not turn a real logout into a permanent no-op: the health
    checker polls about every 30 s, so confirmation has to stay cheap."""
    assert MainWindow._LOGOUT_CONFIRM_STRIKES >= 2, "one reading must not suffice"
    assert MainWindow._LOGOUT_CONFIRM_STRIKES <= 3, "must confirm within ~90 s"


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


def test_works_without_prior_initialisation():
    """check_wa_connection_http() runs from several threads and can reach this
    before anything set the counter up."""
    class _Bare:
        _LOGOUT_CONFIRM_STRIKES = 2
        _logout_confirmed = MainWindow._logout_confirmed
    b = _Bare()
    assert b._logout_confirmed("QRCODE") is False
    assert b._logout_confirmed("QRCODE") is True
