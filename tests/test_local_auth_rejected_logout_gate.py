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

import json
import threading

import pytest

import connection_state as cs
from app_paths import resource_path
from main import MainWindow


class _Recorder:
    def __init__(self):
        self.played = 0

    def play(self):
        self.played += 1


def _real_translations():
    """The locale the app defaults to, loaded exactly as I18n does.

    Not a `lambda key: key` stub: several of these strings carry named
    placeholders the call sites have to fill by keyword, and a bare key name
    has no placeholders at all — so a `.format(positional)` bug passed against
    the stub and raised KeyError in front of the user. That is precisely what
    shipped here: the confirmed-logout branch formatted t("error") ("Erro do
    {app_name}") positionally, so it raised while building wx.MessageBox's
    arguments and the _on_disconnect() call on the next line never ran, with
    _logout_handled already latched so nothing retried. See also
    tests/test_translation_format_call_sites.py, which checks the same
    property across every call site rather than only the ones a test reaches.
    """
    with open(resource_path("languages", "pt-BR.json"), "r", encoding="utf-8") as f:
        return json.load(f)


_TRANSLATIONS = _real_translations()


class _I18n:
    @staticmethod
    def t(key):
        # I18n.t() itself is translations.get(key, key) — mirrored so a key
        # missing from the locale behaves here the way it does in the app.
        return _TRANSLATIONS.get(key, key)


class _Stub:
    _LOGOUT_CONFIRM_STRIKES = MainWindow._LOGOUT_CONFIRM_STRIKES
    _RESUME_FAIL_STRIKES = MainWindow._RESUME_FAIL_STRIKES
    _STILL_LINKED_VETO_LIMIT = MainWindow._STILL_LINKED_VETO_LIMIT
    _handle_local_auth_rejected = MainWindow._handle_local_auth_rejected
    _act_on_unlink_decision = MainWindow._act_on_unlink_decision

    def __init__(self, *, paired=True, restart_grace_active=False,
                 probe=cs.LINK_PROBE_UNLINKED):
        self.settings = {"privateinfo": {"paired": paired}}
        self._wa_connect_announced = False
        self._wa_connected = True
        self._unlink_decision_lock = threading.Lock()
        self._restart_grace_active = restart_grace_active
        self._probe = probe
        self.still_linked_probe_calls = 0
        self.error_sound = _Recorder()
        self.i18n = _I18n()
        self.app_name = "WinZapp"
        self.disconnect_calls = []
        self.set_connected_calls = []
        self._last_strike_ts = 0.0

    def _auto_restart_grace_active(self):
        return self._restart_grace_active

    def _set_wa_connected(self, connected, reason="", announce=True, confirmed=False):
        # The real one is the funnel for _auto_offline, _apply_offline_state(),
        # the tray text and the spoken offline announcement; here we only need
        # to see that it was reached, and with what.
        self.set_connected_calls.append((connected, reason, confirmed))
        self._wa_connected = bool(connected)

    def _still_linked_on_server(self):
        self.still_linked_probe_calls += 1
        return self._probe

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
    span = cs.STRIKE_MIN_INTERVAL_SECONDS * 2 * times if span is None else span
    step = span / max(times - 1, 1)
    for i in range(times):
        monkeypatch.setattr("main.time.time", lambda i=i: 10_000.0 + i * step)
        stub._handle_local_auth_rejected(401)


class TestGoingOfflineIsAnnouncedNotJustFlagged:
    """A 401 window used to write self._wa_connected = False directly and
    return. That flag is what the MessageQueue reads, so sending stopped --
    but _auto_offline stayed False, so the tray still said connected, the
    offline announcement was never spoken, and messages typed meanwhile sat
    in the queue looking sent. For a blind user that is the whole symptom:
    nothing said, nothing visibly wrong, nothing sent. It lasts at least the
    four strikes (~60s), ~6.5 min on a run that never connected, and longer
    behind a still-linked veto -- and it is the same shape as the project's
    open "stops sending out of nowhere" report, so it is not hypothetical.

    _set_wa_connected() is the single funnel for all of that, so this path
    has to go through it like its notLogged/QRCODE sibling does."""

    def test_it_goes_through_the_offline_funnel(self, monkeypatch):
        s = _Stub()
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(401)
        assert [c[0] for c in s.set_connected_calls] == [False]
        assert s._wa_connected is False

    def test_the_reason_names_the_http_status(self, monkeypatch):
        """log.log is the primary tool for reconstructing a lost session after
        the fact, and _set_wa_connected() logs this reason verbatim."""
        s = _Stub()
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(403)
        assert "403" in s.set_connected_calls[0][1]

    def test_it_is_not_a_confirmed_negative(self, monkeypatch):
        """`confirmed=True` skips the startup grace and goes straight to the
        offline UI. A local 401 never reached WhatsApp, which is this PR's
        whole thesis about what it proves -- so it must not claim that."""
        s = _Stub()
        monkeypatch.setattr("main.time.time", lambda: 10_000.0)
        s._handle_local_auth_rejected(401)
        assert s.set_connected_calls[0][2] is False

    def test_the_unpaired_shortcut_announces_too(self):
        """The early return for an unpaired install takes the same window,
        so it must not skip the funnel on its way to the pairing dialog."""
        s = _Stub(paired=False)
        s._handle_local_auth_rejected(401)
        assert [c[0] for c in s.set_connected_calls] == [False]


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
        s._still_linked_vetoes = 3
        s._handle_local_auth_rejected(401)
        assert s._logout_strikes == 0
        assert s._resume_fail_strikes == 0
        assert s._still_linked_vetoes == 0


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
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == []
        assert s.still_linked_probe_calls == 1

    def test_the_veto_resets_the_tally_instead_of_leaving_it_primed(self, monkeypatch):
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s._logout_strikes == 0
        assert s._resume_fail_strikes == 0

    def test_the_probe_only_runs_once_confirmed_not_on_every_reading(self, monkeypatch):
        s = _Stub()
        s._wa_connect_announced = True
        for _ in range(s._LOGOUT_CONFIRM_STRIKES - 1):
            s._handle_local_auth_rejected(401)
        assert s.still_linked_probe_calls == 0

    def test_the_probe_is_not_consulted_for_resume_failed(self, monkeypatch):
        """The still-linked veto only guards the destructive LOGOUT outcome
        -- RESUME_FAILED never wipes anything in the first place, so there
        is nothing for the extra probe to protect against."""
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = False
        _feed(s, s._RESUME_FAIL_STRIKES, monkeypatch)
        assert s.disconnect_calls == [False]
        assert s.still_linked_probe_calls == 0


