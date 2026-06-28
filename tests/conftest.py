"""Shared fixtures for all WinZapp tests — async edition."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

# ── Fixtures: Keys / Encryption ───────────────────────────────────────────────


@pytest.fixture
def fernet_key() -> bytes:
    """Return a fresh Fernet key for one test."""
    return Fernet.generate_key()


@pytest.fixture
def fernet(fernet_key: bytes) -> Fernet:
    """Return a ready-to-use Fernet instance."""
    return Fernet(fernet_key)


# ── Fixtures: Sample Data ─────────────────────────────────────────────────────


@pytest.fixture
def sample_chat() -> dict:
    """A single chat dict matching the shape stored in messages.dat."""
    return {
        "remoteJid": "5511999999999@s.whatsapp.net",
        "unreadCount": 3,
        "pushName": "Alice",
        "name": "Alice Silva",
        "messages": {
            "messages": {
                "records": [],
                "total": 0,
                "pages": 1,
                "currentPage": 1,
            }
        },
        "lastMessage": None,
        "archive": False,
        "archived": False,
        "type": "chat",
    }


@pytest.fixture
def sample_contact() -> dict:
    """A single contact dict matching the shape stored in messages.dat."""
    return {
        "id": "5511999999999@s.whatsapp.net",
        "remoteJid": "5511999999999@s.whatsapp.net",
        "name": "Alice Silva",
        "pushName": "Alice",
        "profilePicUrl": "",
        "type": "contact",
        "isSaved": True,
    }


@pytest.fixture
def sample_message() -> dict:
    """A single normalized message dict (minimal)."""
    return {
        "key": {
            "remoteJid": "5511999999999@s.whatsapp.net",
            "fromMe": False,
            "id": "AB12345",
        },
        "pushName": "Alice",
        "message": {
            "conversation": "Hello, world!",
        },
        "messageTimestamp": 1700000000,
        "messageType": "conversation",
    }


@pytest.fixture
def sample_data(
    sample_chat: dict,
    sample_contact: dict,
    sample_message: dict,
) -> dict[str, Any]:
    """Full data dict matching the top-level shape of messages.dat."""
    chat_jid = "5511999999999@s.whatsapp.net"
    contact_jid = "5511999999999@s.whatsapp.net"

    # Add one message so the chat isn't empty
    chat = dict(sample_chat)
    chat["messages"]["messages"]["records"] = [sample_message]
    chat["messages"]["messages"]["total"] = 1

    return {
        "chats": {chat_jid: chat},
        "contacts": {contact_jid: sample_contact},
        "lid_to_phone": {"12345@lid": "5511999999999@s.whatsapp.net"},
        "unresolvable_lids": [],
        "unresolvable_names": [],
        "status_updates": {
            "5511888888888@s.whatsapp.net": [
                {
                    "key": {
                        "remoteJid": "status@broadcast",
                        "id": "status_1",
                        "participant": "5511888888888@s.whatsapp.net",
                    },
                    "message": {"conversation": "My status"},
                    "messageTimestamp": 1700000100,
                }
            ]
        },
    }


# ── Fixtures: Temporary files / directories ───────────────────────────────────


@pytest.fixture
def tmp_dir() -> Path:
    """Return a temporary directory that lives for the duration of a test."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def temp_messages_dat(tmp_dir: Path, fernet_key: bytes, sample_data: dict) -> Path:
    """Create a real encrypted messages.dat from sample_data and return its path."""
    from core.utils import encrypt_json

    path = tmp_dir / "messages.dat"
    encrypted = encrypt_json(sample_data, fernet_key)
    path.write_bytes(encrypted)
    return path


# ── Fixtures: Async DatabaseManager ───────────────────────────────────────────


@pytest_asyncio.fixture
async def in_memory_db(fernet_key: bytes):
    """Yield an async DatabaseManager pointed at an in-memory SQLite database."""
    from core.database import DatabaseManager

    async with DatabaseManager(":memory:", fernet_key) as db:
        yield db


@pytest_asyncio.fixture
async def db_with_data(in_memory_db, sample_data: dict):
    """Yield a DatabaseManager pre-populated with sample_data."""
    await in_memory_db.import_from_dict(sample_data)
    return in_memory_db
