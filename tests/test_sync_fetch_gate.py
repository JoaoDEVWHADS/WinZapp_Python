"""Issue #379: the sync and backfill do not fire get-messages from six threads.

Every get-messages is evaluated in the one WhatsApp Web page Puppeteer drives
over a single CDP connection, so parallelism past a couple of calls only queues
work inside the page and costs CPU and memory (143% CPU, 2.98 GB of Chromium on
a 616-chat account). The requests of the two pools now share a gate of
SYNC_FETCH_CONCURRENCY — and nothing else does: a person opening a chat or
scrolling up must never queue behind a background sweep, a request's own timeout
must not include its wait, and a worker must never be held forever.
"""

import pathlib
import threading
import time

import pytest

from core import api_client
from core.api_client import SYNC_FETCH_CONCURRENCY, api_get, api_post, sync_throttled

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
URL = "http://127.0.0.1:6300/api/s:t/get-messages/5511900000000@s.whatsapp.net?count=200"
OTHER = "http://127.0.0.1:6300/api/s:t/list-chats"


class _Response:
    status_code = 200


class _Session:
    """Counts how many calls are inside `get` at once."""

    def __init__(self, hold=0.03):
        self.hold = hold
        self.lock = threading.Lock()
        self.inside = 0
        self.peak = 0
        self.calls = []

    def _call(self, url, **kwargs):
        with self.lock:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
            self.calls.append((url, kwargs))
        time.sleep(self.hold)
        with self.lock:
            self.inside -= 1
        return _Response()

    get = _call
    post = _call


def _run_in_threads(count, target):
    threads = [threading.Thread(target=target) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads)


class TestTheLimit:
    def test_six_throttled_workers_never_have_more_than_the_limit_in_flight(self):
        session = _Session()
        task = sync_throttled(lambda: api_get(URL, session=session))

        _run_in_threads(6, task)

        assert len(session.calls) == 6
        assert session.peak <= SYNC_FETCH_CONCURRENCY

    def test_the_limit_is_two(self):
        """The experiment the maintainers asked for first (issue #379)."""
        assert SYNC_FETCH_CONCURRENCY == 2

    def test_they_do_run_two_at_a_time_so_the_sync_is_not_serialised(self):
        session = _Session(hold=0.1)
        task = sync_throttled(lambda: api_get(URL, session=session))

        _run_in_threads(4, task)

        assert session.peak == SYNC_FETCH_CONCURRENCY


class TestWhatTheGateLeavesAlone:
    def test_a_request_outside_the_pools_is_not_throttled(self):
        """Opening a chat, scrolling up, the resync command: a person is waiting."""
        session = _Session()

        _run_in_threads(6, lambda: api_get(URL, session=session))

        assert session.peak > SYNC_FETCH_CONCURRENCY

    def test_other_endpoints_inside_the_pools_are_not_throttled(self):
        session = _Session()
        task = sync_throttled(lambda: api_get(OTHER, session=session))

        _run_in_threads(6, task)

        assert session.peak > SYNC_FETCH_CONCURRENCY

    def test_a_post_inside_the_pools_is_not_throttled(self):
        session = _Session()
        task = sync_throttled(lambda: api_post(URL, session=session))

        _run_in_threads(6, task)

        assert session.peak > SYNC_FETCH_CONCURRENCY

    def test_the_callers_timeout_and_headers_reach_the_call_unchanged(self):
        session = _Session()

        sync_throttled(lambda: api_get(URL, headers={"X-A": "1"}, timeout=17, session=session))()

        [(url, kwargs)] = session.calls
        assert url == URL
        assert kwargs["timeout"] == 17
        assert kwargs["headers"]["X-A"] == "1"

    def test_the_response_is_the_real_one(self):
        session = _Session()

        response = sync_throttled(lambda: api_get(URL, session=session))()

        assert isinstance(response, _Response)


class TestTheMark:
    def test_the_wrapper_returns_what_the_task_returns_and_passes_its_arguments(self):
        assert sync_throttled(lambda a, b=0: a + b)(1, b=2) == 3

    def test_the_mark_is_gone_afterwards(self):
        assert not api_client._gate_scope.__dict__.get("active", False)
        sync_throttled(lambda: None)()
        assert not api_client._gate_scope.__dict__.get("active", False)

    def test_a_failing_task_does_not_leave_its_thread_throttled(self):
        def boom():
            raise RuntimeError("x")

        with pytest.raises(RuntimeError):
            sync_throttled(boom)()
        assert not api_client._gate_scope.__dict__.get("active", False)

    def test_nesting_restores_the_outer_state(self):
        seen = []
        inner = sync_throttled(lambda: seen.append(api_client._gate_scope.active))
        sync_throttled(lambda: (inner(), seen.append(api_client._gate_scope.active)))()
        assert seen == [True, True]
        assert not api_client._gate_scope.__dict__.get("active", False)

    def test_the_mark_is_per_thread(self):
        """A thread started from inside a throttled task is not itself throttled."""
        seen = []
        child = threading.Thread(
            target=lambda: seen.append(api_client._gate_scope.__dict__.get("active", False)))

        def task():
            child.start()
            child.join(5)

        sync_throttled(task)()
        assert seen == [False]


