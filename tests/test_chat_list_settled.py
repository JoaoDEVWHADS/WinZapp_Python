"""Tests for the list-chats "has the server's chat store settled?" decision.

_run_sync() only accepts a chat-list snapshot once the server has answered with
the same non-zero count twice in a row (or once it already covers the local
cache). That rule fixed a real failure — WhatsApp Web fills its chat store
progressively, so an early "4 chats" answer for a several-hundred-chat account
used to be accepted and left the user permanently synced to four conversations.

The rule was unsatisfiable in the commonest startup shape, though: a cold store
answers 0 chats over and over and only fills in on the very last attempt
(observed live: attempts 1-5 → 0, attempt 6 → 498). The loop ran out with the
first non-zero answer never confirmed, so a sync that had in fact fetched every
chat and message declared itself incomplete.

_attempts_needed_to_confirm() grants a one-off extension so the first non-zero
answer always gets a confirmation round. These tests pin both halves: the
extension happens, and it does not turn a still-growing store into a settled one.

Once that budget is spent, _settle_deadline_decision() has to separate two
failures that look identical from the count alone and need opposite answers:
a store that has not finished loading (must stay incomplete, so the health
checker retries) and an account that really has nothing or almost nothing
(must be accepted, or that retry never stops). Chats already stored locally
are the tie-breaker — they cannot vanish, so a server reporting fewer is
behind. See TestZeroIsDisambiguatedByTheLocalCache.
"""

import pytest

from main import MainWindow


needed = MainWindow._attempts_needed_to_confirm

CONFIRM = 2


class TestAttemptBudget:
    def test_no_extension_when_enough_attempts_remain(self):
        # attempt 0 of 6: five more to come, no help needed.
        assert needed(0, 6, CONFIRM) == 6

    def test_no_extension_on_the_exact_boundary(self):
        # attempt 3 of 6 leaves attempts 4 and 5 — exactly CONFIRM.
        assert needed(3, 6, CONFIRM) == 6

    def test_extends_on_the_last_attempt(self):
        # The observed failure: 498 chats arrive on attempt 6 (index 5).
        assert needed(5, 6, CONFIRM) == 8

    def test_extends_on_the_second_to_last_attempt(self):
        assert needed(4, 6, CONFIRM) == 7

    def test_never_shrinks_the_budget(self):
        for attempt in range(10):
            assert needed(attempt, 6, CONFIRM) >= 6


def _run_loop(counts, local_cache, retries=6, confirm=CONFIRM):
    """Faithful replica of _run_sync()'s list-chats retry loop.

    Only the settle decision is reproduced — the HTTP call, the failure/
    disconnect branches and the sleeps are not what these tests are about.
    Returns (chat_list_settled, number_of_fetches_performed).
    """
    has_local_chats = local_cache > 0
    prev_server_count = -1
    settled_flag = False
    saw_nonzero = False
    max_attempts = retries
    attempt = -1
    fetches = 0
    while True:
        attempt += 1
        if attempt >= max_attempts:
            break
        server_count = counts[min(attempt, len(counts) - 1)]
        fetches += 1
        if server_count > 0 and not saw_nonzero:
            saw_nonzero = True
            max_attempts = needed(attempt, max_attempts, confirm)
        settled = server_count > 0 and server_count == prev_server_count
        covers_cache = has_local_chats and server_count >= local_cache
        if settled or covers_cache:
            settled_flag = True
            break
        if attempt == max_attempts - 1:
            decision = MainWindow._settle_deadline_decision(
                server_count, prev_server_count, max_attempts, local_cache
            )
            if decision == "extend":
                max_attempts += MainWindow._CHAT_ATTEMPT_EXTENSION
                prev_server_count = server_count
                continue
            if decision == "accept":
                settled_flag = True
            break
        prev_server_count = server_count
    return settled_flag, fetches


