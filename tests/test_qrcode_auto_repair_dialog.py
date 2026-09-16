"""Tests for on_qrcode_update()'s proactive pairing-dialog trigger.

Reported live: after an automatic session recovery attempt found the stored
token already invalid, WPPConnect correctly started generating a fresh QR
code (on_qrcode_update fired repeatedly with real image bytes) — but nothing
in the app surfaced it. The user was left staring at "offline" with no
explanation for however long _AUTO_RESTART_LOGOUT_GRACE_SECONDS or the
multi-minute confirmed-logout detection (several minutes either way) took
before finally showing a dialog.

A real QR/pairing-code event with no pairing dialog already open is a
fairly reliable "you need to re-pair" signal — WPPConnect only ever
generates one once it has decided the stored session can't be restored —
so on_qrcode_update() opens the pairing dialog once that is confirmed by
a second such reading (TestStartupGraceWindow and
TestProactivePairingDialog below cover why one alone is not enough),
decoupled entirely from the slower, destructive confirmed-logout path
(_on_disconnect(), which wipes local data, is never called from here).

WebSocketClient is exercised as a plain function bound onto a small stub
(no real socketio/wx.App needed) — same approach as tests/test_qrcode_event.py
uses for _extract_qr_payload.
"""

import time

import pytest

from core.websocket_client import WebSocketClient, qr_within_startup_grace
from main import MainWindow


class _FakeI18n:
    def t(self, key):
        return key


class _FakeSound:
    def __init__(self):
        self.plays = 0

    def play(self):
        self.plays += 1


class _FakeSpeakOutput:
    def output(self, text):
        pass


class _FakeConnect:
    def __init__(self, main_window=None):
        self.connection_mode = "phone"
        self.main_window = main_window
        self.show_connection_dial_calls = 0

    def show_connection_dial(self):
        self.show_connection_dial_calls += 1
        # Mirrors the real Connect.show_connection_dial(), which drops both
        # unattended-QR guards right before its modal loop. A fake that skips
        # this makes the flood limit look one event closer than production
        # ever reaches it — see tests/test_qrcode_unattended_session.py.
        self.main_window._reset_unattended_qr_guards()

    def display_qrcode_image(self, base64_img):
        pass


