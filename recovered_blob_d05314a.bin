"""Tests for core.database.DatabaseManager — async edition."""

import json
from typing import Any

import anyio
import pytest
from cryptography.fernet import Fernet


# =============================================================================
#  Chats
# =============================================================================


class TestChats:
    async def test_upsert_chat_creates_record(self, in_memory_db):
        await in_memory_db.upsert_chat("jid@w", {"remoteJid": "jid@w", "pushName": "Foo"})
        chats = await in_memory_db.get_chats()
        assert "jid@w" in chats
        assert chats["jid@w"]["pushName"] == "Foo"
        assert chats["jid@w"]["remoteJid"] == "jid@w"

    async def test_upsert_chat_updates_existing(self, in_memory_db):
        await in_memory_db.upsert_chat("jid@w", {"remoteJid": "jid@w", "pushName": "Foo"})
        await in_memory_db.upsert_chat("jid@w", {"remoteJid": "jid@w", "pushName": "Bar"})
        chats = await in_memory_db.get_chats()
        assert chats["jid@w"]["pushName"] == "Bar"

    async def test_get_chats_returns_empty_dict_when_empty(self, in_memory_db):
        assert await in_memory_db.get_chats() == {}

    async def test_get_chats_includes_message_wrapper(self, in_memory_db):
        chat = {
            "remoteJid": "jid@w",
            "unreadCount": 2,
            "pushName": "Test",
            "name": "Test User",
            "type": "chat",
        }
        await in_memory_db.upsert_chat("jid@w", chat)
        chats = await in_memory_db.get_chats()
        assert "messages" in chats["jid@w"]
        assert chats["jid@w"]["messages"]["messages"]["total"] == 0
        assert chats["jid@w"]["messages"]["messages"]["records"] == []

    async def test_get_chats_includes_message_count(self, in_memory_db):
        chat = {"remoteJid": "jid@w", "pushName": "Test"}
        await in_memory_db.upsert_chat("jid@w", chat)

        for i in range(5):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"msg{i}"},
                    "messageTimestamp": i,
                    "message": {"conversation": f"msg{i}"},
                    "messageType": "conversation",
                },
            )

        chats = await in_memory_db.get_chats()
        assert chats["jid@w"]["messages"]["messages"]["total"] == 5

    async def test_get_chats_archived_flag(self, in_memory_db):
        chat = {"remoteJid": "jid@w", "archived": True}
        await in_memory_db.upsert_chat("jid@w", chat)
        chats = await in_memory_db.get_chats()
        assert chats["jid@w"]["archived"] is True
        assert chats["jid@w"]["archive"] is True

    async def test_upsert_chats_batch(self, in_memory_db):
        chats = {
            "a@w": {"remoteJid": "a@w", "pushName": "A"},
            "b@w": {"remoteJid": "b@w", "pushName": "B"},
        }
        await in_memory_db.upsert_chats_batch(chats)
        result = await in_memory_db.get_chats()
        assert set(result.keys()) == {"a@w", "b@w"}

    async def test_get_chat_jids(self, in_memory_db):
        await in_memory_db.upsert_chat("a@w", {"remoteJid": "a@w"})
        await in_memory_db.upsert_chat("b@w", {"remoteJid": "b@w"})
        jids = await in_memory_db.get_chat_jids()
        assert sorted(jids) == ["a@w", "b@w"]

    async def test_delete_chat_removes_chat_and_messages(self, in_memory_db):
        await in_memory_db.upsert_chat("jid@w", {"remoteJid": "jid@w"})
        await in_memory_db.insert_message("jid@w", {
            "key": {"remoteJid": "jid@w", "id": "m1"},
            "messageTimestamp": 1,
        })
        await in_memory_db.delete_chat("jid@w")
        chats = await in_memory_db.get_chats()
        assert "jid@w" not in chats
        msgs = await in_memory_db.get_messages("jid@w")
        assert msgs == []


# =============================================================================
#  Messages
# =============================================================================


