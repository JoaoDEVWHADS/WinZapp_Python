"""Issue #379, part 2: one V8 garbage collection of the WhatsApp Web page after
a large sync or backfill batch (core/page_heap.py).

This touches the sync, so what must hold is mostly what it must NOT do: never
during a batch, never for the small once-a-minute rounds, never twice at once,
never on a server without the route after it said so, never while shutting down
or disconnected, and never as a sync failure.
"""

import pathlib
import types

import pytest

from core import api_client, page_heap
from core.api_client import api_get, sync_throttled
from core.page_heap import HeapCollectionPolicy, collect_after_batch

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
URL = "http://127.0.0.1:6300/api/s:t/get-messages/5511900000000@s.whatsapp.net?count=200"
MB = 1024 * 1024


def _policy(payload=10, interval=100.0):
    return HeapCollectionPolicy(payload_bytes=payload, min_interval=interval)


class TestWhenItIsDue:
    def test_not_before_enough_has_crossed_the_bridge(self):
        policy = _policy(payload=10)
        policy.note_payload(9)
        assert policy.claim(now=1000) is None
        policy.note_payload(1)
        assert policy.claim(now=1000) == 10

    def test_only_one_at_a_time(self):
        policy = _policy()
        policy.note_payload(50)
        assert policy.claim(now=1000) == 50
        assert policy.claim(now=5000) is None, "the first one has not finished"

    def test_never_twice_within_the_interval_even_after_a_failure(self):
        policy = _policy(interval=100)
        policy.note_payload(50)
        policy.claim(now=1000)
        policy.finish(False)
        assert policy.claim(now=1099) is None
        assert policy.claim(now=1100) == 50, "a failed one keeps the meter for later"

    def test_a_collection_that_ran_resets_by_what_it_answered_for(self):
        policy = _policy(interval=0)
        policy.note_payload(50)
        claimed = policy.claim(now=1000)
        policy.note_payload(7)  # arrived while it ran
        policy.finish(True, claimed)
        assert policy.claim(now=2000) is None
        policy.note_payload(3)
        assert policy.claim(now=2000) == 10

    def test_a_server_without_the_route_is_not_asked_again(self):
        policy = _policy(interval=0)
        policy.note_payload(50)
        policy.claim(now=1000)
        policy.finish(False, unsupported=True)
        policy.note_payload(500)
        assert policy.claim(now=9999) is None

    @pytest.mark.parametrize("value", [0, -5, None, "12", 3.5])
    def test_nonsense_sizes_are_ignored(self, value):
        policy = _policy(payload=1)
        policy.note_payload(value)
        assert policy.claim(now=1000) is None

    def test_the_defaults_leave_the_small_rounds_alone(self):
        assert page_heap.GC_PAYLOAD_BYTES >= 8 * MB
        assert page_heap.GC_MIN_INTERVAL_SECONDS >= 60


def _mw(**overrides):
    values = dict(_wa_connected=True, _shutting_down=False, wpp_server="http://127.0.0.1",
                  wpp_port=6300, token="session-token")
    values.update(overrides)
    return types.SimpleNamespace(**values)


class _Response:
    def __init__(self, status_code, body=None, raises=False):
        self.status_code = status_code
        self._body = body
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._body


