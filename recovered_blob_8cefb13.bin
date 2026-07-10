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
- Clean async code inside DatabaseManager / MigrationEngine.
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
from core.migration import MigrationEngine

log = logging.getLogger(__name__)

_DEFAULT_DAT_PATH = "messages.dat"
_DEFAULT_DB_PATH = "messages.db"


class DatabaseBridge:
    """Synchronous wrapper around the async DatabaseManager.

    Parameters
    ----------
    db_path : str
        Path to the SQLite database file.
    key : bytes
        Fernet symmetric key.
    dat_path : str | None
        Path to the legacy ``messages.dat`` (for migration).  Defaults to
        the same directory as *db_path* with extension ``.dat``.
    """

    def __init__(
        self,
        db_path: str,
        key: bytes,
        dat_path: str | None = None,
    ):
        self._db_path = Path(db_path)
        self._dat_path = Path(dat_path) if dat_path else self._db_path.with_suffix(".dat")
        self._key = key

        # Start background event loop
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="db-asyncio"
        )
        self._thread.start()

        # Create DatabaseManager on the event loop thread
        self._db: DatabaseManager = self._call(
            self._create_db()
        )

    # ── Loop management ──────────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Target for the background daemon thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coro) -> Any:
        """Schedule *coro* on the event loop and block until done.

        Re-raises any exception the coroutine raised.
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()

    async def _create_db(self) -> DatabaseManager:
        """Factory: connect a new DatabaseManager on the event loop."""
        db = DatabaseManager(str(self._db_path), self._key)
        await db.connect()
        return db

    def close(self) -> None:
        """Shut down the event loop and release the database."""
        try:
            self._call(self._db.close())
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        self._thread.join(timeout=2)

    # ── Full-state save (replacement for save_data) ───────────────────────────

    def save_full_state(self, data: dict[str, Any], clear_first: bool = True) -> None:
        """Replace all data in the database with the given dict.

        This is the SQLite equivalent of the old ``save_data()`` which
        writes the entire ``messages.dat`` blob.  It clears all tables
        then re-imports everything within a single transaction.
        """
        self._call(self._db.import_from_dict(data, clear_first=clear_first))

    def clear_all(self) -> None:
        """Delete all records from every table."""
        self._call(self._db.clear_all())

    # ── Migration ─────────────────────────────────────────────────────────────

    def run_migration(self) -> bool:
        """Run migration from messages.dat → SQLite if needed.

        Returns ``True`` if a migration was performed, ``False`` otherwise.
        """
        return self._call(self._run_migration_async())

    async def _run_migration_async(self) -> bool:
        engine = MigrationEngine(
            str(self._dat_path), str(self._db_path), self._key
        )
        if not await engine.needs_migration():
            return False
        count = await engine.migrate()
        migrated = count > 0
        log.info("Migration: %d records imported", count)
        return migrated

    # ── Delegated read methods ────────────────────────────────────────────────

    def get_chats(self) -> dict[str, dict]:
        return self._call(self._db.get_chats())

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
        return self._call(self._db.upsert_chats_batch(chats))

    def insert_message(self, remote_jid: str, msg: dict) -> None:
        return self._call(self._db.insert_message(remote_jid, msg))

    def insert_messages_batch(
        self, remote_jid: str, msgs: list[dict]
    ) -> None:
        return self._call(
            self._db.insert_messages_batch(remote_jid, msgs)
        )

    def update_message_status(
        self, remote_jid: str, message_id: str, status: int
    ) -> None:
        return self._call(
            self._db.update_message_status(remote_jid, message_id, status)
        )

    def delete_chat(self, jid: str) -> None:
        return self._call(self._db.delete_chat(jid))

    def has_message(self, remote_jid: str, message_id: str) -> bool:
        return self._call(self._db.has_message(remote_jid, message_id))

    def delete_message(self, remote_jid: str, message_id: str) -> None:
        return self._call(self._db.delete_message(remote_jid, message_id))

    def delete_chat_messages(self, remote_jid: str) -> None:
        return self._call(self._db.delete_chat_messages(remote_jid))

    def upsert_contact(self, jid: str, data: dict) -> None:
        return self._call(self._db.upsert_contact(jid, data))

    def upsert_contacts_batch(self, contacts: dict[str, dict]) -> None:
        return self._call(self._db.upsert_contacts_batch(contacts))

    def set_lid_mapping(self, lid_jid: str, phone_jid: str) -> None:
        return self._call(self._db.set_lid_mapping(lid_jid, phone_jid))

    def add_unresolvable_lid(self, jid: str) -> None:
        return self._call(self._db.add_unresolvable_lid(jid))

    def add_unresolvable_name(self, jid: str) -> None:
        return self._call(self._db.add_unresolvable_name(jid))

    def upsert_status_update(self, participant: str, msg: dict) -> None:
        return self._call(
            self._db.upsert_status_update(participant, msg)
        )
