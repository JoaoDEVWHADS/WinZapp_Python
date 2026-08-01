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

    def test_still_growing_store_is_never_called_settled(self):
        """The failure the two-equal-counts rule exists for: accepting a
        partial snapshot left users with three or four conversations."""
        settled, _ = _run_loop([4, 7, 11, 16, 22, 29, 37, 46], local_cache=0)
        assert settled is False

    def test_growing_store_is_not_rescued_by_the_extension(self):
        """The extension buys time, it does not weaken the rule — a store that
        is still growing when the extended budget runs out stays unsettled."""
        settled, _ = _run_loop([0, 0, 0, 0, 4, 7, 11, 15], local_cache=0)
        assert settled is False

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
