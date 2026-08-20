"""Tests that drive the real _run_sync() retry loop, not a replica of it.

tests/test_chat_list_settled.py keeps a hand-written copy of this loop so the
settle *decisions* can be exercised as pure functions. That copy has drifted
from the real loop before — the whole suite stayed green over a branch it
covered nothing of — and by construction it can never cover the wiring: which
number is passed as evidence, whether the growth guard is consulted, whether
the deadline veto is called at all. Those live only in _run_sync().

So these bind _run_sync() itself to a stub and let it run, with every
collaborator past the chat-list fetch reduced to a no-op. What is asserted is
only what the loop decides: how many times it asked, whether the sync was
marked complete, and whether the session was recreated.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method is bound to a plain object — the same pattern the other main.py
tests use.
"""

import types

import pytest

import main
from main import MainWindow


class _Sound:
    def play(self):
        pass


class _I18n:
    def t(self, key, *a, **kw):
        return key


class _Stub:
    """Everything _run_sync() touches, reduced to the smallest thing that
    still lets the real loop run."""

    def __init__(self, counts, wa_web, local_chats, high_water=0):
        self._counts = list(counts)
        self._wa_web = wa_web
        self.chats = {
            f"55119{i:08d}@s.whatsapp.net": {"remoteJid": f"55119{i:08d}@s.whatsapp.net"}
            for i in range(local_chats)
        }
        self._chat_list_high_water = high_water
        self._broken_store_rounds = 0

        self._wa_connected = True
        self.offline_mode = False
        self.background_mode = True
        self._sync_completed = False
        self._sync_retry_count = 0
        self._initial_sync_running = True
        self.settings = {"storage": {"auto_download_media": False},
                         "user_interface": {}}
        self.i18n = _I18n()
        self.synchronizing_sound = _Sound()
        self.sync_complete_sound = _Sound()
        self.error_sound = _Sound()
        self._last_chat_fetch_count = 0
        self._last_chat_fetch_disconnected = False
        self._last_chat_fetch_error = None
        self._chats_awaiting_messages = set()
        self._lid_to_phone = {}
        self._history_still_landing = False

        # what the test inspects
        self.fetches = 0
        self.settle_fetches = 0
        self.full_saves_in_settle_loop = 0
        self.wa_web_probes = 0
        self.restarted = False
        self.message_sync_ran = 0

    # ── the two calls the loop actually makes ────────────────────────
    def get_remote_chats(self, chats, persist_full=True, notify_errors=True,
                         prune_stale=None):
        # prune_stale=True is what the settle loop passes and nothing else
        # does, which is how the two callers inside _run_sync() are told
        # apart — the loop, and the single refresh after the message phase.
        # Counting the loop's calls separately also pins the reason that
        # keyword exists: the loop must get the phantom sweep *without* the
        # full clear-and-reimport save, which it used to run once per attempt.
        if prune_stale:
            self.settle_fetches += 1
            if persist_full:
                self.full_saves_in_settle_loop += 1
        idx = min(self.fetches, len(self._counts) - 1)
        self.fetches += 1
        self._last_chat_fetch_count = self._counts[idx]
        return dict(chats)

    def _wa_web_chat_count(self):
        self.wa_web_probes += 1
        return self._wa_web

    def _restart_wpp_session(self):
        self.restarted = True

    def sync_remote_chats(self):
        self.message_sync_ran += 1

    # ── collaborators whose return value the loop uses ───────────────
    def normalize_chats(self, chats):
        return chats

    def deduplicate_chats(self, chats):
        return chats

    def refresh_history_still_landing(self, context=""):
        return False

    def sync_media_for_all_chats(self):
        return 0

    # ── everything else downstream: no-ops ───────────────────────────
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return lambda *a, **kw: None


def _make(counts, wa_web, local_chats=0, high_water=0):
    stub = _Stub(counts, wa_web, local_chats, high_water)
    for name in ("_run_sync", "_should_abort_sync_for_offline",
                 "_announce_sync_events_enabled", "count_contradicts_page",
                 "store_looks_broken", "_attempts_needed_to_confirm",
                 "_settle_deadline_decision", "history_page_target"):
        raw = MainWindow.__dict__[name]
        if isinstance(raw, (staticmethod, classmethod)):
            setattr(stub, name, getattr(MainWindow, name))
        else:
            setattr(stub, name, types.MethodType(raw, stub))
    for const in ("_CHAT_ABSOLUTE_MAX_ATTEMPTS", "_CHAT_ATTEMPT_EXTENSION",
                  "_STORE_PLAUSIBLE_RATIO", "_BROKEN_STORE_CONFIRM",
                  "_BROKEN_STORE_REPAIR_ROUNDS", "_DEEP_SYNC_TOP_N",
                  "_DEEP_SYNC_COUNT"):
        setattr(stub, const, getattr(MainWindow, const))
    return stub


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    """The loop sleeps 5 s between attempts and wx is not running here."""
    monkeypatch.setattr(main.time, "sleep", lambda *_a: None)
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **kw: None)
    monkeypatch.setattr(main.threading, "Thread",
                        lambda target=None, **kw: types.SimpleNamespace(
                            start=lambda: target and target(), is_alive=lambda: False))