class TestMessages:
    async def test_insert_and_retrieve(self, in_memory_db):
        msg = {
            "key": {"remoteJid": "jid@w", "id": "msg1"},
            "messageTimestamp": 1000,
            "message": {"conversation": "hello"},
            "messageType": "conversation",
        }
        await in_memory_db.insert_message("jid@w", msg)
        msgs = await in_memory_db.get_messages("jid@w")
        assert len(msgs) == 1
        assert msgs[0]["key"]["id"] == "msg1"
        assert msgs[0]["message"]["conversation"] == "hello"

    async def test_get_messages_newest_first(self, in_memory_db):
        for i in range(10):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"msg{i}"},
                    "messageTimestamp": i,
                    "message": {"conversation": f"text{i}"},
                    "messageType": "conversation",
                },
            )
        msgs = await in_memory_db.get_messages("jid@w", limit=3)
        assert len(msgs) == 3
        assert msgs[0]["key"]["id"] == "msg9"
        assert msgs[-1]["key"]["id"] == "msg7"

    async def test_get_messages_asc_oldest_first(self, in_memory_db):
        for i in range(5):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"msg{i}"},
                    "messageTimestamp": i,
                },
            )
        msgs = await in_memory_db.get_messages_asc("jid@w", limit=3)
        assert len(msgs) == 3
        assert msgs[0]["key"]["id"] == "msg0"
        assert msgs[-1]["key"]["id"] == "msg2"

    async def test_get_messages_pagination(self, in_memory_db):
        for i in range(50):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"msg{i:02d}"},
                    "messageTimestamp": i,
                },
            )
        page1 = await in_memory_db.get_messages("jid@w", limit=20, offset=0)
        page2 = await in_memory_db.get_messages("jid@w", limit=20, offset=20)
        assert len(page1) == 20
        assert len(page2) == 20
        assert page1[0]["key"]["id"] != page2[0]["key"]["id"]

    async def test_get_message_count(self, in_memory_db):
        count = await in_memory_db.get_message_count("jid@w")
        assert count == 0
        for i in range(7):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"m{i}"},
                    "messageTimestamp": i,
                },
            )
        count = await in_memory_db.get_message_count("jid@w")
        assert count == 7

    async def test_insert_updates_existing_message(self, in_memory_db):
        msg1 = {
            "key": {"remoteJid": "jid@w", "id": "m1"},
            "messageTimestamp": 1,
            "message": {"conversation": "first"},
            "messageType": "conversation",
        }
        msg2 = {
            "key": {"remoteJid": "jid@w", "id": "m1"},
            "messageTimestamp": 2,
            "message": {"conversation": "second"},
            "messageType": "conversation",
        }
        await in_memory_db.insert_message("jid@w", msg1)
        await in_memory_db.insert_message("jid@w", msg2)
        msgs = await in_memory_db.get_messages("jid@w")
        assert len(msgs) == 1
        assert msgs[0]["message"]["conversation"] == "second"

    async def test_update_message_status(self, in_memory_db):
        await in_memory_db.insert_message(
            "jid@w",
            {
                "key": {"remoteJid": "jid@w", "id": "m1"},
                "messageTimestamp": 1,
            },
        )
        await in_memory_db.update_message_status("jid@w", "m1", 3)
        msgs = await in_memory_db.get_messages("jid@w")
        assert len(msgs) == 1

    async def test_delete_chat_messages(self, in_memory_db):
        await in_memory_db.insert_message(
            "jid@w",
            {
                "key": {"remoteJid": "jid@w", "id": "m1"},
                "messageTimestamp": 1,
            },
        )
        await in_memory_db.delete_chat_messages("jid@w")
        count = await in_memory_db.get_message_count("jid@w")
        assert count == 0

    async def test_delete_single_message(self, in_memory_db):
        for i in range(3):
            await in_memory_db.insert_message(
                "jid@w",
                {
                    "key": {"remoteJid": "jid@w", "id": f"msg{i}"},
                    "messageTimestamp": i,
                },
            )
        await in_memory_db.delete_message("jid@w", "msg1")
        remaining = await in_memory_db.get_messages_asc("jid@w")
        ids = [m["key"]["id"] for m in remaining]
        assert ids == ["msg0", "msg2"]
        assert len(ids) == 2

    async def test_insert_messages_batch(self, in_memory_db):
        msgs = [
            {
                "key": {"remoteJid": "jid@w", "id": f"m{i}"},
                "messageTimestamp": i,
                "message": {"conversation": f"text{i}"},
                "messageType": "conversation",
            }
            for i in range(10)
        ]
        await in_memory_db.insert_messages_batch("jid@w", msgs)
        count = await in_memory_db.get_message_count("jid@w")
        assert count == 10

    async def test_get_messages_empty_chat(self, in_memory_db):
        msgs = await in_memory_db.get_messages("nonexistent@w")
        assert msgs == []

    async def test_encrypted_message_json(self, in_memory_db, fernet_key):
        """Verify that message content is encrypted at rest."""
        msg = {
            "key": {"remoteJid": "jid@w", "id": "sec1"},
            "messageTimestamp": 42,
            "message": {"conversation": "sensitive data"},
            "messageType": "conversation",
        }
        await in_memory_db.insert_message("jid@w", msg)

        # Access internal connection to verify raw storage
        assert in_memory_db._conn is not None
        cursor = await in_memory_db._conn.execute(
            "SELECT message_json FROM messages WHERE message_id='sec1'"
        )
        row = await cursor.fetchone()
        raw = row["message_json"]
        assert "sensitive data" not in raw
        assert raw.startswith("gAAAAA")  # Fernet base64 token prefix


