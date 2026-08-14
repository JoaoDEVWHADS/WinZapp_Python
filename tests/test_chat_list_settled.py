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
                server_count, prev_server_count, max_attempts
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

    def test_server_that_never_answers_with_anything_stays_unsettled(self):
        settled, fetches = _run_loop([0, 0, 0, 0, 0, 0], local_cache=0)
        assert settled is False
        # No non-zero answer ever arrived, so no extension was granted either.
        assert fetches == 6

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

    def test_a_stalled_tiny_snapshot_stays_incomplete(self):
        """The failure the settle rule exists for — four conversations is not
        an account, and accepting it would strand the user there."""
        assert self.decide(4, 4, 6) == "incomplete"

    def test_a_growing_list_at_the_ceiling_is_still_judged_on_size(self):
        ceiling = MainWindow._CHAT_ABSOLUTE_MAX_ATTEMPTS
        assert self.decide(498, 400, ceiling) == "accept"
        assert self.decide(4, 2, ceiling) == "incomplete"

    def test_zero_chats_is_never_growth_and_never_acceptable(self):
        """A server answering 0 has told us nothing; there is no snapshot to
        accept and nothing to wait for on this branch."""
        assert self.decide(0, -1, 6) == "incomplete"
        assert self.decide(0, 0, 6) == "incomplete"

    @pytest.mark.parametrize("count", [11, 50, 498, 5000])
    def test_sizes_above_the_threshold_are_accepted_when_stalled(self, count):
        assert self.decide(count, count, 6) == "accept"

    @pytest.mark.parametrize("count", [1, 5, 9, 10])
    def test_sizes_at_or_below_the_threshold_are_not(self, count):
        assert self.decide(count, count, 6) == "incomplete"


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
