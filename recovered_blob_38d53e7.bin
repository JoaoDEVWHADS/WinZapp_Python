"""
WinZapp Data Migration  (async version)
----------------------------------------
Reads the legacy encrypted JSON (``messages.dat``), populates a SQLite
database via :class:`DatabaseManager`, then renames ``messages.dat`` to
``messages.dat.bak`` so the app seamlessly transitions to the new backend.

Design principles
^^^^^^^^^^^^^^^^^
* **Data-first**: the original file is only renamed *after* a successful
  import and validation; any failure preserves the original.
* **Reversible**: ``rollback()`` restores ``messages.dat.bak`` and removes
  the SQLite database, so the app can fall back to file-based storage.
* **Idempotent**: ``needs_migration()`` returns ``False`` if the target DB
  already contains data (so restarting a partially migrated app does not
  double-import).

Concurrency notes
^^^^^^^^^^^^^^^^^
* Blocking file I/O (``read_bytes``, ``rename``, ``unlink``) is offloaded
  to ``anyio.to_thread.run_sync`` so the event loop is never blocked.
* Database operations use the async ``DatabaseManager`` directly.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import anyio

from core.database import DatabaseManager
from core.utils import decrypt_json

log = logging.getLogger(__name__)

_BACKUP_SUFFIX = ".bak"


class MigrationEngine:
    """Coordinate migration from ``messages.dat`` to SQLite.

    Parameters
    ----------
    messages_dat_path : str
        Full path to the existing ``messages.dat``.
    db_path : str
        Full path to the target SQLite database file (e.g. ``messages.db``).
    key : bytes
        Fernet symmetric key (from ``secret.key``).
    """

    def __init__(
        self,
        messages_dat_path: str,
        db_path: str,
        key: bytes,
    ):
        self._dat_path = Path(messages_dat_path)
        self._bak_path = self._dat_path.with_suffix(
            self._dat_path.suffix + _BACKUP_SUFFIX
        )
        self._db_path = Path(db_path)
        self._key = key

    # ── Blocking I/O helpers (run in thread pool) ─────────────────────────────

    async def _read_bytes(self, path: Path) -> bytes:
        """Read file bytes without blocking the event loop."""
        return await anyio.to_thread.run_sync(path.read_bytes)

    async def _path_exists(self, path: Path) -> bool:
        """Check file existence without blocking."""
        return await anyio.to_thread.run_sync(path.is_file)

    async def _rename(self, src: Path, dst: Path) -> None:
        """Rename a file without blocking."""
        await anyio.to_thread.run_sync(src.rename, dst)

    async def _unlink(self, path: Path) -> None:
        """Delete a file without blocking."""
        await anyio.to_thread.run_sync(path.unlink)

    async def _move(self, src: Path, dst: Path) -> None:
        """Move a file without blocking."""
        await anyio.to_thread.run_sync(shutil.move, str(src), str(dst))

    async def _remove_wal_files(self) -> None:
        """Remove WAL / SHM sidecar files if present."""
        for suffix in ("-wal", "-shm"):
            extra = self._db_path.with_suffix(self._db_path.suffix + suffix)
            if await self._path_exists(extra):
                try:
                    await self._unlink(extra)
                except OSError:
                    pass

    # ── Public API ─────────────────────────────────────────────────────────────

    async def needs_migration(self) -> bool:
        """Return ``True`` if a migration should run.

        Criteria (all must be true):
        1. ``messages.dat`` exists.
        2. ``messages.dat.bak`` does **not** exist (otherwise the migration
           already completed successfully).
        3. The SQLite database does **not** contain any chats yet.
        """
        if not await self._path_exists(self._dat_path):
            return False
        if await self._path_exists(self._bak_path):
            return False

        # Check if the target DB already has data
        if await self._path_exists(self._db_path):
            try:
                async with DatabaseManager(
                    str(self._db_path), self._key
                ) as db:
                    chats = await db.get_chats()
                    if chats:
                        return False  # DB already populated
            except Exception:
                pass  # Corrupted / unreadable DB → re-migrate

        return True

    async def migrate(self) -> int:
        """Execute the migration.

        Steps
        -----
        1. Read and decrypt ``messages.dat``.
        2. Import all data into the SQLite database via
           :meth:`DatabaseManager.import_from_dict`.
        3. Validate that the DB contents match the original file.
        4. Rename ``messages.dat`` → ``messages.dat.bak``.

        Returns
        -------
        int
            Number of records imported.

        Raises
        ------
        FileNotFoundError
            ``messages.dat`` does not exist.
        Exception
            Any failure during decryption, import, or validation.
            The original ``messages.dat`` is **never** removed on failure.
        """
        if not await self._path_exists(self._dat_path):
            raise FileNotFoundError(
                f"Cannot migrate: {self._dat_path} does not exist"
            )

        log.info(
            "Starting migration from %s to %s", self._dat_path, self._db_path
        )

        # 1. Read and decrypt
        try:
            encrypted = await self._read_bytes(self._dat_path)
            if not encrypted:
                raise ValueError(f"{self._dat_path} is empty")
            data: dict[str, Any] = decrypt_json(encrypted, self._key)
        except Exception as exc:
            raise type(exc)(
                f"Migration failed: could not decrypt "
                f"{self._dat_path}: {exc}"
            ) from exc

        # 2. Open DB and import
        async with DatabaseManager(str(self._db_path), self._key) as db:
            try:
                total = await db.import_from_dict(data)
                log.info(
                    "Imported %d records into %s", total, self._db_path
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Migration failed during SQLite import: {exc}"
                ) from exc

            # 3. Validate
            try:
                diffs = await self._validate_internal(db, data)
                if diffs:
                    raise ValueError(
                        f"Migration validation failed "
                        f"({len(diffs)} difference(s)):\n"
                        + "\n".join(diffs[:10])
                    )
            except ValueError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"Migration failed during validation: {exc}"
                ) from exc

            # 4. Rename original file (only now — data is safe in DB)
            try:
                await self._rename(self._dat_path, self._bak_path)
                log.info(
                    "Renamed %s → %s", self._dat_path, self._bak_path
                )
            except OSError as exc:
                raise RuntimeError(
                    f"Migration succeeded but could not rename "
                    f"{self._dat_path}: {exc}"
                ) from exc

        log.info(
            "Migration completed successfully — %d records", total
        )
        return total

    async def rollback(self) -> bool:
        """Undo a migration.

        Steps
        -----
        1. If ``messages.dat.bak`` exists, restore it to ``messages.dat``.
        2. Remove the SQLite database file.

        Returns
        -------
        bool
            ``True`` if rollback was performed, ``False`` if nothing to roll back.
        """
        performed = False
        if await self._path_exists(self._bak_path):
            await self._move(self._bak_path, self._dat_path)
            log.info(
                "Rolled back %s → %s", self._bak_path, self._dat_path
            )
            performed = True

        if await self._path_exists(self._db_path):
            try:
                await self._unlink(self._db_path)
                log.info("Removed database %s", self._db_path)
                performed = True
            except OSError:
                log.warning("Could not remove %s", self._db_path)

        await self._remove_wal_files()

        return performed

    async def validate(self) -> list[str]:
        """Compare the SQLite database against the backup file.

        Returns
        -------
        list[str]
            A list of human-readable differences.  An empty list means the
            data is identical (migration was correct).
        """
        if not await self._path_exists(self._db_path):
            return ["Database file does not exist"]
        if not await self._path_exists(self._bak_path):
            return [
                "Backup file (messages.dat.bak) does not exist "
                "— cannot validate"
            ]

        try:
            encrypted = await self._read_bytes(self._bak_path)
            orig: dict[str, Any] = decrypt_json(encrypted, self._key)
        except Exception as exc:
            return [f"Failed to read backup: {exc}"]

        async with DatabaseManager(
            str(self._db_path), self._key
        ) as db:
            return await self._validate_internal(db, orig)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _validate_internal(
        self, db: DatabaseManager, orig: dict[str, Any]
    ) -> list[str]:
        """Compare DB contents against the original data dict.

        Returns a list of discrepancy descriptions (empty = no differences).
        """
        diffs: list[str] = []

        # Chats
        db_chats = await db.get_chats()
        orig_chats = orig.get("chats", {})
        missing = set(orig_chats.keys()) - set(db_chats.keys())
        extra = set(db_chats.keys()) - set(orig_chats.keys())
        if missing:
            diffs.append(f"Chats missing in DB: {missing}")
        if extra:
            diffs.append(f"Extra chats in DB: {extra}")

        # Contacts
        db_contacts = await db.get_contacts()
        orig_contacts = orig.get("contacts", {})
        missing_c = set(orig_contacts.keys()) - set(db_contacts.keys())
        extra_c = set(db_contacts.keys()) - set(orig_contacts.keys())
        if missing_c:
            diffs.append(f"Contacts missing in DB: {missing_c}")
        if extra_c:
            diffs.append(f"Extra contacts in DB: {extra_c}")

        # LID mappings
        db_lids = await db.get_lid_mappings()
        orig_lids = orig.get("lid_to_phone", {})
        if db_lids != orig_lids:
            diffs.append(
                f"LID mappings differ "
                f"({len(db_lids)} vs {len(orig_lids)})"
            )

        # Unresolvable LIDs
        db_lids_set, db_names_set = await db.get_unresolvable_lids()
        orig_lids_set = set(orig.get("unresolvable_lids", []))
        orig_names_set = set(orig.get("unresolvable_names", []))
        if db_lids_set != orig_lids_set:
            diffs.append(
                f"Unresolvable LIDs differ "
                f"({len(db_lids_set)} vs {len(orig_lids_set)})"
            )
        if db_names_set != orig_names_set:
            diffs.append(
                f"Unresolvable names differ "
                f"({len(db_names_set)} vs {len(orig_names_set)})"
            )

        # Status updates (compare participants at minimum)
        db_status = await db.get_status_updates()
        orig_status = orig.get("status_updates", {})
        if set(db_status.keys()) != set(orig_status.keys()):
            diffs.append(
                f"Status participants differ "
                f"({len(db_status)} vs {len(orig_status)})"
            )

        return diffs
