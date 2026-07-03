"""
WinZapp Database Manager  (async version)
------------------------------------------
ACID-compliant SQLite storage for chats, messages, contacts, LID mappings,
and status updates.  Replaces the monolithic encrypted JSON (messages.dat)
with incremental, transactional writes.

Design decisions:
  - Fully async via ``aiosqlite`` — single connection, no threading hacks.
  - Structured concurrency via ``anyio`` — works on both asyncio and Trio.
  - WAL mode for concurrent reads without writer blocking.
  - Indexed columns (jid, timestamp) stored in plain text.
    Payload columns (message_json, last_message_json) encrypted via Fernet.
  - All public methods accept/return plain dicts matching the shapes that
    ``main.py`` expects, making the switch transparent.
  - ``import_from_dict`` / ``export_as_dict`` support the full messages.dat
    shape for migration.
  - Fernet is CPU-bound but fast (~1 µs per record); kept in the async
    context.  If profiling shows it blocks, move to
    ``anyio.to_thread.run_sync``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiosqlite
from cryptography.fernet import Fernet

log = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS chats (
    jid             TEXT PRIMARY KEY,
    remote_jid      TEXT NOT NULL,
    unread_count    INTEGER DEFAULT 0,
    push_name       TEXT DEFAULT '',
    name            TEXT DEFAULT '',
    archived        INTEGER DEFAULT 0,
    chat_type       TEXT DEFAULT 'chat',
    last_message_json TEXT DEFAULT '',
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT NOT NULL,
    remote_jid      TEXT NOT NULL,
    from_me         INTEGER DEFAULT 0,
    participant     TEXT DEFAULT '',
    message_type    TEXT DEFAULT '',
    message_json    TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    status          INTEGER DEFAULT 0,
    PRIMARY KEY (message_id, remote_jid)
);
CREATE INDEX IF NOT EXISTS idx_msgs_jid_ts
    ON messages(remote_jid, timestamp DESC);

CREATE TABLE IF NOT EXISTS contacts (
    jid             TEXT PRIMARY KEY,
    remote_jid      TEXT NOT NULL,
    name            TEXT DEFAULT '',
    push_name       TEXT DEFAULT '',
    profile_pic_url TEXT DEFAULT '',
    is_saved        INTEGER DEFAULT 0,
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lid_mappings (
    lid_jid     TEXT PRIMARY KEY,
    phone_jid   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS unresolvable_lids (
    jid     TEXT PRIMARY KEY,
    type    TEXT DEFAULT 'lid'
);

CREATE TABLE IF NOT EXISTS status_updates (
    participant_jid TEXT NOT NULL,
    message_id      TEXT NOT NULL,
    message_json    TEXT NOT NULL,
    timestamp       INTEGER NOT NULL,
    PRIMARY KEY (participant_jid, message_id)
);
"""

# How many messages to include inside each chat's ``messages.messages.records``
# when ``get_chats()`` builds the backward-compatible wrapper.  The caller can
# always use ``get_messages()`` to paginate the full set.
_CHAT_PAGE_SIZE = 200


# ── Helpers ───────────────────────────────────────────────────────────────────


def _now_ts() -> str:
    """ISO-8601 timestamp for SQLite TEXT columns."""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _jid_from_key(key: dict) -> str:
    """Extract the effective remote JID from a message key dict."""
    return key.get("remoteJidAlt") or key.get("remoteJid", "")


def _msg_id(key: dict) -> str:
    """Extract message id from key dict."""
    return key.get("id", "")


def _timestamp(msg: dict) -> int:
    """Extract numeric timestamp from a message dict (0 if missing)."""
    ts = msg.get("messageTimestamp", 0)
    try:
        return int(ts)
    except (TypeError, ValueError):
        return 0


def _message_type(msg: dict) -> str:
    """Determine the message-type label from a normalized message."""
    mt = msg.get("messageType", "")
    if mt:
        return mt
    m = msg.get("message", {})
    if isinstance(m, dict):
        for known in (
            "conversation",
            "extendedTextMessage",
            "imageMessage",
            "audioMessage",
            "videoMessage",
            "documentMessage",
            "stickerMessage",
            "contactMessage",
            "pollCreationMessage",
            "buttonsMessage",
            "listMessage",
            "templateMessage",
            "protocolMessage",
        ):
            if known in m:
                return known
    return "unknown"


# ── DatabaseManager ───────────────────────────────────────────────────────────