# =============================================================================
#  Contacts
# =============================================================================


class TestContacts:
    async def test_upsert_contact_creates(self, in_memory_db):
        await in_memory_db.upsert_contact("jid@w", {
            "id": "jid@w", "remoteJid": "jid@w", "name": "John",
        })
        contacts = await in_memory_db.get_contacts()
        assert contacts["jid@w"]["name"] == "John"

    async def test_upsert_contact_updates(self, in_memory_db):
        await in_memory_db.upsert_contact("jid@w", {
            "id": "jid@w", "remoteJid": "jid@w", "name": "John",
        })
        await in_memory_db.upsert_contact("jid@w", {
            "id": "jid@w", "remoteJid": "jid@w", "name": "Johnny",
        })
        contacts = await in_memory_db.get_contacts()
        assert contacts["jid@w"]["name"] == "Johnny"

    async def test_get_contacts_empty(self, in_memory_db):
        contacts = await in_memory_db.get_contacts()
        assert contacts == {}

    async def test_get_contacts_multiple(self, in_memory_db):
        await in_memory_db.upsert_contact("a@w", {"id": "a@w", "remoteJid": "a@w"})
        await in_memory_db.upsert_contact("b@w", {"id": "b@w", "remoteJid": "b@w"})
        contacts = await in_memory_db.get_contacts()
        assert set(contacts.keys()) == {"a@w", "b@w"}

    async def test_contact_isSaved_bool(self, in_memory_db):
        await in_memory_db.upsert_contact("jid@w", {
            "id": "jid@w", "remoteJid": "jid@w", "isSaved": True,
        })
        contacts = await in_memory_db.get_contacts()
        assert contacts["jid@w"]["isSaved"] is True

        await in_memory_db.upsert_contact("jid@w", {
            "id": "jid@w", "remoteJid": "jid@w", "isSaved": False,
        })
        contacts = await in_memory_db.get_contacts()
        assert contacts["jid@w"]["isSaved"] is False

    async def test_upsert_contacts_batch(self, in_memory_db):
        contacts = {
            "a@w": {"id": "a@w", "remoteJid": "a@w", "name": "A"},
            "b@w": {"id": "b@w", "remoteJid": "b@w", "name": "B"},
        }
        await in_memory_db.upsert_contacts_batch(contacts)
        result = await in_memory_db.get_contacts()
        assert result["a@w"]["name"] == "A"
        assert result["b@w"]["name"] == "B"


# =============================================================================
#  LID Mappings
# =============================================================================