class TestAnUnprovableProbeIsNeverDestructive:
    """The scenario the whole 401 path lands in: host-device leaves through
    the same local auth middleware that has been answering 401, so it is
    refused too and proves nothing either way.

    Read as a boolean ("could not prove it is still linked"), that used to be
    permission to wipe -- a Node restarted under a rotated local token gave
    401s, four strikes, LOGOUT, then a 401 from the probe as well, and the
    database went. Same destructive outcome as before the strike machinery
    existed, just 60s later. LINK_PROBE_UNKNOWN has to fall back to the
    pairing dialog instead, which keeps the history and still gives the user
    the way back."""

    def test_it_shows_pairing_without_wiping(self, monkeypatch):
        s = _Stub(probe=cs.LINK_PROBE_UNKNOWN)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == [False]

    def test_it_does_not_keep_re_deciding(self, monkeypatch):
        s = _Stub(probe=cs.LINK_PROBE_UNKNOWN)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        s._handle_local_auth_rejected(401)
        s._handle_local_auth_rejected(401)
        assert s.disconnect_calls == [False]

    def test_a_probe_that_answers_with_no_linked_phone_still_wipes(self, monkeypatch):
        """The one reading that genuinely authorises it: the session answered,
        and it holds no linked device."""
        s = _Stub(probe=cs.LINK_PROBE_UNLINKED)
        s._wa_connect_announced = True
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == [True]


class TestTheVetoIsBounded:
    """A veto that can repeat forever is its own failure mode: every veto
    resets the tally and returns, so a session answering host-device from a
    stale cache after a real unlink parks the app offline with no
    escalation -- _wa_connected False, nothing sending, no pairing dialog,
    and nothing in the log to tell it apart from a quiet outage."""

    def test_repeated_vetoes_eventually_fall_back_to_pairing_without_wiping(self, monkeypatch):
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = True
        # Each veto resets the tally, so a fresh run of strikes is needed to
        # reach the next one.
        for _ in range(s._STILL_LINKED_VETO_LIMIT):
            _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.still_linked_probe_calls == s._STILL_LINKED_VETO_LIMIT
        assert s.disconnect_calls == [False], "never a wipe — the probe may be right"

    def test_it_holds_out_for_the_whole_limit_first(self, monkeypatch):
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = True
        for _ in range(s._STILL_LINKED_VETO_LIMIT - 1):
            _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == []

    def test_an_automatic_session_restart_breaks_the_streak(self, monkeypatch):
        """Every reset of the strike tally has to clear the veto run with it,
        or "consecutive" stops meaning anything.

        The restart grace is the case that bit: enough vetoes accumulate that
        the dead-browser recovery fires _restart_wpp_session(), the grace
        clears the strikes, the session comes back and looks unlinked again —
        and the very first confirmed logout after it lands on veto 5, parking
        a session the probe says is linked on the pairing dialog, with the
        restart in the middle never counted as a break.

        Driven through the real reset (a grace-window reading), not by
        zeroing the counter by hand — the reset is the thing under test.
        """
        s = _Stub(probe=cs.LINK_PROBE_LINKED)
        s._wa_connect_announced = True
        for _ in range(s._STILL_LINKED_VETO_LIMIT - 1):
            _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == []

        s._restart_grace_active = True
        s._handle_local_auth_rejected(401)
        assert s._still_linked_vetoes == 0, "the grace must clear the veto run too"

        s._restart_grace_active = False
        _feed(s, s._LOGOUT_CONFIRM_STRIKES, monkeypatch)
        assert s.disconnect_calls == [], (
            "this is veto 1 of a new run, not the limit — the restart broke it"
        )