class TestAfterABatch:
    def _due(self):
        policy = _policy(payload=1, interval=0)
        policy.note_payload(5 * MB)
        return policy

    def test_a_due_collection_runs_on_its_own_thread_and_logs_sizes_only(self, monkeypatch, caplog):
        posted = []

        def _post(url, **kwargs):
            posted.append((url, kwargs))
            return _Response(200, {"status": "success",
                                   "response": {"before": 900 * MB, "after": 400 * MB, "tookMs": 54}})

        monkeypatch.setattr(api_client, "api_post", _post)
        threads = []
        policy = self._due()
        caplog.set_level("INFO")

        assert collect_after_batch(_mw(), policy=policy, start_thread=threads.append, now=1) is True
        assert posted == [], "the caller never waits for the collection"
        threads[0]()

        [(url, kwargs)] = posted
        assert url == "http://127.0.0.1:6300/api/session-token/collect-page-garbage"
        assert kwargs["headers"] == {"Authorization": "Bearer session-token"}
        assert "page heap 900 MB -> 400 MB in 54 ms (5 MB of messages" in caplog.text
        assert policy.claim(now=2) is None, "the meter was reset"

    @pytest.mark.parametrize("overrides", [
        {"_wa_connected": False}, {"_wa_connected": None}, {"_shutting_down": True},
        {"token": ""}, {"wpp_server": None},
    ])
    def test_nothing_is_started_when_it_must_not_run(self, overrides):
        threads = []
        policy = self._due()
        assert collect_after_batch(_mw(**overrides), policy=policy,
                                   start_thread=threads.append, now=1) is False
        assert threads == []
        assert policy.claim(now=1) is not None, "the meter is kept for later"

    def test_a_stub_main_window_is_left_alone(self):
        """Every existing sync test runs these passes against stubs."""
        threads = []
        assert collect_after_batch(types.SimpleNamespace(), policy=self._due(),
                                   start_thread=threads.append) is False
        assert threads == []

    def test_a_404_marks_the_server_as_without_the_route(self, monkeypatch):
        monkeypatch.setattr(api_client, "api_post", lambda url, **kw: _Response(404, raises=True))
        threads, policy = [], self._due()
        collect_after_batch(_mw(), policy=policy, start_thread=threads.append, now=1)
        threads[0]()
        assert policy.unsupported is True

    @pytest.mark.parametrize("response", [
        _Response(409, {"status": "error", "code": "busy"}),
        _Response(504, {"status": "error", "code": "timeout"}),
        _Response(503, raises=True),
        _Response(200, {"status": "success"}),
    ])
    def test_any_other_answer_is_a_failed_attempt_kept_for_later(self, monkeypatch, response):
        monkeypatch.setattr(api_client, "api_post", lambda url, **kw: response)
        threads, policy = [], self._due()
        collect_after_batch(_mw(), policy=policy, start_thread=threads.append, now=1)
        threads[0]()
        assert policy.unsupported is False
        assert policy.claim(now=2) is not None

    def test_a_request_that_raises_never_escapes_the_thread(self, monkeypatch):
        def _boom(url, **kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(api_client, "api_post", _boom)
        threads, policy = [], self._due()
        collect_after_batch(_mw(), policy=policy, start_thread=threads.append, now=1)
        threads[0]()
        assert policy.claim(now=2) is not None

    def test_a_thread_that_cannot_start_releases_the_claim(self):
        def _refuse(_target):
            raise RuntimeError("can't start new thread")

        policy = self._due()
        assert collect_after_batch(_mw(), policy=policy, start_thread=_refuse, now=1) is False
        assert policy.claim(now=2) is not None


class TestTheMeter:
    class _Session:
        def __init__(self, size):
            self.size = size

        def get(self, url, **kwargs):
            response = types.SimpleNamespace(status_code=200, content=b"x" * self.size)
            return response

    def test_sync_and_backfill_answers_are_counted(self, monkeypatch):
        policy = _policy(payload=1000)
        monkeypatch.setattr(page_heap, "_policy", policy)
        sync_throttled(lambda: api_get(URL, session=self._Session(600)))()
        sync_throttled(lambda: api_get(URL, session=self._Session(400)))()
        assert policy.claim(now=1) == 1000

    def test_what_a_person_is_waiting_on_is_not_counted(self, monkeypatch):
        policy = _policy(payload=1)
        monkeypatch.setattr(page_heap, "_policy", policy)
        api_get(URL, session=self._Session(5000))
        assert policy.claim(now=1) is None


class TestWhereItIsAsked:
    def test_after_each_sync_pass_once_its_pool_is_done(self):
        source = (CLIENT / "main_window" / "sync.py").read_text(encoding="utf-8")
        body = source[source.index("    def sync_remote_chats("):]
        assert body.index("collect_after_batch(self)") > body.index("for future in as_completed(futures):")
        assert body.count("collect_after_batch(self)") == 1

    def test_after_each_backfill_pass_once_its_pool_is_done(self):
        source = (CLIENT / "main_window" / "backfill.py").read_text(encoding="utf-8")
        pool = source.index("with ThreadPoolExecutor(max_workers=self._BACKFILL_WORKERS) as pool:")
        call = source.index("collect_after_batch(self)")
        assert call > pool
        assert call < source.index("before phone requests.", pool)
        assert source.count("collect_after_batch(self)") == 1
