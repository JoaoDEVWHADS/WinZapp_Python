"""Regression tests: the @lid<->phone mapping caches were mutated from two
threads with nothing coordinating them.

_extract_lid_mapping() runs unprotected on the Socket.IO callback thread —
WebSocketClient.on_messages_upsert() (core/websocket_client.py) calls it
directly, not via wx.CallAfter like on_new_message()/on_historical_message()
— specifically so it can start bridging @lid identifiers before a sync has
even begun (see the method's own docstring). The wx main thread reaches the
very same _lid_to_phone/_phone_to_lid/_message_pushname_cache/
_chats_without_alt_jid dictionaries through on_new_message()'s own call into
this method, and a third, background sync thread rebuilds the same two
caches wholesale via _build_lid_to_phone_cache(). None of that was ever
serialized: a check-then-set race between two threads on the same key can
lose one thread's update, and a concurrent discard()/rebuild during another
thread's iteration can raise "set/dict changed size during iteration"
outright.

The fix adds self._lid_mapping_lock (a threading.RLock, set up alongside the
already-existing _own_sent_ids_lock in MainWindow.__init__) around the
mutating sections of both methods.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so _extract_lid_mapping is exercised bound to a small stub — same
approach as tests/test_lid_merge_keeps_messages.py, whose own docstring
explains why.
"""

import inspect
import threading
import time

import pytest

import main
from main import MainWindow

_extract_lid_mapping = MainWindow._extract_lid_mapping


class _TrackingLock:
    """A real lock that also records how many threads were ever inside it
    at once — the thing an ordinary threading.Lock can't tell you on its
    own, and exactly what proves the code actually serializes on it rather
    than merely importing threading for show."""

    def __init__(self):
        self._real = threading.RLock()
        self._guard = threading.Lock()
        self._concurrent = 0
        self.max_concurrent = 0
        self.enters = 0

    def __enter__(self):
        self._real.acquire()
        with self._guard:
            self._concurrent += 1
            self.enters += 1
            self.max_concurrent = max(self.max_concurrent, self._concurrent)
        # Widen the critical section on purpose: without the lock actually
        # serializing callers, this is more than enough time for a second
        # thread to enter concurrently and be caught by the counter above.
        time.sleep(0.01)
        return self

    def __exit__(self, exc_type, exc, tb):
        with self._guard:
            self._concurrent -= 1
        self._real.release()
        return False


class _FakeDB:
    def __init__(self):
        self.mapping_calls = []

    def set_lid_mapping(self, lid, phone):
        self.mapping_calls.append((lid, phone))

    def upsert_contacts_batch(self, contacts):
        pass


class _Stub:
    _extract_lid_mapping = MainWindow._extract_lid_mapping

    def __init__(self):
        self._ui_ready_event = threading.Event()
        self._ui_ready_event.set()
        self._chats_without_alt_jid = set()
        self._message_pushname_cache = {}
        self._lid_to_phone = {}
        self._phone_to_lid = {}
        self.contacts = {}
        self.db = _FakeDB()
        self._lid_mapping_lock = _TrackingLock()

    def _is_self_jid(self, jid):
        return False

    def _schedule_set_chats(self):
        pass


def _msg(i):
    lid = f"{1000 + i}@lid"
    phone = f"{2000 + i}@s.whatsapp.net"
    return {
        "key": {
            "remoteJid": lid,
            "remoteJidAlt": phone,
            "fromMe": True,  # skips the sender/mention resolution tail —
                              # irrelevant to the mapping caches under test
        },
        "messageType": "conversation",
        "pushName": f"Contact {i}",
    }


@pytest.fixture(autouse=True)
def _no_real_wx_callafter(monkeypatch):
    monkeypatch.setattr(main.wx, "CallAfter", lambda fn, *a, **kw: None)


class TestConcurrentCallsAreSerialized:
    def test_the_lock_actually_serializes_callers(self):
        """The regression this guards against: two threads racing the same
        critical section undetected. A tracking lock proves mutual
        exclusion directly, rather than hoping a real data race shows up
        under GIL timing (which the check-then-set pattern here would not
        reliably do even when genuinely unprotected)."""
        stub = _Stub()
        threads = [threading.Thread(target=stub._extract_lid_mapping, args=(_msg(i),))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert stub._lid_mapping_lock.enters == 20
        assert stub._lid_mapping_lock.max_concurrent == 1, (
            "more than one thread was inside the critical section at once — "
            "the lock is not actually serializing _extract_lid_mapping()"
        )

    def test_no_pair_is_lost_under_concurrency(self):
        stub = _Stub()
        threads = [threading.Thread(target=stub._extract_lid_mapping, args=(_msg(i),))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(stub._lid_to_phone) == 20
        assert len(stub._phone_to_lid) == 20
        for i in range(20):
            assert stub._lid_to_phone[f"{1000 + i}@lid"] == f"{2000 + i}@s.whatsapp.net"

    def test_no_exception_escapes_any_thread(self):
        stub = _Stub()
        errors = []

        def _run(i):
            try:
                stub._extract_lid_mapping(_msg(i))
            except Exception as exc:  # pragma: no cover - failure path only
                errors.append(exc)

        threads = [threading.Thread(target=_run, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert errors == []


class TestSingleCallStillWorksNormally:
    def test_a_lone_call_records_the_mapping(self):
        stub = _Stub()

        stub._extract_lid_mapping(_msg(0))

        assert stub._lid_to_phone == {"1000@lid": "2000@s.whatsapp.net"}
        assert stub._phone_to_lid == {"2000@s.whatsapp.net": "1000@lid"}
        assert stub.db.mapping_calls == [("1000@lid", "2000@s.whatsapp.net")]

    def test_an_unchanged_repeat_call_does_not_write_the_db_again(self):
        stub = _Stub()
        stub._extract_lid_mapping(_msg(0))

        stub._extract_lid_mapping(_msg(0))

        assert stub.db.mapping_calls == [("1000@lid", "2000@s.whatsapp.net")]


class TestTheLockIsWiredUpStructurally:
    """inspect.getsource pins that both mutators actually use the lock —
    same style as test_lid_merge_keeps_messages.py's own structural test for
    a method too large to exercise every branch of directly."""

    def test_extract_lid_mapping_uses_the_lock(self):
        src = inspect.getsource(MainWindow._extract_lid_mapping)
        assert "with self._lid_mapping_lock:" in src

    def test_build_lid_to_phone_cache_uses_the_lock(self):
        src = inspect.getsource(MainWindow._build_lid_to_phone_cache)
        assert "with self._lid_mapping_lock:" in src

    def test_the_lock_is_reentrant(self):
        """RLock, not Lock — _extract_lid_mapping calling other self methods
        while already inside the critical section must not be a deadlock
        trap for whoever touches this next."""
        src = inspect.getsource(MainWindow.__init__)
        assert "_lid_mapping_lock = threading.RLock()" in src