class TestTheCapturedSessions:
    def test_the_resync_loop_stops_early_instead_of_extending_to_thirty(self):
        """Session one, round two: 931 cached, 935 seen in round one, the page
        still reporting 937, and list-chats answering 0 for ever. The old loop
        spent all 30 attempts here."""
        stub = _make([0] * 60, wa_web=937, local_chats=931, high_water=935)
        stub._run_sync()
        assert stub.restarted is False           # first round only backs off
        assert stub._broken_store_rounds == 1
        assert stub._sync_completed is False
        assert stub.settle_fetches <= MainWindow._BROKEN_STORE_CONFIRM + 1
        assert stub.full_saves_in_settle_loop == 0

    def test_the_second_such_round_recreates_the_session(self):
        stub = _make([0] * 60, wa_web=937, local_chats=931, high_water=935)
        stub._broken_store_rounds = MainWindow._BROKEN_STORE_REPAIR_ROUNDS - 1
        stub._run_sync()
        assert stub.restarted is True
        assert stub._sync_completed is False
        assert stub.message_sync_ran == 0, "ran the message phase into a dying session"

    def test_the_amputated_account_is_refused(self):
        """Session two: fresh install, no cache, 36 seen once, then 0. The old
        loop accepted it and marked the sync complete with 36 of 937."""
        stub = _make([0, 36] + [0] * 60, wa_web=937, local_chats=0)
        stub._run_sync()
        assert stub._sync_completed is False
        assert stub._broken_store_rounds == 1


class TestTheGrowthGuard:
    """A cold store filling in must never be called broken. evidence_count
    comes from the session high-water mark and the growth guard covers the
    ramp inside a round; remove either and this is the shape that breaks."""

    def test_a_cold_store_under_a_large_cache_still_settles(self):
        stub = _make([0, 100, 400, 900, 931, 931], wa_web=937, local_chats=931)
        stub._run_sync()
        assert stub.restarted is False
        assert stub._broken_store_rounds == 0
        assert stub._sync_completed is True
        assert stub.message_sync_ran == 1

    def test_the_documented_late_filling_store_still_settles(self):
        """The shape the code has a live capture of: nothing for five
        attempts, then the whole list."""
        stub = _make([0, 0, 0, 0, 0, 498, 498], wa_web=937, local_chats=931)
        stub._run_sync()
        assert stub.restarted is False
        assert stub._sync_completed is True

    def test_a_reconnection_with_a_warm_cache_settles_on_the_first_answer(self):
        stub = _make([931], wa_web=937, local_chats=931)
        stub._run_sync()
        assert stub.settle_fetches == 1
        assert stub._sync_completed is True


class TestTheDeadlineVeto:
    def test_zero_is_not_accepted_as_an_empty_account_when_the_page_disagrees(self):
        """No cache and nothing seen this session, so the early break cannot
        fire — the deadline would have accepted. Only the veto stops it."""
        stub = _make([0] * 60, wa_web=937, local_chats=0)
        stub._run_sync()
        assert stub._sync_completed is False
        assert stub._broken_store_rounds == 1

    def test_a_genuinely_empty_account_is_still_accepted(self):
        """Page and list-chats agree on zero."""
        stub = _make([0] * 60, wa_web=0, local_chats=0)
        stub._run_sync()
        assert stub._sync_completed is False  # no chats to sync
        assert stub._broken_store_rounds == 0
        assert stub.restarted is False

    def test_without_the_status_endpoint_nothing_new_fires(self):
        """Older client/api/ builds answer nothing; behaviour is unchanged."""
        stub = _make([0] * 60, wa_web=None, local_chats=931, high_water=935)
        stub._run_sync()
        assert stub.restarted is False
        assert stub._broken_store_rounds == 0
        assert stub.settle_fetches == MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS


class TestTheProbeIsNotChatty:
    def test_a_healthy_sync_never_asks_the_page_for_its_count(self):
        """The probe is only worth making when something already looks wrong;
        a normal sync must not pay for it."""
        stub = _make([931, 931], wa_web=937, local_chats=931)
        stub._run_sync()
        assert stub.wa_web_probes == 0