class TestAFailingRequestFreesItsPlace:
    def test_the_next_request_still_gets_one(self):
        class Boom(_Session):
            def _call(self, url, **kwargs):
                raise ConnectionError("down")

            get = _call

        for _ in range(SYNC_FETCH_CONCURRENCY * 3):
            with pytest.raises(ConnectionError):
                sync_throttled(lambda: api_get(URL, session=Boom()))()

        session = _Session()
        sync_throttled(lambda: api_get(URL, session=session))()
        assert len(session.calls) == 1


class TestAWorkerIsNeverHeldForever:
    def test_past_the_bound_the_request_goes_out_as_it_did_before(self, monkeypatch):
        monkeypatch.setattr(api_client, "SYNC_GATE_MAX_WAIT_SECONDS", 0.05)
        taken = [api_client._SYNC_GATE.acquire() for _ in range(SYNC_FETCH_CONCURRENCY)]
        try:
            session = _Session()
            started = time.monotonic()
            sync_throttled(lambda: api_get(URL, session=session))()
            assert len(session.calls) == 1
            assert time.monotonic() - started < 5
        finally:
            for _ in taken:
                api_client._SYNC_GATE.release()

    def test_a_request_that_did_not_wait_for_a_place_gives_none_back(self, monkeypatch):
        """A BoundedSemaphore raises on a release nobody paid for: the gate would
        turn a slow queue into an exception."""
        monkeypatch.setattr(api_client, "SYNC_GATE_MAX_WAIT_SECONDS", 0.01)
        taken = [api_client._SYNC_GATE.acquire() for _ in range(SYNC_FETCH_CONCURRENCY)]
        try:
            sync_throttled(lambda: api_get(URL, session=_Session()))()
        finally:
            for _ in taken:
                api_client._SYNC_GATE.release()
        # Every place is back, none extra.
        again = [api_client._SYNC_GATE.acquire(blocking=False) for _ in range(SYNC_FETCH_CONCURRENCY)]
        assert all(again)
        assert api_client._SYNC_GATE.acquire(blocking=False) is False
        for _ in again:
            api_client._SYNC_GATE.release()

    def test_waiting_is_not_counted_against_the_callers_timeout(self):
        """The timeout handed to the call is the caller's, whatever the queue
        looked like: a queue is not an I/O fault."""
        session = _Session(hold=0.05)
        results = []

        def task():
            api_get(URL, timeout=1.5, session=session)

        _run_in_threads(5, sync_throttled(task))

        assert {kwargs["timeout"] for _url, kwargs in session.calls} == {1.5}


class TestWhoIsThrottled:
    """Source-level: the two pools wrap their tasks, and nothing a person waits on."""

    def test_the_sync_pool_wraps_both_of_its_submits(self):
        source = (CLIENT / "main_window/sync.py").read_text(encoding="utf-8")
        assert source.count("pool.submit(sync_throttled(self.sync_chat_messages)") == 2

    def test_the_backfill_pool_wraps_its_submit(self):
        source = (CLIENT / "main_window/backfill.py").read_text(encoding="utf-8")
        assert "sync_throttled(self.sync_chat_messages), c, my_run" in source

    def test_the_resync_command_and_scrolling_up_are_not_wrapped(self):
        sync = (CLIENT / "main_window/sync.py").read_text(encoding="utf-8")
        history = (CLIENT / "main_window/history.py").read_text(encoding="utf-8")
        assert "ok = bool(chat) and bool(self.sync_chat_messages(" in sync
        assert "sync_throttled" not in history

    def test_nothing_else_submits_the_chat_sync_unwrapped(self):
        import re

        offenders = []
        for path in CLIENT.rglob("*.py"):
            rel = path.relative_to(CLIENT).as_posix()
            if rel.startswith(("api/", "node/", "lib/")):
                continue
            if re.search(r"submit\(\s*self\.sync_chat_messages", path.read_text(encoding="utf-8")):
                offenders.append(rel)
        assert offenders == []
