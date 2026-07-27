"""Tests for retrying chats whose history WhatsApp Web had not loaded yet.

get-messages reads WhatsApp Web's *in-memory* store. Right after pairing that
store is still empty for most chats, so the call answers 200 with an empty list
— indistinguishable from a genuinely empty conversation. Measured on a real
539-chat account: 514 chats came back empty during the sync, and the sync never
ran again because _sync_completed gates it.

The consequences all compound: no local records means effective_unread_count()
clamps every badge to zero (it never claims more unread than records exist), and
a chat with no records, no lastMessage (list-chats returns `msgs: null`) and no
name is dropped from the conversation list entirely.

The same chats answered with 1 message ~40 minutes later and 15-16 shortly
after, so the store does fill in — it just needs to be asked again.
_note_backfill_state() decides who gets asked; that decision is tested here.
"""

import pytest

from main import MainWindow


note = MainWindow._note_backfill_state
claims = MainWindow._server_claims_content


class _Stub:
    def __init__(self):
        self._chats_awaiting_messages = set()

    _server_claims_content = staticmethod(MainWindow._server_claims_content)
    _note_backfill_state = MainWindow._note_backfill_state
    _jid_address_forms = MainWindow._jid_address_forms
    _resolve_backfill_target = MainWindow._resolve_backfill_target


def _chat(records=(), unread=0, t=0):
    c = {"unreadCount": unread, "t": t}
    if records:
        c["messages"] = {"messages": {"records": list(records)}}
    return c


class TestServerClaimsContent:
    def test_unread_count_counts(self):
        assert claims({"unreadCount": 3}) is True

    def test_last_activity_timestamp_counts(self):
        assert claims({"t": 1785147636}) is True

    def test_a_truly_blank_chat_does_not(self):
        assert claims({"unreadCount": 0, "t": 0}) is False

    @pytest.mark.parametrize("chat", [
        {}, {"unreadCount": None, "t": None}, {"unreadCount": "x", "t": "y"},
    ])
    def test_survives_missing_or_junk_values(self, chat):
        assert claims(chat) is False


class TestBackfillBookkeeping:
    def test_marks_a_chat_the_server_says_has_history(self):
        """The 514-chat case: API answered fine, gave nothing, but the chat
        record itself carries unread/activity."""
        s = _Stub()
        s._note_backfill_state("a@lid", _chat(unread=2, t=1785147636), api_ok=True)
        assert s._chats_awaiting_messages == {"a@lid"}

    def test_does_not_mark_a_genuinely_empty_chat(self):
        s = _Stub()
        s._note_backfill_state("a@lid", _chat(), api_ok=True)
        assert s._chats_awaiting_messages == set()

    def test_does_not_mark_when_the_api_never_answered(self):
        """A failed call is the retry loop's business — retrying it here would
        hammer an API that is down."""
        s = _Stub()
        s._note_backfill_state("a@lid", _chat(unread=2), api_ok=False)
        assert s._chats_awaiting_messages == set()

    def test_clears_the_mark_once_history_arrives(self):
        s = _Stub()
        s._note_backfill_state("a@lid", _chat(unread=2, t=1), api_ok=True)
        assert "a@lid" in s._chats_awaiting_messages
        s._note_backfill_state("a@lid", _chat(records=[{"key": {"id": "X"}}], unread=2, t=1), api_ok=True)
        assert s._chats_awaiting_messages == set()

    def test_a_failed_retry_does_not_resurrect_a_recovered_chat(self):
        """Once a chat has history it must leave the pending set and stay out,
        even if a later call fails."""
        s = _Stub()
        s._chats_awaiting_messages = set()
        s._note_backfill_state("a@lid", _chat(records=[{"key": {"id": "X"}}], t=1), api_ok=True)
        s._note_backfill_state("a@lid", _chat(records=[{"key": {"id": "X"}}], t=1), api_ok=False)
        assert s._chats_awaiting_messages == set()

    def test_the_set_is_created_on_first_use(self):
        """sync_chat_messages() runs on worker threads before any explicit
        initialisation, so the first caller must not crash."""
        class _Bare:
            _server_claims_content = staticmethod(MainWindow._server_claims_content)
            _note_backfill_state = MainWindow._note_backfill_state
        b = _Bare()
        b._note_backfill_state("a@lid", _chat(unread=1), api_ok=True)
        assert b._chats_awaiting_messages == {"a@lid"}

    def test_tracks_many_chats_independently(self):
        s = _Stub()
        for i in range(514):
            s._note_backfill_state(f"c{i}@lid", _chat(t=1785147636), api_ok=True)
        assert len(s._chats_awaiting_messages) == 514
        # Half of them recover on the next pass.
        for i in range(0, 514, 2):
            s._note_backfill_state(f"c{i}@lid", _chat(records=[{"key": {"id": i}}], t=1), api_ok=True)
        assert len(s._chats_awaiting_messages) == 257


