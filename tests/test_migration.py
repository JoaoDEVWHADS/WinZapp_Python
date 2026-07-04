"""Tests for core.migration.MigrationEngine — async edition."""

import json
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from core.utils import encrypt_json


# =============================================================================
#  needs_migration
# =============================================================================


class TestNeedsMigration:
    async def test_true_when_messages_dat_exists_and_db_empty(
        self, tmp_path, fernet_key, sample_data
    ):
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db), fernet_key)
        result = await engine.needs_migration()
        assert result

    async def test_false_when_messages_dat_missing(self, tmp_path, fernet_key):
        dat = tmp_path / "messages.dat"
        db = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db), fernet_key)
        result = await engine.needs_migration()
        assert not result

    async def test_false_when_bak_exists(self, tmp_path, fernet_key, sample_data):
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        bak = tmp_path / "messages.dat.bak"
        bak.write_text("already migrated")
        db = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db), fernet_key)
        result = await engine.needs_migration()
        assert not result

    async def test_false_when_db_has_data(self, tmp_path, fernet_key, sample_data):
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.database import DatabaseManager

        async with DatabaseManager(str(db_path), fernet_key) as db:
            await db.import_from_dict(sample_data)

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        result = await engine.needs_migration()
        assert not result

    async def test_true_when_messages_dat_is_empty(self, tmp_path, fernet_key):
        """Empty structure = treat as needing migration (has keys to migrate)."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(
            encrypt_json(
                {
                    "chats": {},
                    "contacts": {},
                    "lid_to_phone": {},
                    "status_updates": {},
                    "unresolvable_lids": [],
                    "unresolvable_names": [],
                },
                fernet_key,
            )
        )
        db = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db), fernet_key)
        result = await engine.needs_migration()
        assert result


# =============================================================================
#  migrate
# =============================================================================


class TestMigrate:
    async def test_migrate_basic(self, tmp_path, fernet_key, sample_data):
        """Basic end-to-end migration."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        count = await engine.migrate()
        assert count > 0

        # Original file renamed
        assert not dat.exists()
        assert (tmp_path / "messages.dat.bak").exists()

        # DB has data
        from core.database import DatabaseManager

        async with DatabaseManager(str(db_path), fernet_key) as db:
            chats = await db.get_chats()
            assert set(chats.keys()) == set(sample_data["chats"].keys())
            contacts = await db.get_contacts()
            assert set(contacts.keys()) == set(sample_data["contacts"].keys())

    async def test_migrate_empty_data(self, tmp_path, fernet_key):
        """Migrate a messages.dat with no actual records."""
        empty = {
            "chats": {},
            "contacts": {},
            "lid_to_phone": {},
            "status_updates": {},
            "unresolvable_lids": [],
            "unresolvable_names": [],
        }
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(empty, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        count = await engine.migrate()
        assert count == 0

    async def test_migrate_raises_if_messages_dat_missing(
        self, tmp_path, fernet_key
    ):
        """Calling migrate() without a source file must raise."""
        dat = tmp_path / "messages.dat"
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        with pytest.raises(FileNotFoundError):
            await engine.migrate()

    async def test_migrate_raises_on_corrupted_data(
        self, tmp_path, fernet_key
    ):
        """Corrupted messages.dat must raise and NOT rename the original."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(b"this is not valid fernet data")
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        with pytest.raises(Exception, match="Migration failed"):
            await engine.migrate()
        # Original must be preserved
        assert dat.exists()
        assert not (tmp_path / "messages.dat.bak").exists()

    async def test_migrate_preserves_message_content(
        self, tmp_path, fernet_key, sample_data
    ):
        """Message text must survive migration intact."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()

        # Read back from DB and verify content
        from core.database import DatabaseManager

        async with DatabaseManager(str(db_path), fernet_key) as db:
            for jid, orig_chat in sample_data["chats"].items():
                orig_records = (
                    orig_chat.get("messages", {})
                    .get("messages", {})
                    .get("records", [])
                )
                if orig_records:
                    db_records = await db.get_messages(jid)
                    assert len(db_records) == len(orig_records)
                    for orig_msg, db_msg in zip(orig_records, db_records):
                        assert orig_msg["key"]["id"] == db_msg["key"]["id"]


# =============================================================================
#  rollback
# =============================================================================


class TestRollback:
    async def test_rollback_restores_messages_dat(
        self, tmp_path, fernet_key, sample_data
    ):
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()

        assert await engine.rollback()
        assert dat.exists()
        assert not (tmp_path / "messages.dat.bak").exists()
        assert not db_path.exists()

    async def test_rollback_when_no_bak_exists(self, tmp_path, fernet_key):
        """rollback() should return False if there's nothing to do."""
        from core.migration import MigrationEngine

        engine = MigrationEngine(
            str(tmp_path / "messages.dat"),
            str(tmp_path / "messages.db"),
            fernet_key,
        )
        result = await engine.rollback()
        assert not result

    async def test_rollback_restores_original_data(
        self, tmp_path, fernet_key, sample_data
    ):
        """After rollback, the original data must be fully readable."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()
        await engine.rollback()

        # Re-read the restored file
        from core.utils import decrypt_json

        restored = decrypt_json(dat.read_bytes(), fernet_key)
        assert set(restored["chats"].keys()) == set(
            sample_data["chats"].keys()
        )
        assert set(restored["contacts"].keys()) == set(
            sample_data["contacts"].keys()
        )


# =============================================================================
#  validate
# =============================================================================


class TestValidate:
    async def test_validate_after_migration(
        self, tmp_path, fernet_key, sample_data
    ):
        """validate() returns empty list after successful migration."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()

        diffs = await engine.validate()
        assert diffs == [], f"Differences found: {diffs}"

    async def test_validate_fails_if_backup_missing(
        self, tmp_path, fernet_key, sample_data
    ):
        """validate() should report if bak file is missing."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()
        # Remove backup
        (tmp_path / "messages.dat.bak").unlink()

        diffs = await engine.validate()
        assert any(
            "does not exist" in d or "não existe" in d for d in diffs
        )

    async def test_validate_reports_chat_mismatch(
        self, tmp_path, fernet_key, sample_data
    ):
        """If we alter the DB after migration, validate should catch it."""
        dat = tmp_path / "messages.dat"
        dat.write_bytes(encrypt_json(sample_data, fernet_key))
        db_path = tmp_path / "messages.db"

        from core.migration import MigrationEngine

        engine = MigrationEngine(str(dat), str(db_path), fernet_key)
        await engine.migrate()

        # Add an extra chat to the DB
        from core.database import DatabaseManager

        async with DatabaseManager(str(db_path), fernet_key) as db:
            await db.upsert_chat("extra@w", {"remoteJid": "extra@w"})

        diffs = await engine.validate()
        assert any("Extra" in d for d in diffs)
