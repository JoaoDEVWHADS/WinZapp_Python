"""
DatabaseBridge
==============
Synchronous bridge from wxPython (main thread / background threads) to the
async :class:`DatabaseManager`.

Design
------
A dedicated asyncio event loop runs in a background daemon thread.  Every
DatabaseManager call is dispatched to that loop via
``asyncio.run_coroutine_threadsafe()`` and blocked on from the caller's
thread.  This gives us:

- A single serialised SQLite connection (no thread-safety hacks).
- Clean async code inside DatabaseManager.
- Transparent sync wrappers for existing wxPython code.

Usage
-----
.. code-block:: python

    bridge = DatabaseBridge("messages.db", fernet_key)
    chats = bridge.get_chats()
    bridge.save_full_state(data)
    bridge.close()
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import itertools
import logging
import threading
from pathlib import Path
from typing import Any

from core.database import DatabaseManager

log = logging.getLogger(__name__)

_DEFAULT_DB_PATH = "messages.db"

# Every synchronous DB call from wx (frequently the UI thread itself) blocks on
# this for as long as the coroutine takes.  Without a bound, a stuck coroutine
# (event-loop thread died, a write wedged behind SQLite's busy_timeout, a
# close() racing an in-flight call — see below) froze the whole app forever,
# with no way to recover short of killing the process. This is the single
# most commonly reported "WinZapp parou de responder" symptom. A bounded wait
# turns that into a logged, recoverable error instead.
_DEFAULT_CALL_TIMEOUT = 20.0
# Bulk operations (a full save_full_state/import over a large account) can
# legitimately take longer than a single read/write; give them more rope
# before giving up.
_BULK_CALL_TIMEOUT = 120.0

# Bridge-level scheduling priorities. The old bridge submitted every coroutine
# straight to the asyncio/aiosqlite queues, so an interactive read could land
# behind a large backlog created by sync/backfill workers. Keeping one small
# priority queue in front of the DB gives UI work precedence without opening a
# second SQLite connection or weakening the single-writer guarantees.
_PRIORITY_UI = 0
_PRIORITY_NORMAL = 10
_PRIORITY_BULK = 20


class DatabaseBridgeClosed(RuntimeError):
    """Raised when a call is made after close() has started."""


class DatabaseBridgeTimeout(RuntimeError):
    """Raised when a database call does not complete within its timeout.

    This does NOT mean the underlying operation failed or was rolled back —
    only that the calling thread stopped waiting for it. The operation may
    still complete on the event-loop thread afterwards.
    """


class DatabaseBridge:
    """Synchronous wrapper around the async DatabaseManager.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.
    key : bytes
        Fernet symmetric key.
    """

    def __init__(self, db_path: str, key: bytes):
        self._db_path = Path(db_path)
        self._key = key
        self._closing = False
        self._close_lock = threading.Lock()
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._inflight_drained = threading.Event()
        self._inflight_drained.set()
        self._request_seq = itertools.count()
        self._scheduler_ready = threading.Event()
        self._request_queue = None

        # Start the asyncio loop, then a single priority scheduler on that loop.
        # DatabaseManager still owns exactly one aiosqlite connection; the
        # scheduler merely controls which bridge request is allowed to reach it
        # next. This prevents hundreds of sync writes from being pre-enqueued
        # ahead of an interactive read/write.
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="db-asyncio"
        )
        self._thread.start()
        self._scheduler_future = asyncio.run_coroutine_threadsafe(
            self._priority_worker(), self._loop
        )
        if not self._scheduler_ready.wait(timeout=5):
            raise DatabaseBridgeTimeout("database priority scheduler did not start")

        # Create DatabaseManager through the same scheduler so initialization
        # obeys the exact same lifecycle rules as every later request.
        self._db: DatabaseManager = self._call(
            self._create_db(), timeout=_DEFAULT_CALL_TIMEOUT, priority=_PRIORITY_UI
        )

    # ── Loop management ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Target for the background daemon thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _priority_worker(self) -> None:
        """Run bridge requests one-at-a-time, smallest priority first.

        Serialising here is intentional: aiosqlite ultimately owns one sqlite3
        connection/worker anyway. The difference is that requests have not yet
        been dumped into a FIFO we cannot reorder, so a UI request can jump in
        front of queued backfill writes.
        """
        self._request_queue = asyncio.PriorityQueue()
        self._scheduler_ready.set()
        while True:
            priority, seq, coro, result_future, allow_during_close = await self._request_queue.get()
            try:
                if coro is None:
                    return
                if self._closing and not allow_during_close:
                    try:
                        coro.close()
                    except Exception:
                        pass
                    if not result_future.done():
                        result_future.set_exception(
                            DatabaseBridgeClosed("DatabaseBridge is closing")
                        )
                    continue
                try:
                    result = await coro
                except asyncio.CancelledError:
                    if not result_future.done():
                        result_future.set_exception(
                            DatabaseBridgeClosed("DatabaseBridge scheduler stopped")
                        )
                    raise
                except BaseException as exc:
                    if not result_future.done():
                        result_future.set_exception(exc)
                else:
                    if not result_future.done():
                        result_future.set_result(result)
            finally:
                self._request_queue.task_done()
                if coro is not None:
                    with self._inflight_lock:
                        self._inflight -= 1
                        if self._inflight <= 0:
                            self._inflight_drained.set()

    @staticmethod
    def _default_priority() -> int:
        # wx's UI loop normally runs on Python's MainThread. Calls from there
        # are interactive even if a legacy site still uses a synchronous bridge
        # method; prioritising them limits the wait to the request currently in
        # progress rather than the entire sync backlog.
        return (
            _PRIORITY_UI
            if threading.current_thread() is threading.main_thread()
            else _PRIORITY_NORMAL
        )

    def _submit(self, coro, *, priority: int | None = None,
                allow_during_close: bool = False) -> concurrent.futures.Future:
        if self._closing and not allow_during_close:
            coro.close()
            raise DatabaseBridgeClosed("DatabaseBridge is closing")
        return self._submit_unchecked(
            coro, priority=priority, allow_during_close=allow_during_close
        )

    def _submit_unchecked(self, coro, *, priority: int | None = None,
                          allow_during_close: bool = False) -> concurrent.futures.Future:
        if not self._thread.is_alive() or self._request_queue is None:
            coro.close()
            raise DatabaseBridgeTimeout(
                "db-asyncio thread is not running; cannot execute query"
            )
        if priority is None:
            priority = self._default_priority()

        result_future: concurrent.futures.Future = concurrent.futures.Future()
        with self._inflight_lock:
            self._inflight += 1
            self._inflight_drained.clear()

        item = (
            int(priority), next(self._request_seq), coro, result_future,
            bool(allow_during_close),
        )
        try:
            self._loop.call_soon_threadsafe(self._request_queue.put_nowait, item)
        except Exception:
            with self._inflight_lock:
                self._inflight -= 1
                if self._inflight <= 0:
                    self._inflight_drained.set()
            coro.close()
            raise
        return result_future

    def _call(self, coro, timeout: float = _DEFAULT_CALL_TIMEOUT,
              priority: int | None = None) -> Any:
        """Queue *coro* and synchronously wait with a hard caller timeout.

        UI handlers that need a result should use the dedicated ``*_async``
        helpers below and marshal completion back with ``wx.CallAfter``. The
        synchronous facade remains for existing background/sync code and for
        compatibility, but now benefits from priority scheduling.
        """
        future = self._submit(coro, priority=priority)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            log.error(
                "[DatabaseBridge] Call timed out after %.0fs while queued/running: %s",
                timeout, coro,
            )
            raise DatabaseBridgeTimeout(
                f"Database call timed out after {timeout:.0f}s"
            ) from exc

    def _call_unchecked(self, coro, timeout: float = _DEFAULT_CALL_TIMEOUT,
                        priority: int | None = None) -> Any:
        """Like ``_call`` but permits the bridge's own shutdown request."""
        future = self._submit_unchecked(
            coro, priority=priority, allow_during_close=True
        )
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            log.error(
                "[DatabaseBridge] Shutdown DB call timed out after %.0fs: %s",
                timeout, coro,
            )
            raise DatabaseBridgeTimeout(
                f"Database call timed out after {timeout:.0f}s"
            ) from exc

    async def _create_db(self) -> DatabaseManager:
        """Factory: connect a new DatabaseManager on the event loop."""
        db = DatabaseManager(str(self._db_path), self._key)
        await db.connect()
        return db

    def close(self) -> None:
        """Shut down the scheduler, event loop and database safely."""
        with self._close_lock:
            if self._closing:
                return
            self._closing = True

        # Requests that were only queued are rejected by _priority_worker once
        # it reaches them; the request currently executing is allowed a brief
        # chance to finish, preserving the previous close-race guarantee.
        self._inflight_drained.wait(timeout=5)

        try:
            self._call_unchecked(
                self._db.close(), timeout=5, priority=-100
            )
        except Exception:
            pass

        # Stop the scheduler cleanly after the close request. The sentinel is
        # allowed during close and sorts behind the close operation only.
        try:
            sentinel_future = concurrent.futures.Future()
            self._loop.call_soon_threadsafe(
                self._request_queue.put_nowait,
                (1_000_000, next(self._request_seq), None, sentinel_future, True),
            )
            self._scheduler_future.result(timeout=2)
        except Exception:
            try:
                self._scheduler_future.cancel()
            except Exception:
                pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        self._thread.join(timeout=2)

    # ── Full-state save (replacement for save_data) ───────────────────────────

    def save_full_state(self, data: dict[str, Any], clear_first: bool = True,
                         clear_metadata: bool = True) -> None:
        """Replace all data in the database with the given dict.

        This is the SQLite equivalent of the old full-state rewrite: it
        clears all tables then re-imports everything within a single
        transaction. Uses the longer bulk timeout — a large account's full
        chat/message set can legitimately take longer than a routine call.

        clear_metadata=False preserves system_metadata (cleared_chats,
        deleted_chats, archived_chats, pinned_chats, muted_chats,
        blocked_contacts, ...) across the wipe — see
        DatabaseManager.import_from_dict()'s own docstring for when that
        matters (an F5 resync should not also discard those).
        """
        self._call(
            self._db.import_from_dict(data, clear_first=clear_first, clear_metadata=clear_metadata),
            timeout=_BULK_CALL_TIMEOUT, priority=_PRIORITY_BULK,
        )

    def clear_all(self) -> None:
        """Delete all records from every table."""
        self._call(self._db.clear_all(), timeout=_BULK_CALL_TIMEOUT, priority=_PRIORITY_BULK)

    # ── Delegated read methods ────────────────────────────────────────────────

    def get_chats(self, limit: int = 200) -> dict[str, dict]:
        return self._call(self._db.get_chats(limit), timeout=_BULK_CALL_TIMEOUT)

    def get_chat_jids(self) -> list[str]:
        return self._call(self._db.get_chat_jids())

    def get_message_count(self, remote_jid: str) -> int:
        return self._call(self._db.get_message_count(remote_jid))

    def get_messages(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        return self._call(self._db.get_messages(remote_jid, limit, offset))

    def get_messages_async(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> concurrent.futures.Future:
        """Priority message read for UI workers without blocking wx."""
        return self._submit(
            self._db.get_messages(remote_jid, limit, offset),
            priority=_PRIORITY_UI,
        )

    def get_message_count_async(
        self, remote_jid: str
    ) -> concurrent.futures.Future:
        """Priority count read paired with an interactive page load."""
        return self._submit(
            self._db.get_message_count(remote_jid),
            priority=_PRIORITY_UI,
        )

    def get_messages_page(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> tuple[list[dict], int]:
        return self._call(self._db.get_messages_page(remote_jid, limit, offset))

    def get_messages_page_async(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> concurrent.futures.Future:
        """Priority UI read that never blocks the wx caller."""
        return self._submit(
            self._db.get_messages_page(remote_jid, limit, offset),
            priority=_PRIORITY_UI,
        )

    def get_messages_asc(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        return self._call(
            self._db.get_messages_asc(remote_jid, limit, offset)
        )

    def get_contacts(self) -> dict[str, dict]:
        return self._call(self._db.get_contacts())

    def get_lid_mappings(self) -> dict[str, str]:
        return self._call(self._db.get_lid_mappings())

    def get_unresolvable_lids(self) -> tuple[set[str], set[str]]:
        return self._call(self._db.get_unresolvable_lids())

    def get_status_updates(self) -> dict[str, list[dict]]:
        return self._call(self._db.get_status_updates())

    def export_as_dict(self) -> dict[str, Any]:
        return self._call(self._db.export_as_dict())

    # ── Delegated write methods ───────────────────────────────────────────────

    def upsert_chat(self, jid: str, data: dict) -> None:
        return self._call(self._db.upsert_chat(jid, data))

    def upsert_chats_batch(self, chats: dict[str, dict]) -> None:
        return self._call(self._db.upsert_chats_batch(chats), timeout=_BULK_CALL_TIMEOUT, priority=_PRIORITY_BULK)

    def insert_message(self, remote_jid: str, msg: dict) -> None:
        return self._call(self._db.insert_message(remote_jid, msg))

    def insert_messages_batch(
        self, remote_jid: str, msgs: list[dict]
    ) -> None:
        return self._call(
            self._db.insert_messages_batch(remote_jid, msgs),
            timeout=_BULK_CALL_TIMEOUT, priority=_PRIORITY_BULK,
        )

    def update_message_status(
        self, remote_jid: str, message_id: str, status: int
    ) -> None:
        return self._call(
            self._db.update_message_status(remote_jid, message_id, status)
        )

    def update_message_id(
        self, remote_jid: str, old_id: str, new_id: str
    ) -> None:
        return self._call(
            self._db.update_message_id(remote_jid, old_id, new_id)
        )


    def delete_chat(self, jid: str) -> None:
        return self._call(self._db.delete_chat(jid))

    def delete_contact(self, jid: str) -> None:
        return self._call(self._db.delete_contact(jid))

    def merge_or_rename_chat(self, old_jid: str, new_jid: str) -> None:
        return self._call(self._db.merge_or_rename_chat(old_jid, new_jid))


    def has_message(self, remote_jid: str, message_id: str) -> bool:
        return self._call(self._db.has_message(remote_jid, message_id))

    def get_deleted_message_ids(self, remote_jid: str, message_ids) -> set[str]:
        return self._call(
            self._db.get_deleted_message_ids(remote_jid, list(message_ids or []))
        )

    def get_all_deleted_message_keys(self) -> list[tuple[str, str]]:
        return self._call(self._db.get_all_deleted_message_keys())

    def delete_message(self, remote_jid: str, message_id: str) -> None:
        return self._call(self._db.delete_message(remote_jid, message_id))

    def delete_messages_batch(self, remote_jid: str, message_ids) -> None:
        return self._call(
            self._db.delete_messages_batch(remote_jid, message_ids)
        )

    def delete_messages_batch_async(
        self, remote_jid: str, message_ids
    ) -> concurrent.futures.Future:
        """Priority batch delete for UI reconciliation; returns immediately."""
        ids = list(message_ids or [])
        return self._submit(
            self._db.delete_messages_batch(remote_jid, ids),
            priority=_PRIORITY_UI,
        )

    def delete_chat_messages(self, remote_jid: str) -> None:
        return self._call(self._db.delete_chat_messages(remote_jid))

    def delete_chat_messages_except(self, remote_jid: str, keep_message_ids) -> None:
        return self._call(self._db.delete_chat_messages_except(remote_jid, keep_message_ids))

    def upsert_contact(self, jid: str, data: dict) -> None:
        return self._call(self._db.upsert_contact(jid, data))

    def upsert_contacts_batch(self, contacts: dict[str, dict]) -> None:
        return self._call(self._db.upsert_contacts_batch(contacts))

    def set_lid_mapping(self, lid_jid: str, phone_jid: str) -> None:
        return self._call(self._db.set_lid_mapping(lid_jid, phone_jid))

    def delete_lid_mapping(self, lid_jid: str) -> None:
        return self._call(self._db.delete_lid_mapping(lid_jid))

    def add_unresolvable_lid(self, jid: str) -> None:
        return self._call(self._db.add_unresolvable_lid(jid))

    def add_unresolvable_name(self, jid: str) -> None:
        return self._call(self._db.add_unresolvable_name(jid))

    def upsert_status_update(self, participant: str, msg: dict) -> None:
        return self._call(
            self._db.upsert_status_update(participant, msg)
        )

    def delete_status_update(self, message_id: str) -> int:
        return self._call(self._db.delete_status_update(message_id))

    def delete_expired_status_updates(self, cutoff_ts: int) -> int:
        return self._call(self._db.delete_expired_status_updates(cutoff_ts))

    def vacuum(self) -> None:
        """Reclaim disk space freed by deletes. Slow on a large DB — call
        rarely, from a background thread, never from the wx UI thread."""
        self._call(self._db.vacuum(), timeout=_BULK_CALL_TIMEOUT, priority=_PRIORITY_BULK)

    # ── Metadata ──────────────────────────────────────────────────────────────

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        return self._call(self._db.get_metadata(key, default))

    def set_metadata(self, key: str, value: str) -> None:
        return self._call(self._db.set_metadata(key, value))

    def get_metadata_json(self, key: str, default: Any = None) -> Any:
        return self._call(self._db.get_metadata_json(key, default))

    def set_metadata_json(self, key: str, value: Any) -> None:
        return self._call(self._db.set_metadata_json(key, value))

    def set_metadata_json_async(self, key: str, value: Any) -> concurrent.futures.Future:
        """Priority metadata write that never blocks the wx caller."""
        return self._submit(
            self._db.set_metadata_json(key, value), priority=_PRIORITY_UI
        )