class TestSettleDecision:
    def test_cold_store_that_fills_in_on_the_last_attempt(self):
        """The regression: this is the real log, and it must settle."""
        settled, _ = _run_loop([0, 0, 0, 0, 0, 498, 498], local_cache=0)
        assert settled is True

    def test_reconnection_with_a_warm_local_cache_settles_immediately(self):
        settled, fetches = _run_loop([498], local_cache=498)
        assert settled is True
        assert fetches == 1

    def test_small_account_settling_early_still_works(self):
        settled, fetches = _run_loop([4, 4, 4, 4, 4, 4], local_cache=0)
        assert settled is True
        assert fetches == 2

    def test_a_still_growing_store_is_now_accepted_once_it_is_big(self):
        """Deliberate weakening of the original rule, and the reason this
        exists: refusing a growing snapshot left _sync_completed False, and
        the health checker then restarted the whole sync every time it came
        round — which users experienced as the app announcing "sincronizando"
        again minutes after it had finished. A snapshot this size is a real
        account; the chat poller and live events keep filling it in.

        The old guarantee ("still growing is never settled") now lives at the
        deadline only, keyed on size — see TestDeadlineDecision."""
        settled, _ = _run_loop([4, 7, 11, 16, 22, 29, 37, 46], local_cache=0)
        assert settled is True

    def test_a_late_starting_store_that_keeps_growing_also_settles(self):
        """Same change seen from the cold-store shape: nothing for the first
        attempts, then a list that is still arriving when the original budget
        would have expired."""
        settled, _ = _run_loop([0, 0, 0, 0, 4, 7, 11, 15], local_cache=0)
        assert settled is True

    def test_late_start_that_does_stabilise_settles(self):
        settled, _ = _run_loop([0, 0, 0, 0, 4, 7, 7, 7], local_cache=0)
        assert settled is True

    def test_a_server_stuck_on_zero_with_chats_cached_stays_unsettled(self):
        """We already hold 500 chats; the server insisting on 0 has not
        finished loading its store. Stored chats do not vanish, so this must
        stay incomplete and be retried rather than be taken at face value."""
        settled, _ = _run_loop([0] * 40, local_cache=500)
        assert settled is False

    def test_an_account_that_really_is_empty_eventually_settles(self):
        """Same answers, no local cache to contradict them — a first pairing
        of a number with no conversations. Waiting longer cannot distinguish
        it from a cold store, so once the ceiling is reached the 0 is taken at
        face value; the alternative is re-syncing a brand-new number for ever."""
        settled, _ = _run_loop([0] * 40, local_cache=0)
        assert settled is True

    def test_the_empty_account_is_not_accepted_before_the_ceiling(self):
        """It settles only after the full budget has been spent waiting — a
        store that is merely slow still gets every chance to fill in first."""
        _, fetches = _run_loop([0] * 40, local_cache=0)
        assert fetches == MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS

    @pytest.mark.parametrize("counts", [
        [0, 0, 0, 0, 0, 498, 498],
        [0, 0, 0, 0, 4, 7, 7, 7],
        [4, 4, 4, 4, 4, 4],
    ])
    def test_extension_is_granted_at_most_once(self, counts):
        """saw_nonzero latches, so the budget cannot grow unboundedly."""
        _, fetches = _run_loop(counts, local_cache=0)
        assert fetches <= 6 + CONFIRM