class DatabaseManager:
    """Async SQLite manager for WinZapp data.

    Parameters
    ----------
    db_path : str
        Path to the SQLite file, or ``\":memory:\"`` for testing.
    key : bytes
        Fernet symmetric key used to encrypt/decrypt payload columns.
    """

    def __init__(self, db_path: str, key: bytes):
        self.db_path = db_path
        self._fernet = Fernet(key)
        self._conn: aiosqlite.Connection | None = None
        # Serialise every DB write.  aiosqlite uses a single sqlite3 connection;
        # without this lock, two coroutines interleave at await points and one
        # may try BEGIN while the other already started an auto-transaction.
        self._write_lock = asyncio.Lock()

    # ── Async context manager ─────────────────────────────────────────────

    async def __aenter__(self) -> DatabaseManager:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def connect(self) -> None:
        """Open the SQLite connection and initialise the schema."""
        if self._conn is not None:
            return
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        # Without this, any external lock on the file (antivirus scanning
        # messages.db/-wal, OneDrive sync, etc.) makes SQLite raise "database
        # is locked" immediately instead of waiting briefly and retrying.
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(_SCHEMA_SQL)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the connection if open."""
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    @property
    async def is_connected(self) -> bool:
        """Check whether the database connection is open."""
        return self._conn is not None

    # ── Internal helpers ───────────────────────────────────────────────────

    def _encrypt(self, plain: str) -> str:
        """Encrypt a string with Fernet, returns base64 token."""
        if not plain:
            return ""
        return self._fernet.encrypt(plain.encode()).decode()

    def _decrypt(self, token: str) -> str:
        """Decrypt a Fernet token back to string."""
        if not token:
            return ""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except Exception as exc:
            log.warning("Failed to decrypt field: %s", exc)
            return ""

    def _encrypt_json(self, obj: Any) -> str:
        """JSON-serialize then encrypt. Returns empty string if obj is falsy."""
        if not obj:
            return ""
        return self._encrypt(json.dumps(obj, ensure_ascii=False))

    def _decrypt_json(self, token: str) -> Any:
        """Decrypt then JSON-deserialize."""
        plain = self._decrypt(token)
        if not plain:
            return {} if token else None
        try:
            return json.loads(plain)
        except json.JSONDecodeError:
            log.warning("Failed to JSON-decode decrypted field")
            return {}

    async def _ensure_conn(self) -> aiosqlite.Connection:
        """Auto-connect if not already connected."""
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        return self._conn

    # ── Chats ───────────────────────────────────────────────────────────────

    async def get_chats(self) -> dict[str, dict]:
        """Return all chats as ``{jid: chat_dict}``, compatible with main.py.

        Each chat dict includes a ``messages`` wrapper with the first
        ``_CHAT_PAGE_SIZE`` records so callers that iterate ``records``
        continue to work.  The full message set can be fetched via
        ``get_messages()``.
        """
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM chats ORDER BY remote_jid"
        )
        rows = await cursor.fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            jid = row["jid"]
            last_msg = self._decrypt_json(row["last_message_json"])
            msgs = await self._build_message_wrapper(jid)
            t = 0
            if isinstance(last_msg, dict):
                try:
                    t = int(last_msg.get("timestamp") or last_msg.get("messageTimestamp") or last_msg.get("t") or 0)
                except (TypeError, ValueError):
                    t = 0
            result[jid] = {
                "remoteJid": row["remote_jid"],
                "unreadCount": row["unread_count"],
                "pushName": row["push_name"] or "",
                "name": row["name"] or "",
                "messages": msgs,
                "lastMessage": last_msg,
                "t": t,
                "archived": bool(row["archived"]),
                "archive": bool(row["archived"]),
                "type": row["chat_type"] or "chat",
            }
        return result

    async def _build_message_wrapper(self, jid: str) -> dict:
        """Build the ``{messages: {{records: [...], total: N, ...}}}`` wrapper."""
        total = await self.get_message_count(jid)
        records = await self.get_messages(jid, limit=_CHAT_PAGE_SIZE, offset=0)
        return {
            "messages": {
                "records": records,
                "total": total,
                "pages": max(1, (total + _CHAT_PAGE_SIZE - 1) // _CHAT_PAGE_SIZE),
                "currentPage": 1,
            }
        }

    async def upsert_chat(self, jid: str, data: dict) -> None:
        """Insert or replace a chat record from a chat dict."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            remote_jid = data.get("remoteJid", jid)
            unread = int(data.get("unreadCount", 0))
            push_name = data.get("pushName", "")
            name = data.get("name", "")
            archived = 1 if (data.get("archived") or data.get("archive")) else 0
            chat_type = data.get("type", "chat")
            last_msg = data.get("lastMessage")
            last_msg_enc = self._encrypt_json(last_msg) if last_msg else ""

            await conn.execute(
                """INSERT OR REPLACE INTO chats
                   (jid, remote_jid, unread_count, push_name, name,
                    archived, chat_type, last_message_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (jid, remote_jid, unread, push_name, name,
                 archived, chat_type, last_msg_enc, _now_ts()),
            )
            await conn.commit()

    async def upsert_chats_batch(self, chats: dict[str, dict]) -> None:
        """Insert/replace multiple chats in one transaction."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            try:
                await conn.execute("BEGIN")
                for jid, data in chats.items():
                    remote_jid = data.get("remoteJid", jid)
                    unread = int(data.get("unreadCount", 0))
                    push_name = data.get("pushName", "")
                    name = data.get("name", "")
                    archived = 1 if (data.get("archived") or data.get("archive")) else 0
                    chat_type = data.get("type", "chat")
                    last_msg = data.get("lastMessage")
                    last_msg_enc = self._encrypt_json(last_msg) if last_msg else ""
                    await conn.execute(
                        """INSERT OR REPLACE INTO chats
                           (jid, remote_jid, unread_count, push_name, name,
                            archived, chat_type, last_message_json, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (jid, remote_jid, unread, push_name, name,
                         archived, chat_type, last_msg_enc, _now_ts()),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def get_chat_jids(self) -> list[str]:
        """Return a sorted list of all chat JIDs."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT jid FROM chats ORDER BY remote_jid"
        )
        rows = await cursor.fetchall()
        return [r["jid"] for r in rows]

    async def delete_chat(self, jid: str) -> None:
        """Remove a chat and all its messages."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute("DELETE FROM messages WHERE remote_jid=?", (jid,))
            await conn.execute("DELETE FROM chats WHERE jid=?", (jid,))
            await conn.commit()

    async def has_message(self, remote_jid: str, message_id: str) -> bool:
        """Return True if the message exists in the database."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT 1 FROM messages WHERE remote_jid=? AND message_id=? LIMIT 1",
            (remote_jid, message_id)
        )
        row = await cursor.fetchone()
        return row is not None

    # ── Messages ────────────────────────────────────────────────────────────


    async def get_messages(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        """Return message dicts for a chat, newest-first.

        Parameters
        ----------
        remote_jid : str
            Chat JID.
        limit : int
            Maximum records to return (default 200).
        offset : int
            Skip this many records (for pagination).

        Returns
        -------
        list[dict]
            Normalized message dicts (same shape as current messages.dat).
        """
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            """SELECT message_json FROM messages
               WHERE remote_jid=?
               ORDER BY timestamp DESC, message_id
               LIMIT ? OFFSET ?""",
            (remote_jid, limit, offset),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            msg = self._decrypt_json(row["message_json"])
            if msg:
                result.append(msg)
        return result

    async def get_messages_asc(
        self, remote_jid: str, limit: int = 200, offset: int = 0
    ) -> list[dict]:
        """Return message dicts oldest-first (for initial chat load)."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            """SELECT message_json FROM messages
               WHERE remote_jid=?
               ORDER BY timestamp ASC, message_id
               LIMIT ? OFFSET ?""",
            (remote_jid, limit, offset),
        )
        rows = await cursor.fetchall()
        result = []
        for row in rows:
            msg = self._decrypt_json(row["message_json"])
            if msg:
                result.append(msg)
        return result

    async def get_message_count(self, remote_jid: str) -> int:
        """Return total message count for a chat."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE remote_jid=?",
            (remote_jid,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def insert_message(self, remote_jid: str, msg: dict) -> None:
        """Insert a single message record."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            key = msg.get("key", {})
            mid = _msg_id(key)
            from_me = 1 if key.get("fromMe") else 0
            participant = key.get("participant", "")
            mtype = _message_type(msg)
            ts = _timestamp(msg)
            msg_enc = self._encrypt_json(msg)

            await conn.execute(
                """INSERT OR REPLACE INTO messages
                   (message_id, remote_jid, from_me, participant,
                    message_type, message_json, timestamp, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, remote_jid, from_me, participant,
                 mtype, msg_enc, ts, 0),
            )
            await conn.commit()

    async def insert_messages_batch(
        self, remote_jid: str, msgs: list[dict]
    ) -> None:
        """Insert many messages in a single transaction."""
        if not msgs:
            return
        async with self._write_lock:
            conn = await self._ensure_conn()
            try:
                await conn.execute("BEGIN")
                for msg in msgs:
                    key = msg.get("key", {})
                    mid = _msg_id(key)
                    from_me = 1 if key.get("fromMe") else 0
                    participant = key.get("participant", "")
                    mtype = _message_type(msg)
                    ts = _timestamp(msg)
                    msg_enc = self._encrypt_json(msg)
                    await conn.execute(
                        """INSERT OR REPLACE INTO messages
                           (message_id, remote_jid, from_me, participant,
                            message_type, message_json, timestamp, status)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (mid, remote_jid, from_me, participant,
                         mtype, msg_enc, ts, 0),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def update_message_id(
        self, remote_jid: str, old_id: str, new_id: str
    ) -> None:
        """Update a message's ID from old_id to new_id in the database."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            # First, check if the new_id already exists (to prevent duplicates)
            cursor = await conn.execute(
                "SELECT 1 FROM messages WHERE remote_jid=? AND message_id=?",
                (remote_jid, new_id),
            )
            exists = await cursor.fetchone()
            if exists:
                # If the new ID already exists, delete the old UUID message
                await conn.execute(
                    "DELETE FROM messages WHERE remote_jid=? AND message_id=?",
                    (remote_jid, old_id),
                )
            else:
                # Otherwise, update the message ID
                await conn.execute(
                    "UPDATE messages SET message_id=? WHERE remote_jid=? AND message_id=?",
                    (new_id, remote_jid, old_id),
                )
            await conn.commit()

    async def update_message_status(
        self, remote_jid: str, message_id: str, status: int
    ) -> None:
        """Update delivery/read status for a message."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "UPDATE messages SET status=? WHERE message_id=? AND remote_jid=?",
                (status, message_id, remote_jid),
            )
            await conn.commit()

    async def delete_message(self, remote_jid: str, message_id: str) -> None:
        """Delete a single message by remote_jid + message_id."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "DELETE FROM messages WHERE remote_jid=? AND message_id=?",
                (remote_jid, message_id),
            )
            await conn.commit()

    async def delete_chat_messages(self, remote_jid: str) -> None:
        """Remove all messages for a chat."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "DELETE FROM messages WHERE remote_jid=?", (remote_jid,)
            )
            await conn.commit()

    # ── Contacts ────────────────────────────────────────────────────────────

    async def get_contacts(self) -> dict[str, dict]:
        """Return all contacts as ``{jid: contact_dict}``."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM contacts ORDER BY remote_jid"
        )
        rows = await cursor.fetchall()
        result: dict[str, dict] = {}
        for row in rows:
            result[row["jid"]] = {
                "id": row["jid"],
                "remoteJid": row["remote_jid"],
                "name": row["name"] or "",
                "pushName": row["push_name"] or "",
                "profilePicUrl": row["profile_pic_url"] or "",
                "type": "contact",
                "isSaved": bool(row["is_saved"]),
            }
        return result

    async def upsert_contact(self, jid: str, data: dict) -> None:
        """Insert or replace a contact record."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            remote_jid = data.get("remoteJid", jid)
            name = data.get("name", "")
            push_name = data.get("pushName", "")
            pic = data.get("profilePicUrl", "")
            saved = 1 if data.get("isSaved") else 0

            await conn.execute(
                """INSERT OR REPLACE INTO contacts
                   (jid, remote_jid, name, push_name, profile_pic_url,
                    is_saved, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (jid, remote_jid, name, push_name, pic, saved, _now_ts()),
            )
            await conn.commit()

    async def upsert_contacts_batch(self, contacts: dict[str, dict]) -> None:
        """Insert/replace multiple contacts in one transaction."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            try:
                await conn.execute("BEGIN")
                for jid, data in contacts.items():
                    remote_jid = data.get("remoteJid", jid)
                    name = data.get("name", "")
                    push_name = data.get("pushName", "")
                    pic = data.get("profilePicUrl", "")
                    saved = 1 if data.get("isSaved") else 0
                    await conn.execute(
                        """INSERT OR REPLACE INTO contacts
                           (jid, remote_jid, name, push_name, profile_pic_url,
                            is_saved, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (jid, remote_jid, name, push_name, pic, saved, _now_ts()),
                    )
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    # ── LID Mappings ────────────────────────────────────────────────────────

    async def get_lid_mappings(self) -> dict[str, str]:
        """Return ``{lid_jid: phone_jid}``."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT lid_jid, phone_jid FROM lid_mappings"
        )
        rows = await cursor.fetchall()
        return {r["lid_jid"]: r["phone_jid"] for r in rows}

    async def set_lid_mapping(self, lid_jid: str, phone_jid: str) -> None:
        """Insert or update a single LID → phone mapping."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "INSERT OR REPLACE INTO lid_mappings (lid_jid, phone_jid) VALUES (?, ?)",
                (lid_jid, phone_jid),
            )
            await conn.commit()

    async def delete_lid_mapping(self, lid_jid: str) -> None:
        """Delete a single JID mapping."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "DELETE FROM lid_mappings WHERE lid_jid = ?",
                (lid_jid,),
            )
            await conn.commit()

    async def get_unresolvable_lids(self) -> tuple[set[str], set[str]]:
        """Return ``(set_of_lids, set_of_names)``."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT jid, type FROM unresolvable_lids"
        )
        rows = await cursor.fetchall()
        lids: set[str] = set()
        names: set[str] = set()
        for r in rows:
            if r["type"] == "name":
                names.add(r["jid"])
            else:
                lids.add(r["jid"])
        return lids, names

    async def add_unresolvable_lid(self, jid: str) -> None:
        """Mark a LID as unresolvable."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "INSERT OR IGNORE INTO unresolvable_lids (jid, type) VALUES (?, 'lid')",
                (jid,),
            )
            await conn.commit()

    async def add_unresolvable_name(self, jid: str) -> None:
        """Mark a LID as having an unresolvable name."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            await conn.execute(
                "INSERT OR IGNORE INTO unresolvable_lids (jid, type) VALUES (?, 'name')",
                (jid,),
            )
            await conn.commit()

    # ── Status Updates (Stories) ─────────────────────────────────────────────

    async def get_status_updates(self) -> dict[str, list[dict]]:
        """Return ``{participant_jid: [msg_dict, ...]}``."""
        conn = await self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM status_updates ORDER BY participant_jid, timestamp"
        )
        rows = await cursor.fetchall()
        result: dict[str, list[dict]] = {}
        for row in rows:
            p = row["participant_jid"]
            msg = self._decrypt_json(row["message_json"])
            if msg:
                result.setdefault(p, []).append(msg)
        return result

    async def upsert_status_update(self, participant: str, msg: dict) -> None:
        """Insert or replace a status update message."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            key = msg.get("key", {})
            mid = _msg_id(key)
            ts = _timestamp(msg)
            msg_enc = self._encrypt_json(msg)

            await conn.execute(
                """INSERT OR REPLACE INTO status_updates
                   (participant_jid, message_id, message_json, timestamp)
                   VALUES (?, ?, ?, ?)""",
                (participant, mid, msg_enc, ts),
            )
            await conn.commit()

    # ── Bulk Import / Export (for migration) ─────────────────────────────────

    async def import_from_dict(self, data: dict, clear_first: bool = False) -> int:
        """Populate the database from a messages.dat-shaped dict.

        Parameters
        ----------
        data : dict
            The messages.dat-shaped dict (keys: ``chats``, ``contacts``,
            ``lid_to_phone``, ``unresolvable_lids``, ``unresolvable_names``,
            ``status_updates``).
        clear_first : bool
            If ``True``, delete all existing records before importing.

        Returns
        -------
        int
            Total number of records imported.

        Notes
        -----
        All SQL is inlined here (not delegated to helper methods) because
        this method holds _write_lock for the entire operation; calling any
        other write method from here would deadlock on that same lock.
        One explicit BEGIN … COMMIT wraps everything so the import is atomic.
        """
        async with self._write_lock:
            conn = await self._ensure_conn()
            total = 0
            try:
                await conn.execute("BEGIN")

                if clear_first:
                    for tbl in (
                        "chats", "messages", "contacts",
                        "lid_mappings", "unresolvable_lids", "status_updates",
                    ):
                        await conn.execute(f"DELETE FROM {tbl}")

                # ── Chats + messages ─────────────────────────────────────
                now = _now_ts()
                for jid, chat in data.get("chats", {}).items():
                    remote_jid  = chat.get("remoteJid", jid)
                    unread      = int(chat.get("unreadCount", 0) or 0)
                    push_name   = chat.get("pushName", "") or ""
                    name        = chat.get("name", "") or ""
                    archived    = 1 if (chat.get("archived") or chat.get("archive")) else 0
                    chat_type   = chat.get("type", "chat") or "chat"
                    last_msg    = chat.get("lastMessage")
                    last_msg_enc = self._encrypt_json(last_msg) if last_msg else ""

                    await conn.execute(
                        """INSERT OR REPLACE INTO chats
                           (jid, remote_jid, unread_count, push_name, name,
                            archived, chat_type, last_message_json, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (jid, remote_jid, unread, push_name, name,
                         archived, chat_type, last_msg_enc, now),
                    )
                    total += 1

                    records = (
                        chat.get("messages", {})
                            .get("messages", {})
                            .get("records", [])
                    )
                    for msg in records:
                        key   = msg.get("key", {})
                        mid   = _msg_id(key)
                        fm    = 1 if key.get("fromMe") else 0
                        part  = key.get("participant", "") or ""
                        mtype = _message_type(msg)
                        ts    = _timestamp(msg)
                        menc  = self._encrypt_json(msg)
                        await conn.execute(
                            """INSERT OR REPLACE INTO messages
                               (message_id, remote_jid, from_me, participant,
                                message_type, message_json, timestamp, status)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (mid, remote_jid, fm, part, mtype, menc, ts, 0),
                        )
                        total += 1

                # ── Contacts ─────────────────────────────────────────────
                for jid, contact in data.get("contacts", {}).items():
                    remote_jid = contact.get("remoteJid", jid)
                    name       = contact.get("name", "") or ""
                    push_name  = contact.get("pushName", "") or ""
                    pic        = contact.get("profilePicUrl", "") or ""
                    saved      = 1 if contact.get("isSaved") else 0
                    await conn.execute(
                        """INSERT OR REPLACE INTO contacts
                           (jid, remote_jid, name, push_name, profile_pic_url,
                            is_saved, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (jid, remote_jid, name, push_name, pic, saved, now),
                    )
                    total += 1

                # ── LID mappings ──────────────────────────────────────────
                for lid_jid, phone_jid in data.get("lid_to_phone", {}).items():
                    await conn.execute(
                        "INSERT OR REPLACE INTO lid_mappings (lid_jid, phone_jid) VALUES (?, ?)",
                        (lid_jid, phone_jid),
                    )
                    total += 1

                # ── Unresolvable LIDs / names ─────────────────────────────
                for lid in data.get("unresolvable_lids", []):
                    await conn.execute(
                        "INSERT OR IGNORE INTO unresolvable_lids (jid, type) VALUES (?, 'lid')",
                        (lid,),
                    )
                    total += 1
                for nm in data.get("unresolvable_names", []):
                    await conn.execute(
                        "INSERT OR IGNORE INTO unresolvable_lids (jid, type) VALUES (?, 'name')",
                        (nm,),
                    )
                    total += 1

                # ── Status updates ────────────────────────────────────────
                for participant, statuses in data.get("status_updates", {}).items():
                    for smsg in statuses:
                        key  = smsg.get("key", {})
                        mid  = _msg_id(key)
                        ts   = _timestamp(smsg)
                        menc = self._encrypt_json(smsg)
                        await conn.execute(
                            """INSERT OR REPLACE INTO status_updates
                               (participant_jid, message_id, message_json, timestamp)
                               VALUES (?, ?, ?, ?)""",
                            (participant, mid, menc, ts),
                        )
                        total += 1

                await conn.commit()
                return total

            except Exception:
                await conn.rollback()
                raise

    async def export_as_dict(self) -> dict[str, Any]:
        """Export the full database as a messages.dat-shaped dict.

        Used for validation after migration.
        """
        chats = await self.get_chats()
        contacts = await self.get_contacts()
        lid_to_phone = await self.get_lid_mappings()
        lids, names = await self.get_unresolvable_lids()
        status_updates = await self.get_status_updates()

        return {
            "chats": chats,
            "contacts": contacts,
            "lid_to_phone": lid_to_phone,
            "unresolvable_lids": sorted(lids),
            "unresolvable_names": sorted(names),
            "status_updates": status_updates,
        }

    async def clear_all(self) -> None:
        """Delete all records from every table (for full-state replacement)."""
        async with self._write_lock:
            conn = await self._ensure_conn()
            try:
                await conn.execute("BEGIN")
                for table in (
                    "chats", "messages", "contacts",
                    "lid_mappings", "unresolvable_lids", "status_updates",
                ):
                    await conn.execute(f"DELETE FROM {table}")
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

    async def vacuum(self) -> None:
        """Recover disk space.  Call during idle periods."""
        conn = await self._ensure_conn()
        await conn.execute("VACUUM")
