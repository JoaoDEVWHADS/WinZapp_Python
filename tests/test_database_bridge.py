"""Tests for core.database_bridge.DatabaseBridge.

DatabaseBridge is the sync facade main.py actually calls: it runs a
background asyncio event loop in its own thread and blocks the calling
thread (often the wx UI thread) on every call. Before this session it had no
timeout at all, so a stuck coroutine froze the entire app forever — the most
commonly reported "WinZapp parou de responder" symptom. These tests cover the
timeout and the close()-race-safety this session added, using the real
background-thread bridge (not mocked) against a temporary on-disk database.
"""

import asyncio
import time

import pytest
from cryptography.fernet import Fernet

from core.database_bridge import (
    DatabaseBridge,
    DatabaseBridgeClosed,
    DatabaseBridgeTimeout,
)


@pytest.fixture
def bridge(tmp_path):
    db_path = str(tmp_path / "test.db")
    key = Fernet.generate_key()
    b = DatabaseBridge(db_path, key)
    yield b
    try:
        b.close()
    except Exception:
        pass


class TestNormalOperation:
    def test_basic_call_round_trips(self, bridge):
        bridge.upsert_chat("jid@w", {"remoteJid": "jid@w", "pushName": "Foo"})
        chats = bridge.get_chats()
        assert chats["jid@w"]["pushName"] == "Foo"

    def test_get_chats_default_limit_matches_page_size(self, bridge):
        """Same regression this session fixed at the DatabaseManager level:
        the bridge's own default used to be 5 too."""
        bridge.upsert_chat("jid@w", {"remoteJid": "jid@w"})
        for i in range(12):
            bridge.insert_message("jid@w", {
                "key": {"remoteJid": "jid@w", "id": f"m{i}"},
                "messageTimestamp": i,
            })
        chats = bridge.get_chats()
        assert len(chats["jid@w"]["messages"]["messages"]["records"]) == 12


class TestTimeout:
    def test_slow_coroutine_raises_timeout_instead_of_hanging(self, bridge):
        start = time.monotonic()
        with pytest.raises(DatabaseBridgeTimeout):
            bridge._call(asyncio.sleep(0.6), timeout=0.2)
        elapsed = time.monotonic() - start
        # The whole point of the fix: the caller gets control back close to
        # the timeout, not after the full duration the coroutine sleeps.
        assert elapsed < 0.5

    def test_bridge_stays_usable_after_a_timeout(self, bridge):
        """A timed-out call must not corrupt the bridge/loop for later calls
        — the underlying coroutine finishing late on the loop thread is
        expected and must not affect anything after it."""
        with pytest.raises(DatabaseBridgeTimeout):
            bridge._call(asyncio.sleep(0.3), timeout=0.1)
        bridge.upsert_chat("jid@w", {"remoteJid": "jid@w", "pushName": "StillWorks"})
        chats = bridge.get_chats()
        assert chats["jid@w"]["pushName"] == "StillWorks"


class TestClose:
    def test_calls_after_close_raise_immediately(self, bridge):
        bridge.close()
        with pytest.raises(DatabaseBridgeClosed):
            bridge.get_chats()

    def test_close_is_idempotent(self, bridge):
        bridge.close()
        bridge.close()  # must not raise

    def test_close_waits_for_in_flight_call_instead_of_stranding_it(self, tmp_path):
        """A call already running when close() starts must still be allowed
        to finish (close() drains briefly) rather than the loop being pulled
        out from under it, which would otherwise leave that caller's
        future.result() blocked forever with nothing left to resolve it."""
        import threading

        db_path = str(tmp_path / "test2.db")
        b = DatabaseBridge(db_path, Fernet.generate_key())
        result = {}

        def slow_call():
            try:
                result["value"] = b._call(asyncio.sleep(0.3, result=42), timeout=5)
            except Exception as exc:
                result["error"] = exc

        t = threading.Thread(target=slow_call)
        t.start()
        time.sleep(0.05)  # let slow_call actually start before closing
        b.close()
        t.join(timeout=5)

        assert result.get("value") == 42
        assert "error" not in result