class TestLidMappings:
    async def test_get_lid_mappings_empty(self, in_memory_db):
        mappings = await in_memory_db.get_lid_mappings()
        assert mappings == {}

    async def test_set_and_get_lid_mapping(self, in_memory_db):
        await in_memory_db.set_lid_mapping("lid@lid", "phone@s.whatsapp.net")
        mappings = await in_memory_db.get_lid_mappings()
        assert mappings == {"lid@lid": "phone@s.whatsapp.net"}

    async def test_set_lid_mapping_updates(self, in_memory_db):
        await in_memory_db.set_lid_mapping("lid@lid", "old@w")
        await in_memory_db.set_lid_mapping("lid@lid", "new@w")
        mappings = await in_memory_db.get_lid_mappings()
        assert mappings["lid@lid"] == "new@w"

    async def test_multiple_lid_mappings(self, in_memory_db):
        await in_memory_db.set_lid_mapping("l1@lid", "p1@w")
        await in_memory_db.set_lid_mapping("l2@lid", "p2@w")
        mappings = await in_memory_db.get_lid_mappings()
        assert len(mappings) == 2
        assert mappings["l1@lid"] == "p1@w"

    async def test_unresolvable_lids_empty(self, in_memory_db):
        lids, names = await in_memory_db.get_unresolvable_lids()
        assert lids == set()
        assert names == set()

    async def test_add_unresolvable_lid(self, in_memory_db):
        await in_memory_db.add_unresolvable_lid("bad@lid")
        lids, names = await in_memory_db.get_unresolvable_lids()
        assert "bad@lid" in lids
        assert len(names) == 0

    async def test_add_unresolvable_name(self, in_memory_db):
        await in_memory_db.add_unresolvable_name("no_name@lid")
        lids, names = await in_memory_db.get_unresolvable_lids()
        assert "no_name@lid" in names
        assert len(lids) == 0

    async def test_add_unresolvable_lid_idempotent(self, in_memory_db):
        await in_memory_db.add_unresolvable_lid("bad@lid")
        await in_memory_db.add_unresolvable_lid("bad@lid")  # should not error
        lids, _ = await in_memory_db.get_unresolvable_lids()
        assert len(lids) == 1


# =============================================================================
#  Status Updates
# =============================================================================


class TestStatusUpdates:
    async def test_get_status_updates_empty(self, in_memory_db):
        updates = await in_memory_db.get_status_updates()
        assert updates == {}

    async def test_upsert_and_get_status(self, in_memory_db):
        msg = {
            "key": {
                "remoteJid": "status@broadcast",
                "id": "s1",
                "participant": "me@w",
            },
            "message": {"conversation": "my status"},
            "messageTimestamp": 1000,
            "messageType": "conversation",
        }
        await in_memory_db.upsert_status_update("me@w", msg)
        updates = await in_memory_db.get_status_updates()
        assert "me@w" in updates
        assert len(updates["me@w"]) == 1
        assert updates["me@w"][0]["message"]["conversation"] == "my status"

    async def test_multiple_statuses_same_user(self, in_memory_db):
        for i in range(3):
            await in_memory_db.upsert_status_update(
                "me@w",
                {
                    "key": {
                        "remoteJid": "status@broadcast",
                        "id": f"s{i}",
                        "participant": "me@w",
                    },
                    "message": {"conversation": f"s{i}"},
                    "messageTimestamp": i,
                    "messageType": "conversation",
                },
            )
        updates = await in_memory_db.get_status_updates()
        assert len(updates["me@w"]) == 3

    async def test_multiple_users_statuses(self, in_memory_db):
        await in_memory_db.upsert_status_update("a@w", {
            "key": {"id": "a1", "participant": "a@w"},
            "messageTimestamp": 1,
            "messageType": "conversation",
        })
        await in_memory_db.upsert_status_update("b@w", {
            "key": {"id": "b1", "participant": "b@w"},
            "messageTimestamp": 1,
            "messageType": "conversation",
        })
        updates = await in_memory_db.get_status_updates()
        assert set(updates.keys()) == {"a@w", "b@w"}


# =============================================================================
#  Bulk Import / Export (Migration)
# =============================================================================


