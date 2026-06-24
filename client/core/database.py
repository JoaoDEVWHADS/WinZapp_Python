import json
import logging
import sqlite3
import threading
import time
from app_paths import data_path

VERSION = 1


class DatabaseManager:
    def __init__(self):
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._path = data_path("winzapp.db")
        self._initialize()

    def _conn(self):
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self._path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _execute(self, sql, params=None):
        c = self._conn().execute(sql, params or [])
        return c

    def _executemany(self, sql, seq):
        self._conn().executemany(sql, seq)

    def _commit(self):
        try:
            self._conn().commit()
        except Exception:
            pass

    def _initialize(self):
        sql = """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS contacts (
            jid TEXT PRIMARY KEY,
            name TEXT,
            push_name TEXT,
            is_group INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            muted INTEGER DEFAULT 0,
            unread_count INTEGER DEFAULT 0,
            last_msg_ts INTEGER,
            metadata TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            remote_jid TEXT NOT NULL,
            participant_jid TEXT,
            from_me INTEGER DEFAULT 0,
            msg_type TEXT,
            timestamp INTEGER,
            body TEXT,
            data TEXT,
            downloaded INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_messages_remote_jid ON messages(remote_jid);
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        CREATE TABLE IF NOT EXISTS lid_mapping (
            lid_jid TEXT PRIMARY KEY,
            phone_jid TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS unresolvable_lids (
            jid TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS unresolvable_names (
            name TEXT PRIMARY KEY
        );
        CREATE TABLE IF NOT EXISTS status_updates (
            id TEXT PRIMARY KEY,
            participant_jid TEXT,
            timestamp INTEGER,
            data TEXT
        );
        CREATE TABLE IF NOT EXISTS failed_media (
            msg_id TEXT PRIMARY KEY,
            error TEXT,
            timestamp INTEGER
        );
        """
        for statement in sql.split(";"):
            stmt = statement.strip()
            if stmt:
                try:
                    self._execute(stmt)
                except Exception as e:
                    logging.error(f"[DB] Schema init error: {e}")
        self._commit()

    def schema_version(self):
        try:
            row = self._execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            return row["version"] if row else 0
        except Exception:
            return 0

    def set_schema_version(self, version):
        self._execute("DELETE FROM schema_version")
        self._execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        self._commit()

    # settings
    def all_settings(self):
        rows = self._execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: json.loads(r["value"]) for r in rows}

    def settings_save_batch(self, settings_dict):
        with self._write_lock:
            self._execute("DELETE FROM settings")
            for key, value in settings_dict.items():
                self._execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )
            self._commit()

    def settings_has(self, key):
        return self._execute(
            "SELECT 1 FROM settings WHERE key = ?", (key,)
        ).fetchone() is not None

    # contacts
    def get_all_contacts(self):
        rows = self._execute("SELECT * FROM contacts").fetchall()
        result = {}
        for r in rows:
            jid = r["jid"]
            entry = {"id": jid, "remoteJid": jid}
            if r["name"]:
                entry["name"] = r["name"]
            if r["push_name"]:
                entry["pushName"] = r["push_name"]
            if r["metadata"]:
                try:
                    entry.update(json.loads(r["metadata"]))
                except Exception:
                    pass
            result[jid] = entry
        return result

    def save_contacts_batch(self, contacts_dict):
        with self._write_lock:
            for jid, contact in contacts_dict.items():
                name = contact.get("name") or contact.get("pushName")
                push_name = contact.get("pushName")
                metadata = {k: v for k, v in contact.items() if k not in ("id", "remoteJid", "name", "pushName")}
                self._execute(
                    """INSERT OR REPLACE INTO contacts
                    (jid, name, push_name, metadata)
                    VALUES (?, ?, ?, ?)""",
                    (jid, name, push_name, json.dumps(metadata) if metadata else None),
                )
            self._commit()

    def set_contact(self, jid, contact):
        name = contact.get("name") or contact.get("pushName")
        push_name = contact.get("pushName")
        with self._write_lock:
            self._execute(
                """INSERT OR REPLACE INTO contacts
                (jid, name, push_name) VALUES (?, ?, ?)""",
                (jid, name, push_name),
            )
            self._commit()

    # chats (derived from contacts + messages)
    def get_all_chats(self):
        rows = self._execute("""
            SELECT c.*,
                (SELECT MAX(timestamp) FROM messages WHERE remote_jid = c.jid) as last_msg_ts
            FROM contacts c
            ORDER BY last_msg_ts DESC
        """).fetchall()
        result = {}
        for r in rows:
            jid = r["jid"]
            chat = {
                "remoteJid": jid,
                "unreadCount": r["unread_count"] or 0,
                "pushName": r["push_name"] or "",
            }
            if r["name"]:
                chat["name"] = r["name"]
            chat["messages"] = {"messages": {"records": [], "total": 0, "pages": 1, "currentPage": 1}}
            result[jid] = chat
        return result

    def update_chat_unread(self, jid, unread_count=None, increment=False):
        with self._write_lock:
            if increment:
                self._execute(
                    "UPDATE contacts SET unread_count = COALESCE(unread_count, 0) + 1 WHERE jid = ?",
                    (jid,),
                )
            elif unread_count is not None:
                self._execute(
                    "UPDATE contacts SET unread_count = ? WHERE jid = ?",
                    (unread_count, jid),
                )
            self._commit()

    def update_chat_archived(self, jid, archived):
        with self._write_lock:
            self._execute("UPDATE contacts SET archived = ? WHERE jid = ?", (1 if archived else 0, jid))
            self._commit()

    def update_chat_muted(self, jid, muted):
        with self._write_lock:
            self._execute("UPDATE contacts SET muted = ? WHERE jid = ?", (1 if muted else 0, jid))
            self._commit()

    def set_chat_unread_zero(self, jid):
        with self._write_lock:
            self._execute("UPDATE contacts SET unread_count = 0 WHERE jid = ?", (jid,))
            self._commit()

    def set_chat_unread_all_zero(self):
        with self._write_lock:
            self._execute("UPDATE contacts SET unread_count = 0 WHERE unread_count > 0")
            self._commit()

    # messages
    def get_chat_messages(self, jid, limit=50, offset=0):
        rows = self._execute(
            """SELECT * FROM messages WHERE remote_jid = ?
            ORDER BY timestamp DESC LIMIT ? OFFSET ?""",
            (jid, limit, offset),
        ).fetchall()
        return [self._row_to_msg(r) for r in rows]

    def _row_to_msg(self, r):
        msg = json.loads(r["data"]) if r["data"] else {}
        msg["key"] = msg.get("key", {})
        msg["key"]["id"] = r["id"]
        msg["key"]["remoteJid"] = r["remote_jid"]
        msg["key"]["fromMe"] = bool(r["from_me"])
        msg["messageType"] = r["msg_type"]
        msg["messageTimestamp"] = r["timestamp"]
        return msg

    def save_message(self, msg):
        key = msg.get("key", {})
        msg_id = key.get("id", "")
        if not msg_id:
            return
        remote_jid = key.get("remoteJid", "")
        participant = key.get("participant")
        from_me = 1 if key.get("fromMe") else 0
        msg_type = msg.get("messageType", "")
        ts = msg.get("messageTimestamp", int(time.time()))
        with self._write_lock:
            self._execute(
                """INSERT OR IGNORE INTO messages
                (id, remote_jid, participant_jid, from_me, msg_type, timestamp, data)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, remote_jid, participant, from_me, msg_type, ts, json.dumps(msg)),
            )
            self._commit()

    def message_exists(self, msg_id):
        return self._execute(
            "SELECT 1 FROM messages WHERE id = ?", (msg_id,)
        ).fetchone() is not None

    def get_message_count(self, jid):
        row = self._execute(
            "SELECT COUNT(*) as cnt FROM messages WHERE remote_jid = ?", (jid,)
        ).fetchone()
        return row["cnt"] if row else 0

    def get_chat_message_records(self, jid):
        return self.get_chat_messages(jid, limit=100000)

    # lid mapping
    def get_all_lid_mappings(self):
        rows = self._execute("SELECT * FROM lid_mapping").fetchall()
        lid_to_phone = {}
        phone_to_lid = {}
        for r in rows:
            lid_to_phone[r["lid_jid"]] = r["phone_jid"]
            phone_to_lid[r["phone_jid"]] = r["lid_jid"]
        return lid_to_phone, phone_to_lid

    def set_lid_mapping(self, lid_jid, phone_jid):
        with self._write_lock:
            self._execute(
                "INSERT OR REPLACE INTO lid_mapping (lid_jid, phone_jid) VALUES (?, ?)",
                (lid_jid, phone_jid),
            )
            self._commit()

    def set_lid_mappings_batch(self, mapping_dict):
        with self._write_lock:
            for lid, phone in mapping_dict.items():
                self._execute(
                    "INSERT OR REPLACE INTO lid_mapping (lid_jid, phone_jid) VALUES (?, ?)",
                    (lid, phone),
                )
            self._commit()

    def get_all_unresolvable_lids(self):
        rows = self._execute("SELECT jid FROM unresolvable_lids").fetchall()
        return {r["jid"] for r in rows}

    def set_unresolvable_lids(self, lids_set):
        with self._write_lock:
            self._execute("DELETE FROM unresolvable_lids")
            for lid in lids_set:
                self._execute(
                    "INSERT OR IGNORE INTO unresolvable_lids (jid) VALUES (?)", (lid,)
                )
            self._commit()

    def get_all_unresolvable_names(self):
        rows = self._execute("SELECT name FROM unresolvable_names").fetchall()
        return {r["name"] for r in rows}

    def set_unresolvable_names(self, names_set):
        with self._write_lock:
            self._execute("DELETE FROM unresolvable_names")
            for name in names_set:
                self._execute(
                    "INSERT OR IGNORE INTO unresolvable_names (name) VALUES (?)", (name,)
                )
            self._commit()

    # status updates
    def get_all_status_updates(self):
        rows = self._execute("SELECT * FROM status_updates ORDER BY timestamp DESC").fetchall()
        result = {}
        for r in rows:
            participant = r["participant_jid"] or ""
            if participant not in result:
                result[participant] = []
            result[participant].append(json.loads(r["data"]))
        return result

    def save_status_update(self, msg):
        key = msg.get("key", {})
        msg_id = key.get("id", "")
        participant = key.get("participant") or key.get("remoteJid", "")
        ts = msg.get("messageTimestamp", int(time.time()))
        with self._write_lock:
            self._execute(
                """INSERT OR IGNORE INTO status_updates
                (id, participant_jid, timestamp, data) VALUES (?, ?, ?, ?)""",
                (msg_id, participant, ts, json.dumps(msg)),
            )
            self._commit()

    def clear_all_status_updates(self):
        with self._write_lock:
            self._execute("DELETE FROM status_updates")
            self._commit()

    # failed media
    def get_all_failed_media(self):
        rows = self._execute("SELECT * FROM failed_media").fetchall()
        return {r["msg_id"]: {"error": r["error"]} for r in rows}

    def set_failed_media(self, msg_id, error, ts=None):
        ts = ts or int(time.time())
        with self._write_lock:
            self._execute(
                "INSERT OR REPLACE INTO failed_media (msg_id, error, timestamp) VALUES (?, ?, ?)",
                (msg_id, str(error), ts),
            )
            self._commit()

    def remove_failed_media(self, msg_id):
        with self._write_lock:
            self._execute("DELETE FROM failed_media WHERE msg_id = ?", (msg_id,))
            self._commit()

    # full clear
    def clear_all(self):
        with self._write_lock:
            for table in ("messages", "contacts", "lid_mapping", "unresolvable_lids",
                          "unresolvable_names", "status_updates", "failed_media"):
                self._execute(f"DELETE FROM {table}")
            self._commit()

    def close(self):
        if hasattr(self._local, "conn") and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None
