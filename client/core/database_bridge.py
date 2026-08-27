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
        # Tracks calls currently waiting on the event loop, so close() can
        # give them a moment to finish instead of yanking the loop out from
        # under them (which would otherwise strand their future forever).
        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self._inflight_drained = threading.Event()
        self._inflight_drained.set()

        # Start background event loop
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="db-asyncio"
        )
        self._thread.start()

        # Create DatabaseManager on the event loop thread
        self._db: DatabaseManager = self._call(
            self._create_db(), timeout=_DEFAULT_CALL_TIMEOUT
        )

    # ── Loop management ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Target for the background daemon thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro, timeout: float = _DEFAULT_CALL_TIMEOUT) -> Any:
        """Schedule *coro* on the event loop and block until done, or timeout.

        Re-raises any exception the coroutine raised. Raises
        ``DatabaseBridgeClosed`` immediately if ``close()`` has already been
        called, and ``DatabaseBridgeTimeout`` if the loop does not answer
        within *timeout* seconds — either of which the caller can catch,
        instead of the whole app (often the wx UI thread) hanging forever.
        """
        if self._closing:
            coro.close()  # avoid a "coroutine was never awaited" warning
            raise DatabaseBridgeClosed("DatabaseBridge is closing")
        return self._call_unchecked(coro, timeout)

    def _call_unchecked(self, coro, timeout: float = _DEFAULT_CALL_TIMEOUT) -> Any:
        """Like ``_call`` but skips the ``_closing`` gate.

        Used only by ``close()`` itself, whose own DB-close call must run even
        though it has already flipped ``_closing`` to True.
        """
        if not self._thread.is_alive():
            coro.close()
            raise DatabaseBridgeTimeout(
                "db-asyncio thread is not running; cannot execute query"
            )

        with self._inflight_lock:
            self._inflight += 1
            self._inflight_drained.clear()
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            try:
                return future.result(timeout=timeout)
            except asyncio.TimeoutError as exc:
                log.error(
                    "[DatabaseBridge] Call timed out after %.0fs (coroutine may "
                    "still complete in the background): %s",
                    timeout, coro,
                )
                raise DatabaseBridgeTimeout(
                    f"Database call timed out after {timeout:.0f}s"
                ) from exc
        finally:
            with self._inflight_lock:
                self._inflight -= 1
                if self._inflight <= 0:
                    self._inflight_drained.set()

    async def _create_db(self) -> DatabaseManager:
        """Factory: connect a new DatabaseManager on the event loop."""
        db = DatabaseManager(str(self._db_path), self._key)
        await db.connect()
        return db

    def close(self) -> None:
        """Shut down the event loop and release the database.

        Rejects any new call the moment this starts (``_closing`` is checked
        before ``_call`` ever touches the loop), then waits briefly for calls
        already in flight to finish on their own before stopping the loop —
        stopping it out from under a pending call would otherwise leave that
        caller's ``future.result()`` blocked forever with nothing left to ever
        resolve it.
        """
        with self._close_lock:
            if self._closing:
                return
            self._closing = True

        # Give in-flight calls a chance to finish normally.
        self._inflight_drained.wait(timeout=5)

        try:
            # Bypasses the _closing gate in _call() — that gate exists to
            # reject callers *other than* close() itself, which must still be
            # able to run this one shutdown call after setting it.
            self._call_unchecked(self._db.close(), timeout=5)
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
            timeout=_BULK_CALL_TIMEOUT,
        )

    def clear_all(self) -> None:
        """Delete all records from every table."""
        self._call(self._db.clear_all(), timeout=_BULK_CALL_TIMEOUT)

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
        return self._call(self._db.upsert_chats_batch(chats), timeout=_BULK_CALL_TIMEOUT)

    def insert_message(self, remote_jid: str, msg: dict) -> None:
        return self._call(self._db.insert_message(remote_jid, msg))

    def insert_messages_batch(
        self, remote_jid: str, msgs: list[dict]
    ) -> None:
        return self._call(
            self._db.insert_messages_batch(remote_jid, msgs),
            timeout=_BULK_CALL_TIMEOUT,
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

    def delete_message(self, remote_jid: str, message_id: str) -> None:
        return self._call(self._db.delete_message(remote_jid, message_id))

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

    def delete_unresolvable_lid(self, jid: str) -> None:
        return self._call(self._db.delete_unresolvable_lid(jid))

    def delete_unresolvable_name(self, jid: str) -> None:
        return self._call(self._db.delete_unresolvable_name(jid))

    def delete_expired_unresolvable(self, cutoff_ts: int) -> int:
        return self._call(self._db.delete_expired_unresolvable(cutoff_ts))

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
        self._call(self._db.vacuum(), timeout=_BULK_CALL_TIMEOUT)

    # ── Metadata ──────────────────────────────────────────────────────────────

    def get_metadata(self, key: str, default: str | None = None) -> str | None:
        return self._call(self._db.get_metadata(key, default))

    def set_metadata(self, key: str, value: str) -> None:
        return self._call(self._db.set_metadata(key, value))

    def get_metadata_json(self, key: str, default: Any = None) -> Any:
        return self._call(self._db.get_metadata_json(key, default))

    def set_metadata_json(self, key: str, value: Any) -> None:
        return self._call(self._db.set_metadata_json(key, value))