class _FakeMainWindow:
    def __init__(self, paired=True, pairing_dialog_active=False,
                 wa_connect_announced=True, wa_startup_time=None):
        self.settings = {"privateinfo": {"paired": paired}}
        self._pairing_dialog_active = pairing_dialog_active
        self.pairing_code_updated_sound = _FakeSound()
        self.error_sound = _FakeSound()
        self.speak_output = _FakeSpeakOutput()
        self.app_name = "WinZapp"
        self.restore_window_calls = 0
        self._unattended_qr_events = 0
        self._qr_flood_halted = False
        self._pairing_in_progress = False
        self.halt_calls = 0
        # Whether a snapshot exists to put back. False keeps every test
        # written before the profile-repair step behaving exactly as it did:
        # nothing to restore, so the pairing dialog is the outcome.
        self.profile_restore_available = False
        self.recover_calls = []
        # Every on_give_up handed over, kept so a test can fire one the way
        # the restore thread does — see fail_restore().
        self.give_up_callbacks = []
        # Defaults put every pre-existing test well past the startup grace
        # window (already connected once before, or started long ago) —
        # only the dedicated grace-window tests below override these.
        self._wa_connect_announced = wa_connect_announced
        self._WA_STARTUP_GRACE_SECONDS = MainWindow._WA_STARTUP_GRACE_SECONDS
        self._wa_startup_time = (
            time.time() - (self._WA_STARTUP_GRACE_SECONDS * 10)
            if wa_startup_time is None else wa_startup_time
        )
        # Modelling the restore's own two effects separately, because they
        # land at very different moments — see finish_restore() below.
        self._recovery_spent = False
        self.restore_starts = 0
        # Set before the restore thread starts and cleared in its finally, on
        # both outcomes — exactly where the real _recover_suspect_profile()
        # sets and clears it. finish_restore()/fail_restore() are that finally.
        self._profile_restore_in_flight = False

    def _profile_restore_worth_trying(self):
        # The real one asks pick_restore_generation() without spending
        # anything; here "restorable" is simply profile_restore_available.
        return (self.profile_restore_available
                and not self._recovery_spent
                and not self._profile_restore_in_flight)

    def _recover_suspect_profile(self, reason=None, on_give_up=None):
        # Every call is recorded, including the ones the latch refuses: the
        # caller (_handle_unattended_qr) does not guard against a later QR
        # refresh calling this again, so what it does with the NEXT code is
        # exactly what these tests are about.
        self.recover_calls.append(reason)
        self.give_up_callbacks.append(on_give_up)
        # Mirrors the real contract: on_give_up fires only when a restore was
        # started and then failed. A False return means nothing was started,
        # and the caller handles it inline — see _recover_suspect_profile().
        if not self.profile_restore_available or self._recovery_spent:
            return False
        # The latch is what the real one does synchronously: it is set before
        # the restore thread is even started, so a second call is refused
        # whether or not that thread has finished.
        self._recovery_spent = True
        self._profile_restore_in_flight = True
        self.restore_starts += 1
        return True

    def finish_restore(self):
        """The restore thread reaching `self._unattended_qr_events = 0`.

        Kept separate from _recover_suspect_profile() on purpose. In
        production that line runs on a background thread, after close-session
        (10 s timeout), wait_for_profile_release (20 s) and a copy of a few
        hundred MB — while codes keep arriving every ~20-30 s. Zeroing the
        counter inline here would model a race production does not reliably
        win, and every test resting on it would be asserting a guarantee the
        app does not have. So the tests say when it lands, and both orderings
        are covered. The production line this stands in for has its own test,
        against the real MainWindow method that runs it:
        tests/test_profile_recovery_wiring.py::
        TestASuccessfulRestoreGivesBackTheQrFloodAllowance.
        """
        self._unattended_qr_events = 0
        self._profile_restore_in_flight = False   # the thread's finally

    def fail_restore(self):
        """The restore thread's give-up path, in the order production runs it.

        _recover_suspect_profile() queues wx.CallAfter(
        self._announce_profile_beyond_repair) — whose *first* statement is
        error_sound.play() — and immediately behind it wx.CallAfter(
        on_give_up), which passes no arguments at all. Both land on the wx
        main thread milliseconds apart, so what the callback does with the
        sound is the whole question here.
        """
        # The finally has already run by the time either queued call does: it
        # is on the restore thread, they are on the wx main thread behind it.
        self._profile_restore_in_flight = False
        self.error_sound.play()           # _announce_profile_beyond_repair()
        self.give_up_callbacks[-1]()      # wx.CallAfter(on_give_up): no args

    def _is_pairing_dialog_active(self):
        return self._pairing_dialog_active

    def restore_window(self):
        self.restore_window_calls += 1

    # The real method, so this fake cannot drift from what production does
    # when the pairing dialog goes up.
    _reset_unattended_qr_guards = MainWindow._reset_unattended_qr_guards

    def _halt_unattended_qr_session(self):
        self.halt_calls += 1
        self._qr_flood_halted = True


class _Stub:
    on_qrcode_update = WebSocketClient.on_qrcode_update
    _pairing_attended = WebSocketClient._pairing_attended
    _handle_unattended_qr = WebSocketClient._handle_unattended_qr
    _qr_within_startup_grace = WebSocketClient._qr_within_startup_grace
    _show_repair_dialog = WebSocketClient._show_repair_dialog
    _repair_gave_up = WebSocketClient._repair_gave_up
    _UNATTENDED_QR_LIMIT = WebSocketClient._UNATTENDED_QR_LIMIT
    _REPAIR_DIALOG_CONFIRM_EVENTS = WebSocketClient._REPAIR_DIALOG_CONFIRM_EVENTS
    _extract_qr_payload = staticmethod(WebSocketClient._extract_qr_payload)

    def __init__(self, main_window, connect):
        self.main_window = main_window
        self.connect = connect
        self.i18n = _FakeI18n()