class TestJidBridge:
    """sync_remote_chats() records pending JIDs, and deduplicate_chats() then
    re-keys self.chats from @lid to phone JIDs. Looking a pending JID up
    verbatim afterwards misses.

    Measured live: pass 11 reported "retrying 7 of 267" — only 7 of 267 pending
    JIDs still existed under the name they were recorded under. The 260 that did
    not were every individual chat; only groups, which dedup never renames, were
    ever retried. That is why a real account sat frozen at 399 visible
    conversations while every pass reported progress.
    """

    def _stub(self):
        s = _Stub()
        s.chats = {}
        s._lid_to_phone = {"111@lid": "5511999999999@s.whatsapp.net"}
        s._phone_to_lid = {"5511999999999@s.whatsapp.net": "111@lid"}
        return s

    def test_finds_a_chat_that_was_rekeyed_to_its_phone_jid(self):
        s = self._stub()
        s.chats["5511999999999@s.whatsapp.net"] = {"remoteJid": "5511999999999@s.whatsapp.net"}
        key, chat = s._resolve_backfill_target("111@lid")
        assert key == "5511999999999@s.whatsapp.net"
        assert chat is not None

    def test_finds_a_chat_still_under_its_lid(self):
        s = self._stub()
        s.chats["111@lid"] = {"remoteJid": "111@lid"}
        key, _ = s._resolve_backfill_target("111@lid")
        assert key == "111@lid"

    def test_resolves_in_the_other_direction_too(self):
        s = self._stub()
        s.chats["111@lid"] = {"remoteJid": "111@lid"}
        key, _ = s._resolve_backfill_target("5511999999999@s.whatsapp.net")
        assert key == "111@lid"

    def test_reports_a_chat_that_is_really_gone(self):
        s = self._stub()
        key, chat = s._resolve_backfill_target("999@lid")
        assert (key, chat) == (None, None)

    def test_groups_resolve_unchanged(self):
        s = self._stub()
        s.chats["120363@g.us"] = {"remoteJid": "120363@g.us"}
        key, _ = s._resolve_backfill_target("120363@g.us")
        assert key == "120363@g.us"

    def test_recovery_clears_both_address_forms(self):
        """Marked under its @lid, re-synced under its phone JID — the @lid entry
        must not linger and be retried forever."""
        s = self._stub()
        s._chats_awaiting_messages = {"111@lid"}
        s._note_backfill_state(
            "5511999999999@s.whatsapp.net",
            _chat(records=[{"key": {"id": "X"}}], t=1), api_ok=True)
        assert s._chats_awaiting_messages == set()


