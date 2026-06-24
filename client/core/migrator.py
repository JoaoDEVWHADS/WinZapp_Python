import json
import logging
import os
import shutil
from app_paths import data_path
from core.utils import decrypt_json, retrieve_key


def run_migration(db):
    """Run one-time migration from messages.dat + settings.json to SQLite.
    Safe to call on every startup — skips if already migrated."""
    if db.schema_version() >= 1:
        return

    logging.info("[Migrator] Starting migration from messages.dat → SQLite...")

    key = _get_or_create_key()
    if key is None:
        logging.error("[Migrator] No secret.key found, cannot decrypt messages.dat")
        db.set_schema_version(1)
        return

    _migrate_messages_dat(db, key)
    _migrate_settings_json(db)
    _migrate_media_failed_json(db)

    db.set_schema_version(1)
    logging.info("[Migrator] Migration complete.")


def _get_or_create_key():
    key_path = data_path("secret.key")
    if os.path.isfile(key_path):
        try:
            return retrieve_key(key_path)
        except Exception as e:
            logging.error(f"[Migrator] Failed to read secret.key: {e}")
            return None
    from core.utils import generate_and_save_key
    generate_and_save_key(key_path)
    return retrieve_key(key_path)


def _migrate_messages_dat(db, key):
    messages_file = data_path("messages.dat")
    if not os.path.isfile(messages_file):
        logging.info("[Migrator] No messages.dat found — skipping.")
        return

    try:
        with open(messages_file, "rb") as f:
            encrypted = f.read()
        if not encrypted:
            return
        data = decrypt_json(encrypted, key)
    except Exception as e:
        logging.error(f"[Migrator] Failed to decrypt messages.dat: {e}")
        return

    contacts = data.get("contacts", {})
    if contacts:
        logging.info(f"[Migrator] Migrating {len(contacts)} contacts...")
        for jid, contact in contacts.items():
            name = contact.get("name") or contact.get("pushName")
            push_name = contact.get("pushName")
            db._execute(
                "INSERT OR IGNORE INTO contacts (jid, name, push_name) VALUES (?, ?, ?)",
                (jid, name, push_name),
            )

    lid_to_phone = data.get("lid_to_phone", {})
    if lid_to_phone:
        logging.info(f"[Migrator] Migrating {len(lid_to_phone)} LID mappings...")
        for lid, phone in lid_to_phone.items():
            db._execute(
                "INSERT OR IGNORE INTO lid_mapping (lid_jid, phone_jid) VALUES (?, ?)",
                (lid, phone),
            )

    unresolvable_lids = data.get("unresolvable_lids", [])
    if unresolvable_lids:
        for lid in unresolvable_lids:
            db._execute(
                "INSERT OR IGNORE INTO unresolvable_lids (jid) VALUES (?)", (lid,)
            )

    unresolvable_names = data.get("unresolvable_names", [])
    if unresolvable_names:
        for name in unresolvable_names:
            db._execute(
                "INSERT OR IGNORE INTO unresolvable_names (name) VALUES (?)", (name,)
            )

    # Migrate status_updates
    status_updates = data.get("status_updates", {})
    if status_updates:
        for participant, entries in status_updates.items():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        entry_id = (
                            entry.get("key", {}).get("id") or entry.get("id", "")
                        )
                        if entry_id:
                            ts = entry.get("messageTimestamp", 0)
                            db._execute(
                                "INSERT OR IGNORE INTO status_updates (id, participant_jid, timestamp, data) VALUES (?, ?, ?, ?)",
                                (entry_id, participant, ts, json.dumps(entry)),
                            )

    # Migrate chats + messages
    chats = data.get("chats", {})
    if chats:
        total_msgs = 0
        for jid, chat_data in chats.items():
            push_name = chat_data.get("pushName", "")
            unread = chat_data.get("unreadCount", 0)
            db._execute(
                """INSERT OR IGNORE INTO contacts
                (jid, push_name, unread_count) VALUES (?, ?, ?)""",
                (jid, push_name, unread),
            )

            messages = chat_data.get("messages", {}).get("messages", {}).get("records", [])
            for msg in messages:
                if isinstance(msg, dict):
                    key = msg.get("key", {})
                    msg_id = key.get("id", "")
                    if not msg_id:
                        continue
                    remote_jid = key.get("remoteJid", jid)
                    participant = key.get("participant")
                    from_me = 1 if key.get("fromMe") else 0
                    msg_type = msg.get("messageType", "")
                    ts = msg.get("messageTimestamp", 0)
                    db._execute(
                        """INSERT OR IGNORE INTO messages
                        (id, remote_jid, participant_jid, from_me, msg_type, timestamp, data)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (msg_id, remote_jid, participant, from_me, msg_type, ts, json.dumps(msg)),
                    )
                    total_msgs += 1
        logging.info(f"[Migrator] Migrated {len(chats)} chats with {total_msgs} messages.")

    db._commit()

    backup_path = messages_file + ".backup"
    try:
        shutil.move(messages_file, backup_path)
        logging.info(f"[Migrator] Renamed messages.dat → messages.dat.backup")
    except Exception as e:
        logging.error(f"[Migrator] Failed to backup messages.dat: {e}")


def _migrate_settings_json(db):
    settings_file = data_path("settings.json")
    if not os.path.isfile(settings_file):
        logging.info("[Migrator] No settings.json found — skipping.")
        return

    try:
        with open(settings_file, "r") as f:
            settings = json.load(f)
    except Exception as e:
        logging.error(f"[Migrator] Failed to read settings.json: {e}")
        return

    if not isinstance(settings, dict):
        return

    logging.info(f"[Migrator] Migrating {len(settings)} settings sections...")
    for key, value in settings.items():
        db._execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, json.dumps(value)),
        )
    db._commit()

    backup_path = settings_file + ".backup"
    try:
        shutil.move(settings_file, backup_path)
        logging.info(f"[Migrator] Renamed settings.json → settings.json.backup")
    except Exception as e:
        logging.error(f"[Migrator] Failed to backup settings.json: {e}")


def _migrate_media_failed_json(db):
    media_failed_file = data_path("media_failed.json")
    if not os.path.isfile(media_failed_file):
        return

    try:
        with open(media_failed_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        logging.error(f"[Migrator] Failed to read media_failed.json: {e}")
        return

    if not isinstance(data, dict):
        return

    for msg_id, info in data.items():
        error = info.get("error", "") if isinstance(info, dict) else str(info)
        db._execute(
            "INSERT OR IGNORE INTO failed_media (msg_id, error, timestamp) VALUES (?, ?, ?)",
            (msg_id, error, 0),
        )
    db._commit()

    backup_path = media_failed_file + ".backup"
    try:
        shutil.move(media_failed_file, backup_path)
    except Exception:
        pass