class TestDeadlineDecision:
    """What happens when the loop reaches its last attempt without two equal
    counts — MainWindow._settle_deadline_decision().

    Reported live: sync finished, and a while later announced itself as
    syncing again, with no connection drop. An unsettled snapshot leaves
    _sync_completed False, and the connection health checker (every 30 s)
    calls trigger_sync_if_needed(), which starts the whole sync over. For a
    large account whose chat list is still streaming in from the phone, the
    ~30 s budget (_CHAT_RETRIES 6 x _CHAT_DELAY 5 s) simply ran out every
    time, so the loop repeated indefinitely.
    """

    decide = staticmethod(MainWindow._settle_deadline_decision)

    def test_a_still_growing_list_buys_more_time(self):
        assert self.decide(120, 80, 6) == "extend"

    def test_extending_stops_at_the_absolute_ceiling(self):
        """Waiting is bounded: past the ceiling something is wrong that more
        waiting will not fix."""
        ceiling = MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS
        assert self.decide(120, 80, ceiling) != "extend"
        assert self.decide(120, 80, ceiling - 1) == "extend"

    def test_a_stalled_but_real_snapshot_is_accepted(self):
        """Not growing any more and big enough to be a real account: keeping
        it beats declaring the sync incomplete and having it start over."""
        assert self.decide(498, 498, 6) == "accept"

    def test_a_stalled_tiny_snapshot_is_accepted_too(self):
        """Size is no longer a reason to reject. Four conversations is a
        finished sync for someone who has four conversations, and calling it
        incomplete is what had the health checker restart the sync for ever."""
        assert self.decide(4, 4, 6) == "accept"

    def test_a_growing_list_at_the_ceiling_is_accepted_regardless_of_size(self):
        ceiling = MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS
        assert self.decide(498, 400, ceiling) == "accept"
        assert self.decide(4, 2, ceiling) == "accept"

    def test_zero_buys_time_first(self):
        """0 tells us nothing at all, so it is always worth waiting on while
        the ceiling allows — whether or not anything is cached."""
        assert self.decide(0, -1, 6) == "extend"
        assert self.decide(0, 0, 6) == "extend"
        assert self.decide(0, 0, 6, 500) == "extend"

    @pytest.mark.parametrize("count", [1, 5, 9, 10, 11, 50, 498, 5000])
    def test_any_real_snapshot_is_accepted_when_stalled(self, count):
        assert self.decide(count, count, 6) == "accept"


class TestZeroIsDisambiguatedByTheLocalCache:
    """The heart of the rule: a bare count cannot tell "the store is still
    cold" from "this account is genuinely empty" — both answer 0 — and the two
    need opposite outcomes. Chats already stored locally cannot vanish, so
    they are the tie-breaker.
    """

    decide = staticmethod(MainWindow._settle_deadline_decision)
    ceiling = MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS

    def test_zero_against_a_populated_cache_is_incomplete(self):
        """500 chats are on disk and the server claims none: it has not
        finished loading. Only an incomplete sync gets retried, so accepting
        this would strand the session with nothing left to fix it."""
        assert self.decide(0, 0, self.ceiling, 500) == "incomplete"

    def test_zero_with_no_cache_is_an_empty_account(self):
        """Nothing contradicts the 0 — a first pairing of a number with no
        conversations. Retrying for ever would never produce a 1."""
        assert self.decide(0, 0, self.ceiling, 0) == "accept"

    def test_falling_short_of_the_cache_is_still_accepted(self):
        """The cache breaks the tie for zero and nothing else.

        Chats really can disappear from the server: the user deletes them
        from another device. Rejecting every snapshot smaller than the cache
        would call that "the server is behind" and retry for ever, which is
        the exact loop this whole rule exists to avoid.

        Nor is the check needed for a non-zero count. The loop's own
        two-equal exit fires on any stable answer, short of the cache or not,
        long before this deadline — and it never consulted the cache, on any
        version. An answer that is still moving is genuinely still moving."""
        assert self.decide(300, 300, self.ceiling, 660) == "accept"

    def test_reaching_the_cache_is_accepted(self):
        assert self.decide(660, 660, self.ceiling, 660) == "accept"
        assert self.decide(700, 700, self.ceiling, 660) == "accept"

    def test_an_unstable_count_below_the_cache_is_accepted(self):
        """A raw list-chats count can wobble (it includes the phantom entries
        filtered out later), so "never two equal in a row" is reachable
        without anything being wrong. This used to come out incomplete after
        only six attempts."""
        assert self.decide(448, 451, self.ceiling, 500) == "accept"

    @pytest.mark.parametrize("count", [1, 4, 10, 498])
    def test_a_real_snapshot_with_no_cache_is_never_incomplete(self, count):
        """The small-account guarantee: with nothing cached to fall short of,
        no non-zero answer can be rejected for its size."""
        assert self.decide(count, count, self.ceiling, 0) == "accept"

    @pytest.mark.parametrize("count", [1, 4, 10, 498, 5000])
    def test_no_non_zero_answer_is_ever_incomplete(self, count):
        """Zero is the only count that can produce "incomplete" at all —
        whatever the cache says, and whether or not the list is still moving.
        Anything else would make deleting chats elsewhere loop."""
        for prev in (-1, 0, count - 1, count, count + 1):
            for cache in (0, 1, count, count * 2):
                assert self.decide(count, prev, self.ceiling, cache) != "incomplete"

    def test_deleting_every_conversation_elsewhere_is_the_known_ambiguity(self):
        """Documented, not accidental: 0 against a populated cache is
        indistinguishable from a store that never loaded, so it keeps
        retrying. The cached chats stay on screen meanwhile, and retrying is
        the recoverable half of the pair — accepting a broken store is not."""
        assert self.decide(0, 0, self.ceiling, 500) == "incomplete"


