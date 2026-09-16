"""Push a read state to WhatsApp for many chats without flooding WPPConnect.

"Marcar todas as conversas como lidas" used to start one thread per unread
chat, each firing its own ``/send-seen`` at the same instant. Measured on a
real account with ~100 unread chats: every request left within the same
millisecond, the Node side took 3-6 s to answer each one instead of the
~250 ms a lone request takes, and a batch of them hit the 10 s read timeout
and had to be retried on top of the queue that caused the timeout. WPPConnect
drives a single WhatsApp Web page, so its throughput does not grow with the
number of concurrent callers — past a few, extra concurrency only turns into
latency and timeouts.

So the work goes through a small fixed pool, and completion is guaranteed by
rounds rather than by a retry count: every chat that failed in a round is
tried again in the next one, for as long as the run keeps making progress.

**The give-up rule is time without progress, never a number of rounds.** The
two ways WhatsApp Web can be unavailable fail at opposite speeds, and a round
count is wrong for both. A page reload makes ``/send-seen`` fail instantly
(the endpoint skips the connection probe), so three quick rounds would give up
after a few seconds and roll back hundreds of chats over an ordinary 15 s
reload. A hung page makes every request run into its 10 s timeout — twice per
chat, one per JID alias — so a single round over 300 chats would last ~25 min
while the badges claim "read". Measuring ``idle_timeout`` since the last
confirmed chat, and checking it before every send as well as between rounds,
bounds both cases by the same wall-clock patience.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

# Enough to keep WPPConnect's single page busy; more only adds latency.
DEFAULT_MAX_WORKERS = 4
# Seconds with no confirmed chat before the remainder is given up. Long enough
# to ride out a WhatsApp Web reload, short enough that a dead page is reported.
DEFAULT_IDLE_TIMEOUT = 120.0


def _idle_backoff(idle_rounds: int) -> float:
    """Seconds to wait after the Nth consecutive round with no progress."""
    return float(min(2 ** idle_rounds, 15))


def run_bulk_read_state(
    jids: Iterable[str],
    send_one: Callable[[str], bool],
    *,
    max_workers: int = DEFAULT_MAX_WORKERS,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[str]:
    """Run ``send_one(jid)`` for every JID; return those that never succeeded.

    ``send_one`` is blocking and returns True only when WhatsApp confirmed the
    change. An exception from it counts as a failure of that chat for the
    round, never as a failure of the whole run.
    """
    pending = list(dict.fromkeys(j for j in jids if j))
    if not pending:
        return []

    lock = threading.Lock()
    last_progress = [clock()]

    def _stalled() -> bool:
        with lock:
            return clock() - last_progress[0] >= idle_timeout

    def _attempt(jid: str) -> bool:
        # Checked per chat, not only per round: a hung page would otherwise
        # hold a whole round of 10 s timeouts past the budget.
        if _stalled():
            return False
        try:
            ok = bool(send_one(jid))
        except Exception:
            logging.exception("[bulk_read_state] send failed for %s", jid)
            ok = False
        if ok:
            with lock:
                last_progress[0] = clock()
        return ok

    idle_rounds = 0
    round_no = 0
    with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as pool:
        while pending:
            round_no += 1
            results = list(pool.map(_attempt, pending))
            failed = [jid for jid, ok in zip(pending, results) if not ok]
            succeeded = len(pending) - len(failed)
            logging.info(
                "[bulk_read_state] round %d: %d ok, %d pending",
                round_no, succeeded, len(failed),
            )
            pending = failed
            if not pending:
                break
            if _stalled():
                logging.warning(
                    "[bulk_read_state] no progress for %.0fs; giving up on %d chats",
                    idle_timeout, len(pending),
                )
                break
            if succeeded:
                idle_rounds = 0
                # Brief pause so a server that was shedding load catches up.
                sleep(1.0)
            else:
                idle_rounds += 1
                sleep(_idle_backoff(idle_rounds))
    return pending