class TestSweepCoverage:
    """The window advances by remembering what was tried, not by an index.

    `pending` shrinks as chats recover, so index arithmetic over it skipped
    entries outright — some chats were never retried at all.
    """

    @staticmethod
    def _sweep(pending, chunk, recover_per_pass):
        """Run the sweep rule, removing `recover_per_pass` chats each pass."""
        pending = list(pending)
        attempted, tried_ever, passes = set(), set(), 0
        while pending and passes < 200:
            untried = [j for j in pending if j not in attempted]
            if not untried:
                attempted.clear()
                untried = list(pending)
            window = untried[:chunk]
            attempted.update(window)
            tried_ever.update(window)
            for j in window[:recover_per_pass]:
                pending.remove(j)
            passes += 1
        return tried_ever, passes

    def test_every_chat_gets_tried_even_as_the_set_shrinks(self):
        original = [f"c{i}@lid" for i in range(463)]
        tried, _ = self._sweep(original, chunk=60, recover_per_pass=17)
        assert tried == set(original), "no chat may be skipped by the sweep"

    def test_it_terminates_when_nothing_ever_recovers(self):
        original = [f"c{i}@lid" for i in range(120)]
        tried, passes = self._sweep(original, chunk=60, recover_per_pass=0)
        assert tried == set(original)
        assert passes == 200, "loop is bounded by the caller's budget, not by progress"


class TestBackfillPacing:
    """The loop is adaptive: quick retries while passes recover chats, backing
    off when one recovers nothing, and a hard overall budget.

    A fixed schedule was tried first and abandoned one real account's remaining
    260 chats while their history was still arriving — one pass had just
    recovered 203 of 463.
    """

    def test_constants_are_sane(self):
        assert MainWindow._BACKFILL_FIRST_DELAY <= 60, "first retry must be soon"
        assert MainWindow._BACKFILL_MAX_DELAY >= MainWindow._BACKFILL_FIRST_DELAY
        assert MainWindow._BACKFILL_BUDGET >= 15 * 60, "must outlast a slow warm-up"
        assert MainWindow._BACKFILL_BUDGET <= 2 * 60 * 60, "must not poll forever"

    @staticmethod
    def _next_delay(delay, recovered):
        """The pacing rule the loop applies after each pass."""
        if recovered > 0:
            return MainWindow._BACKFILL_FIRST_DELAY
        return min(delay * 2, MainWindow._BACKFILL_MAX_DELAY)

    def test_progress_keeps_retries_fast(self):
        d = self._next_delay(240, recovered=203)
        assert d == MainWindow._BACKFILL_FIRST_DELAY

    def test_no_progress_backs_off(self):
        first = MainWindow._BACKFILL_FIRST_DELAY
        assert self._next_delay(first, 0) == first * 2

    def test_backoff_is_capped(self):
        d = MainWindow._BACKFILL_FIRST_DELAY
        for _ in range(20):
            d = self._next_delay(d, 0)
        assert d == MainWindow._BACKFILL_MAX_DELAY

    def test_each_pass_is_a_bounded_chunk(self):
        """An unchunked pass fired 463 get-messages calls in ~6 s through the
        single Puppeteer page, on top of the media phase. This is background
        history nobody is waiting on — it must not burst."""
        assert MainWindow._BACKFILL_CHUNK <= 100
        assert MainWindow._BACKFILL_WORKERS <= 6, "must not exceed the sync's own cap"

    def test_the_window_rotates_so_every_chat_gets_tried(self):
        """`pending` is sorted, so slicing from the front every pass would retry
        the same chats forever and never reach the rest."""
        pending = [f"c{i}@lid" for i in range(463)]
        chunk = MainWindow._BACKFILL_CHUNK
        cursor, seen, passes = 0, set(), 0
        while len(seen) < len(pending) and passes < 100:
            cursor %= len(pending)
            ordered = pending[cursor:] + pending[:cursor]
            cursor += chunk
            seen.update(ordered[:chunk])
            passes += 1
        assert seen == set(pending), "rotation must cover every pending chat"
        assert passes == -(-len(pending) // chunk), "and cover it without wasted passes"

    def test_a_stuck_account_cannot_burn_the_budget_in_a_few_passes(self):
        """Backing off means an account that never warms up costs few passes."""
        d, spent, passes = MainWindow._BACKFILL_FIRST_DELAY, 0, 0
        while spent < MainWindow._BACKFILL_BUDGET:
            spent += d
            passes += 1
            d = self._next_delay(d, 0)
        assert passes <= 15, f"{passes} passes for a store that never warms up"
