"""A V8 garbage collection of the WhatsApp Web page after large sync batches.

Issue #379, part 2. The sync and backfill move large message arrays across the
Puppeteer bridge; once answered they are garbage, but Chromium can leave that
space unreclaimed long after a big sync (the report: 2.98 GB of Chromium on a
616-chat account). WinZapp's own route (client/api_patches/src/controller/
pageHeapController.ts) runs HeapProfiler.collectGarbage in the page, which
reclaims only what nothing references, so no WhatsApp Web state is lost.

When, deliberately narrow:

* only after a sync or backfill pass has finished its batch, never in the
  middle of one, and never for anything a person is waiting on;
* only once that work has carried at least GC_PAYLOAD_BYTES of get-messages
  answers since the last collection (api_client feeds the meter for the calls
  the sync gate covers, the same set: issue #379's part 1), so the small
  once-a-minute rounds never trigger one;
* at most once every GC_MIN_INTERVAL_SECONDS, one at a time, on its own thread,
  with WhatsApp connected and WinZapp not shutting down;
* best effort: a server without the route (an older or external one) answers
  404, and the collection is then not asked for again this run. A failure is
  never a sync failure and never reaches message_failures.
"""

from __future__ import annotations

import logging
import threading
import time

#: get-messages answers since the last collection that make one worth it.
GC_PAYLOAD_BYTES = 16 * 1024 * 1024

#: The shortest time between two collections, attempted or done.
GC_MIN_INTERVAL_SECONDS = 180.0

#: The HTTP budget: the route's own deadline is 20 s.
GC_REQUEST_TIMEOUT_SECONDS = 30


class HeapCollectionPolicy:
    """Whether a collection is due. Thread-safe; no I/O, no wx."""

    def __init__(self, payload_bytes: int = GC_PAYLOAD_BYTES,
                 min_interval: float = GC_MIN_INTERVAL_SECONDS):
        self._lock = threading.Lock()
        self._payload_bytes = payload_bytes
        self._min_interval = min_interval
        self._pending = 0
        self._last_attempt = None
        self._running = False
        self.unsupported = False

    def note_payload(self, nbytes) -> None:
        if isinstance(nbytes, int) and nbytes > 0:
            with self._lock:
                self._pending += nbytes

    def claim(self, now: float):
        """The bytes this collection answers for, or None when none is due.
        A claim must be followed by finish()."""
        with self._lock:
            if self.unsupported or self._running or self._pending < self._payload_bytes:
                return None
            if self._last_attempt is not None and now - self._last_attempt < self._min_interval:
                return None
            self._running = True
            self._last_attempt = now
            return self._pending

    def finish(self, collected: bool, claimed: int = 0, unsupported: bool = False) -> None:
        """Close a claim. A collection that ran resets the meter by what it
        answered for (bytes that arrived meanwhile still count); one that did
        not keeps it, for the next pass after the interval."""
        with self._lock:
            self._running = False
            if unsupported:
                self.unsupported = True
            if collected:
                self._pending = max(0, self._pending - max(0, int(claimed)))


_policy = HeapCollectionPolicy()


def note_sync_payload(nbytes) -> None:
    """api_client: one get-messages answer of the sync or backfill arrived."""
    _policy.note_payload(nbytes)


def _megabytes(value) -> str:
    return f"{value / (1024 * 1024):.0f} MB" if isinstance(value, (int, float)) else "?"


def describe(result: dict, claimed: int) -> str:
    """The log line for a collection that ran: sizes and times only."""
    took = result.get("tookMs")
    took_text = f"{took:.0f} ms" if isinstance(took, (int, float)) else "? ms"
    return (f"[page-heap] V8 garbage collection after a large sync batch: "
            f"page heap {_megabytes(result.get('before'))} -> {_megabytes(result.get('after'))} "
            f"in {took_text} ({_megabytes(claimed)} of messages since the last one)")


def request_collection(server: str, port, token: str) -> tuple:
    """POST the route once. (outcome, measurements): outcome is "collected",
    "unsupported" (no such route: 404) or "failed". Never raises."""
    from core.api_client import api_post
    url = f"{server}:{port}/api/{token}/collect-page-garbage"
    try:
        response = api_post(url, json={}, headers={"Authorization": f"Bearer {token}"},
                            timeout=GC_REQUEST_TIMEOUT_SECONDS)
    except Exception as exc:
        logging.info("[page-heap] collection request failed: %s", type(exc).__name__)
        return "failed", {}
    if response.status_code == 404:
        return "unsupported", {}
    try:
        body = response.json()
    except Exception:
        body = None
    if (response.status_code == 200 and isinstance(body, dict)
            and body.get("status") == "success" and isinstance(body.get("response"), dict)):
        return "collected", body["response"]
    code = body.get("code") if isinstance(body, dict) else None
    logging.info("[page-heap] collection not done (HTTP %s, %s)", response.status_code,
                 code if isinstance(code, str) else "no code")
    return "failed", {}


def _may_collect(main_window) -> bool:
    if getattr(main_window, "_shutting_down", False):
        return False
    if getattr(main_window, "_wa_connected", False) is not True:
        return False
    server = getattr(main_window, "wpp_server", None)
    token = getattr(main_window, "token", None)
    return isinstance(server, str) and bool(server) and isinstance(token, str) and bool(token)


def collect_after_batch(main_window, policy: HeapCollectionPolicy = None,
                        start_thread=None, now: float = None) -> bool:
    """Called when a sync or backfill pass has finished its batch. Starts one
    collection on its own thread when one is due; True when it did. Never
    raises and never blocks the caller."""
    policy = policy or _policy
    try:
        if not _may_collect(main_window):
            return False
        claimed = policy.claim(time.monotonic() if now is None else now)
        if claimed is None:
            return False
        connection = (main_window.wpp_server, getattr(main_window, "wpp_port", 6300),
                      main_window.token)

        def _run():
            outcome = "failed"
            try:
                outcome, measured = request_collection(*connection)
                if outcome == "collected":
                    logging.info(describe(measured, claimed))
                elif outcome == "unsupported":
                    logging.info("[page-heap] the WPPConnect Server has no garbage "
                                 "collection route; not asking again this run")
            finally:
                policy.finish(outcome == "collected", claimed, unsupported=outcome == "unsupported")

        if start_thread is None:
            start_thread = lambda target: threading.Thread(
                target=target, daemon=True, name="winzapp-page-gc").start()
        try:
            start_thread(_run)
        except Exception:
            policy.finish(False)
            raise
        return True
    except Exception:
        logging.exception("[page-heap] could not start a collection")
        return False