class TestBulkImportExport:
    async def test_import_from_dict_basic(self, in_memory_db, sample_data):
        count = await in_memory_db.import_from_dict(sample_data)
        assert count > 0

        chats = await in_memory_db.get_chats()
        assert len(chats) == len(sample_data["chats"])

        contacts = await in_memory_db.get_contacts()
        assert len(contacts) == len(sample_data["contacts"])

    async def test_import_export_roundtrip(self, in_memory_db, sample_data):
        await in_memory_db.import_from_dict(sample_data)
        exported = await in_memory_db.export_as_dict()

        assert set(exported["chats"].keys()) == set(sample_data["chats"].keys())
        assert set(exported["contacts"].keys()) == set(sample_data["contacts"].keys())
        assert exported["lid_to_phone"] == sample_data["lid_to_phone"]
        assert set(exported["status_updates"].keys()) == set(
            sample_data["status_updates"].keys()
        )

    async def test_export_empty_db(self, in_memory_db):
        exported = await in_memory_db.export_as_dict()
        assert exported["chats"] == {}
        assert exported["contacts"] == {}
        assert exported["lid_to_phone"] == {}

    async def test_import_preserves_message_content(self, in_memory_db, sample_data):
        await in_memory_db.import_from_dict(sample_data)
        exported = await in_memory_db.export_as_dict()

        for chat_jid, chat in exported["chats"].items():
            records = chat.get("messages", {}).get("messages", {}).get("records", [])
            if records:
                msg = records[0]
                orig_jid = list(sample_data["chats"].keys())[0]
                orig_records = (
                    sample_data["chats"][orig_jid]
                    .get("messages", {})
                    .get("messages", {})
                    .get("records", [])
                )
                if orig_records:
                    assert msg["key"]["id"] == orig_records[0]["key"]["id"]
                    if "conversation" in msg.get("message", {}):
                        assert (
                            msg["message"]["conversation"]
                            == orig_records[0]["message"]["conversation"]
                        )
                break

    async def test_import_is_idempotent(self, in_memory_db, sample_data):
        c1 = await in_memory_db.import_from_dict(sample_data)
        c2 = await in_memory_db.import_from_dict(sample_data)

        chats = await in_memory_db.get_chats()
        assert len(chats) == len(sample_data["chats"])

        for jid in sample_data["chats"]:
            orig_count = len(
                sample_data["chats"][jid]
                .get("messages", {})
                .get("messages", {})
                .get("records", [])
            )
            count = await in_memory_db.get_message_count(jid)
            assert count == orig_count


# =============================================================================
#  Structured Concurrency (replaces old thread-safety tests)
# =============================================================================


class TestStructuredConcurrency:
    async def test_concurrent_writes_task_group(self, tmp_path, fernet_key):
        """Concurrent writes via anyio TaskGroup — all must succeed."""
        from core.database import DatabaseManager

        db_path = str(tmp_path / "test.db")
        async with DatabaseManager(db_path, fernet_key) as db:
            async with anyio.create_task_group() as tg:
                for letter in ("a", "b", "c"):
                    tg.start_soon(self._write_chats, db, letter, 10)

            chats = await db.get_chats()
            assert "a@a" in chats
            assert "b@b" in chats
            assert "c@c" in chats

    async def _write_chats(
        self, db, name: str, count: int
    ) -> None:
        """Helper: write *count* chats with prefix *name*."""
        for i in range(count):
            await db.upsert_chat(
                f"{name}@{name}",
                {"remoteJid": f"{name}@{name}", "pushName": f"{name}{i}"},
            )

    async def test_concurrent_read_and_write(self, tmp_path, fernet_key):
        """Concurrent readers and writers via TaskGroup — no errors."""
        from core.database import DatabaseManager

        db_path = str(tmp_path / "test.db")
        errors: list[Exception] = []

        async def reader():
            try:
                for _ in range(30):
                    await db.get_chats()
            except Exception as e:
                errors.append(e)

        async def writer():
            try:
                for i in range(30):
                    await db.upsert_chat(
                        f"jid{i}@w", {"remoteJid": f"jid{i}@w"}
                    )
            except Exception as e:
                errors.append(e)

        async with DatabaseManager(db_path, fernet_key) as db:
            async with anyio.create_task_group() as tg:
                tg.start_soon(reader)
                tg.start_soon(writer)

        assert not errors, f"Errors during concurrent access: {errors}"
