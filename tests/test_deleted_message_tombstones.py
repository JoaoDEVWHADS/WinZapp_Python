"""Regression contracts for remote/local delete durability."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "client" / "core" / "database.py"
CONV = ROOT / "client" / "ui" / "conversations.py"
DEVICE = ROOT / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"


def _method(path: Path, cls: str, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{cls}.{name} missing")


def test_deleted_ids_have_durable_tombstones():
    source = DB.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS deleted_messages" in source
    delete = _method(DB, "DatabaseManager", "delete_messages_batch")
    assert delete.index("INSERT OR REPLACE INTO deleted_messages") < delete.index("DELETE FROM messages")


def test_sync_inserts_refuse_tombstoned_ids():
    one = _method(DB, "DatabaseManager", "insert_message")
    batch = _method(DB, "DatabaseManager", "insert_messages_batch")
    assert "_deleted_message_ids" in one
    assert "_deleted_message_ids" in batch


def test_hidden_row_delete_still_reaches_sqlite():
    remove = _method(CONV, "ConversationsPanel", "remove_messages_by_id")
    assert "if not indices:\n            return" not in remove
    assert "delete_messages_batch_async" in remove


def test_remote_already_missing_is_idempotent_success():
    source = DEVICE.read_text(encoding="utf-8")
    assert "Message already deleted" in source
    assert "alreadyDeleted: true" in source