QR_EVENT = {"data": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg"}


@pytest.fixture(autouse=True)
def _synchronous_call_after(monkeypatch):
    monkeypatch.setattr("core.websocket_client.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr("core.websocket_client.wx.MessageBox", lambda *a, **kw: None)


class TestProactivePairingDialog:
    def test_does_not_open_on_a_single_event(self):
        """Regression: a real log showed one QR event, seconds apart from
        _act_on_unlink_decision() (main.py) independently logging "resuming
        — data preserved" for the very same underlying reading — the two
        mechanisms disagreed because this one used to act on one reading
        while the other, more careful one required several. A single event
        must not be enough on its own any more."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 0

    def test_opens_the_dialog_once_confirmed_by_a_second_event(self):
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 1

    def test_restores_the_window_and_gives_the_classic_logout_cue_first(self):
        """Regression: the first version of this feature jumped straight to
        show_connection_dial() with no sound/MessageBox at all — silent and
        easy to miss entirely if the window was minimized to the tray at the
        time, reported live as exactly that."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert mw.restore_window_calls == 1

    def test_does_not_open_a_second_dialog_on_a_qr_refresh(self):
        """QR codes rotate every ~20-30s while waiting — must not stack
        nested dialogs on every refresh."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 1
        # And the refreshes behind the open dialog are not a flood: opening it
        # resets the counter, so three events never reach the halt. Asserted
        # here because this is exactly where a fake that skipped the reset
        # would diverge from production while still passing the line above.
        assert mw.halt_calls == 0

    def test_does_nothing_when_a_pairing_dialog_is_already_open(self):
        """The dialog is already up (e.g. user-initiated, or already shown
        proactively) — this is the existing display_qrcode_image()/pairing
        code field update path instead."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=True)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 0

    def test_does_nothing_when_never_paired(self):
        """An account that was never paired goes through the normal
        first-run pairing flow already — this path is only for "was paired,
        suddenly needs a fresh QR"."""
        mw = _FakeMainWindow(paired=False, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 0

    def test_reconnecting_afterwards_allows_a_future_trigger(self):
        """_auto_repair_dialog_shown is reset by _set_wa_connected(True, ...)
        once the connection genuinely recovers — simulated here directly."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)
        assert connect.show_connection_dial_calls == 1

        mw._auto_repair_dialog_shown = False  # what a real reconnect does
        # _unattended_qr_events is already back at 0: show_connection_dial()
        # (the fake mirrors the real one) calls _reset_unattended_qr_guards()
        # the moment the first dialog opens above.
        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)
        assert connect.show_connection_dial_calls == 2


class TestTheProfileIsRepairedBeforeAskingTheUserToPair:
    """A code minted for a *paired* install means the stored session could not
    be restored — which is exactly the condition the profile recovery exists
    for, and this is the earliest and cleanest evidence of it available.

    Measured on a real install on 2026-09-08. A clean Ctrl+Shift+Q shutdown
    (close-session acknowledged, session observed CLOSED, Chrome confirmed to
    have released the profile), and the next launch logged itself out seven
    seconds into the page load. ProfileHealthTracker counted
    INITIALIZING/CLOSED cycles at ~60 s each and stood at 2 of 3 when the code
    arrived at t+2.4 min — and opening the pairing dialog then froze it there
    for good, because check_wa_connection_http() returns immediately while a
    pairing dialog is up, so the poll that feeds the tracker never ran again.
    The snapshot was restorable by hand the whole time; the app could never
    reach it.
    """

    def test_a_restorable_profile_is_repaired_on_the_very_first_code(self):
        """Recover early, confirm late (issue #203): the repair does not wait
        for _REPAIR_DIALOG_CONFIRM_EVENTS — only the dialog does."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)

        assert mw.restore_starts == 1
        assert connect.show_connection_dial_calls == 0

    def test_the_reason_says_what_was_observed(self):
        # It lands in shutdown_audit.log, which survives the launch — the one
        # place the next diagnosis can read why a restore was attempted.
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = True
        s = _Stub(mw, _FakeConnect(mw))

        s.on_qrcode_update(QR_EVENT)

        assert "pairing code" in (mw.recover_calls[0] or "")

    def test_with_nothing_to_restore_the_user_is_still_sent_to_pair(self):
        """And the recovery is only called once the reading is confirmed: with
        nothing restorable it answers with the "profile corrupted" sound,
        speech and modal, which the gates exist to keep off a single reading."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = False
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        assert mw.recover_calls == []

        s.on_qrcode_update(QR_EVENT)

        assert len(mw.recover_calls) == 1
        assert connect.show_connection_dial_calls == 1

    def test_an_install_that_never_paired_is_not_a_broken_profile(self):
        # Nothing to restore and nothing lost: this is an ordinary first
        # pairing, and the recovery must not run at all — not even with a
        # snapshot lying around.
        mw = _FakeMainWindow(paired=False, pairing_dialog_active=False)
        mw.profile_restore_available = True
        s = _Stub(mw, _FakeConnect(mw))

        s.on_qrcode_update(QR_EVENT)

        assert mw.recover_calls == []

    def test_a_failed_restore_on_a_confirmed_reading_sends_the_user_to_pair_without_a_second_sound(self):
        """The give-up route is a caller of _show_repair_dialog(), and nothing
        used to bind its play_sound.

        wx.CallAfter(on_give_up) invokes it with no arguments, and it is queued
        directly behind wx.CallAfter(self._announce_profile_beyond_repair),
        whose first statement is error_sound.play() and whose MessageBox then
        pumps the queue this callback is sitting in. Two plays on one stream
        milliseconds apart are heard as a single truncated blip rather than as
        two cues, the same defect the post-halt route is written around (see
        tests/test_qrcode_unattended_session.py, which pins that one).

        Reached when the restore was started on a confirmed reading: here the
        snapshot only became worth trying after the first code, so the second
        one — outside the grace, confirmed — is what starts it."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)          # nothing restorable yet
        mw.profile_restore_available = True
        s.on_qrcode_update(QR_EVENT)          # confirmed: this one starts it
        assert mw.restore_starts == 1
        assert mw.error_sound.plays == 0      # nothing has been played yet

        mw.fail_restore()

        # The user is still sent to pair by hand — the repair is what failed,
        # not the reading that prompted it.
        assert connect.show_connection_dial_calls == 1
        assert mw.restore_window_calls == 1
        assert mw.error_sound.plays == 1, (
            "the give-up route played the error sound again on top of "
            "_announce_profile_beyond_repair()'s own")

    def test_a_failed_restore_on_an_unconfirmed_reading_does_not_open_the_dialog(self):
        """Issue #203 moved the restore in front of the gates, so its give-up
        has to ask them again: otherwise one unconfirmed code, seconds into a
        boot, ends in the device_logged_out MessageBox and a pairing dialog
        whose Cancel quits the app. Nothing is lost by waiting — the failed
        restore put the refused profile back, and its next code confirms."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)          # starts the restore
        mw.fail_restore()
        assert connect.show_connection_dial_calls == 0

        s.on_qrcode_update(QR_EVENT)          # the refused profile, restarted

        assert connect.show_connection_dial_calls == 1
        assert mw.restore_starts == 1
        assert mw.halt_calls == 0

    def test_a_qr_refresh_after_the_restore_finished_does_not_retry_it(self):
        # _recover_suspect_profile() latches, so a code minted by the restored
        # profile does not start a second restore; and the restore's own
        # counter reset means it is only the first of a fresh run, which
        # _REPAIR_DIALOG_CONFIRM_EVENTS does not accept on its own.
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)          # this one starts the restore
        assert mw.restore_starts == 1
        mw.finish_restore()

        s.on_qrcode_update(QR_EVENT)

        assert mw.restore_starts == 1
        assert connect.show_connection_dial_calls == 0
        assert mw.halt_calls == 0

    def test_codes_while_the_restore_still_runs_are_neither_counted_nor_acted_on(self):
        """The ordering production usually gets: the restore thread is still
        inside close-session / wait_for_profile_release / the copy when the
        next codes arrive.

        This used to open the pairing dialog on top of the restore — pinned
        then as a known gap, since pairing from it starts a session over the
        directory restore_snapshot() may still be writing. Neither that nor
        the halt belongs here: the restore has already closed the session and
        blocks the health poll's /start-session for the whole flight, and the
        halt's latch would keep the restored profile from ever starting."""
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False)
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)          # starts the restore
        for _ in range(WebSocketClient._UNATTENDED_QR_LIMIT * 2):
            s.on_qrcode_update(QR_EVENT)      # the thread has not landed

        assert mw.restore_starts == 1
        assert connect.show_connection_dial_calls == 0
        assert mw.halt_calls == 0
        assert mw._unattended_qr_events == 1, (
            "codes during the flight were counted; a counted-but-skipped "
            "event is how the halt stops being evaluated")

    @pytest.mark.parametrize("inside_grace", [False, True],
                             ids=["outside-grace", "inside-grace"])
    @pytest.mark.parametrize("outcome", ["succeeds", "fails"])
    def test_after_the_restore_the_flood_keeps_its_ceiling_and_no_more(
            self, outcome, inside_grace):
        """What issue #203 asked to be measured and written down: the cost in
        codes requested from WhatsApp, since an unattended code stream has
        already cost an account.

        Worst case for the restored profile: it is refused too, so codes keep
        coming after the restore. One code starts the restore; the flight's
        stragglers are not counted; and from there the flood is bounded by the
        same two ceilings as a flood with nothing to restore — the dialog on
        the _REPAIR_DIALOG_CONFIRM_EVENTS'th counted code outside the grace,
        the halt on the _UNATTENDED_QR_LIMIT'th inside it. A successful restore
        zeroes the count, a failed one keeps the code that started it, and
        neither can start a second restore."""
        mw = _FakeMainWindow(
            paired=True, pairing_dialog_active=False,
            wa_connect_announced=not inside_grace,
            wa_startup_time=time.time() if inside_grace else None,
        )
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)          # code 1 starts the restore
        s.on_qrcode_update(QR_EVENT)          # a straggler during the flight
        if outcome == "succeeds":
            mw.finish_restore()
        else:
            mw.fail_restore()

        codes_after = 0
        while connect.show_connection_dial_calls == 0 and mw.halt_calls == 0:
            codes_after += 1
            assert codes_after <= WebSocketClient._UNATTENDED_QR_LIMIT, (
                "the flood ran past its ceiling after the restore")
            s.on_qrcode_update(QR_EVENT)

        already = 0 if outcome == "succeeds" else 1
        if inside_grace:
            assert mw.halt_calls == 1
            assert codes_after == WebSocketClient._UNATTENDED_QR_LIMIT - already
        else:
            assert mw.halt_calls == 0
            assert codes_after == WebSocketClient._REPAIR_DIALOG_CONFIRM_EVENTS - already
        assert mw.restore_starts == 1


class TestIssue203AFloodInsideTheGraceIsRepaired:
    """The report itself: a flood confined to _WA_STARTUP_GRACE_SECONDS (a
    fresh boot on a profile WhatsApp has just refused) ran out
    _UNATTENDED_QR_LIMIT and reached the halt with a good snapshot on disk that
    nothing had looked at — and the halt's latch then kept even a restore made
    afterwards from being started."""

    def _in_grace(self):
        mw = _FakeMainWindow(paired=True, pairing_dialog_active=False,
                             wa_connect_announced=False, wa_startup_time=time.time())
        mw.profile_restore_available = True
        connect = _FakeConnect(mw)
        return mw, connect, _Stub(mw, connect)

    def test_the_restore_starts_before_the_halt(self):
        mw, connect, s = self._in_grace()

        for _ in range(WebSocketClient._UNATTENDED_QR_LIMIT):
            s.on_qrcode_update(QR_EVENT)

        assert mw.restore_starts == 1
        assert mw.halt_calls == 0
        assert mw._qr_flood_halted is False
        assert connect.show_connection_dial_calls == 0

    def test_without_a_snapshot_the_grace_still_withholds_everything_but_the_halt(self):
        """No early modal: the recovery is not even called until something
        confirms, and inside the grace that is the halt."""
        mw, connect, s = self._in_grace()
        mw.profile_restore_available = False

        for _ in range(WebSocketClient._UNATTENDED_QR_LIMIT - 1):
            s.on_qrcode_update(QR_EVENT)
        assert mw.recover_calls == []
        assert connect.show_connection_dial_calls == 0

        s.on_qrcode_update(QR_EVENT)
        assert mw.halt_calls == 1

    def test_a_restore_that_began_on_the_limits_own_code_cannot_lose_the_halt(self):
        """The #202 shape, reached by a new route. An event that returns above
        the halt used to withhold it for the rest of the flood, because the
        test was `seen == limit` and `seen` only grows. Here the restore starts
        on exactly that code and then fails on an unconfirmed reading, so
        nothing resets the count: the next code must still halt."""
        mw, connect, s = self._in_grace()
        mw._unattended_qr_events = WebSocketClient._UNATTENDED_QR_LIMIT - 1

        s.on_qrcode_update(QR_EVENT)          # seen == limit, starts the restore
        assert mw.restore_starts == 1
        assert mw.halt_calls == 0
        mw.fail_restore()                     # inside the grace: no dialog
        assert connect.show_connection_dial_calls == 0

        s.on_qrcode_update(QR_EVENT)          # seen == limit + 1

        assert mw.halt_calls == 1

class TestStartupGraceWindow:
    """Regression: a real log showed on_qrcode_update firing 11s after
    process start, while /list-chats was still 404ing for another 50s
    because the session itself had not finished starting — WPPConnect's
    first QR event is not immune to the exact slow-boot race
    _WA_STARTUP_GRACE_SECONDS exists for elsewhere. A single such event
    used to open the proactive re-pair dialog immediately; the user then
    followed it into a fresh pairing, which wiped their local history."""

    def test_does_not_open_inside_the_startup_grace_window_even_with_two_events(self):
        mw = _FakeMainWindow(
            paired=True, pairing_dialog_active=False,
            wa_connect_announced=False, wa_startup_time=time.time(),
        )
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 0

    def test_opens_once_the_grace_window_has_elapsed_and_a_second_event_confirms(self):
        mw = _FakeMainWindow(
            paired=True, pairing_dialog_active=False,
            wa_connect_announced=False,
            wa_startup_time=time.time() - (MainWindow._WA_STARTUP_GRACE_SECONDS + 1),
        )
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 1

    def test_a_lone_event_past_the_grace_window_still_is_not_enough(self):
        """The grace window and _REPAIR_DIALOG_CONFIRM_EVENTS are two
        independent requirements — clearing one must not silently satisfy
        the other."""
        mw = _FakeMainWindow(
            paired=True, pairing_dialog_active=False,
            wa_connect_announced=False,
            wa_startup_time=time.time() - (MainWindow._WA_STARTUP_GRACE_SECONDS + 1),
        )
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 0

    def test_opens_once_confirmed_by_a_second_event_once_a_connection_was_ever_confirmed(self):
        """The grace window only protects a (re)connect attempt that has
        never yet succeeded — once _wa_connect_announced is True, a QR event
        is exactly as conclusive as before, even seconds after it fires. The
        _REPAIR_DIALOG_CONFIRM_EVENTS requirement still applies regardless."""
        mw = _FakeMainWindow(
            paired=True, pairing_dialog_active=False,
            wa_connect_announced=True, wa_startup_time=time.time(),
        )
        connect = _FakeConnect(mw)
        s = _Stub(mw, connect)

        s.on_qrcode_update(QR_EVENT)
        s.on_qrcode_update(QR_EVENT)

        assert connect.show_connection_dial_calls == 1


class TestQrWithinStartupGraceIsPureLogic:
    """The window itself, with no MainWindow and no socket in the way —
    _qr_within_startup_grace() is the four-value reader in front of it."""

    def test_a_confirmed_connection_ends_the_window_whatever_the_clock_says(self):
        assert qr_within_startup_grace(True, 1000.0, 60.0, 1000.0) is False

    def test_inside_the_window_when_no_connection_was_ever_confirmed(self):
        assert qr_within_startup_grace(False, 1000.0, 60.0, 1030.0) is True

    def test_outside_the_window_once_the_grace_has_elapsed(self):
        assert qr_within_startup_grace(False, 1000.0, 60.0, 1061.0) is False

    def test_a_missing_startup_time_or_grace_never_opens_the_window(self):
        # getattr(..., 0) or 0 is what the caller passes when MainWindow has
        # not written either attribute yet; that must read as "not in a grace
        # window", never as an open-ended one.
        assert qr_within_startup_grace(False, 0, 0, 1000.0) is False