class TestTheLoopEndToEnd:
    def test_a_large_account_that_keeps_growing_now_settles(self):
        """The reported case: the list is still filling in when the original
        6-attempt budget expires. It must not come out unsettled — that is
        what made the sync restart itself later."""
        counts = [0, 40, 90, 150, 220, 300, 380, 460, 540, 600, 640, 660, 660]
        settled, _ = _run_loop(counts, local_cache=0)
        assert settled is True

    def test_a_large_account_that_never_stops_growing_is_still_accepted(self):
        """Even with no two equal counts anywhere, a big snapshot beats an
        endless re-sync loop."""
        counts = [i * 40 for i in range(1, 40)]
        settled, _ = _run_loop(counts, local_cache=0)
        assert settled is True

    def test_the_extension_is_bounded(self):
        """It buys time, it does not hang: the loop cannot run past the
        ceiling however long the list keeps growing."""
        counts = [i * 40 for i in range(1, 60)]
        _, fetches = _run_loop(counts, local_cache=0)
        assert fetches <= MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS


class TestSmallAccountsAreNotLockedOut:
    """The size threshold must never keep a genuinely small account from
    finishing its sync.

    It only exists in the deadline branch, and the deadline is only reached
    when the count never repeats. A small account's count repeats on the very
    next attempt, so it settles by the two-equal rule long before size is
    ever consulted — an account with one conversation syncs in two attempts.
    """

    @pytest.mark.parametrize("counts,label", [
        ([3, 3, 3, 3, 3, 3], "three chats, answered immediately"),
        ([1, 1, 1, 1, 1, 1], "a single conversation"),
        ([0, 0, 0, 0, 0, 3, 3], "cold store, three chats arriving last"),
        ([1, 2, 3, 4, 4, 4], "filling in, then stable at four"),
        ([0, 0, 2, 2, 2, 2], "slow first answer, two chats"),
        ([0, 0, 0, 0, 0, 1, 1], "one conversation, arriving late"),
    ])
    def test_a_small_account_still_settles(self, counts, label):
        settled, _ = _run_loop(counts, local_cache=0)
        assert settled is True, label

    def test_a_small_account_never_reaches_the_size_check(self):
        """Two attempts, not the full budget — proof the deadline branch (the
        only place size is looked at) is not involved."""
        _, fetches = _run_loop([3, 3, 3, 3, 3, 3], local_cache=0)
        assert fetches == 2

    def test_nothing_cached_means_the_deadline_never_says_incomplete(self):
        """A first sync has no cache to fall short of, so "incomplete" — the
        one outcome that sends the health checker round again — is
        unreachable however small the account turns out to be. That is what
        keeps a genuinely small (or empty) account from looping for ever."""
        ceiling = MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS
        outcomes = {
            MainWindow._settle_deadline_decision(count, prev, budget, 0)
            for count in (0, 1, 4, 10, 11, 500)
            for prev in (-1, 0, 3, 10, 499)
            for budget in (6, ceiling)
        }
        assert outcomes <= {"extend", "accept"}
        assert MainWindow._settle_deadline_decision(4, 4, ceiling, 0) == "accept"
