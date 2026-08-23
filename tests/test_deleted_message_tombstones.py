"""Regression contracts for remote/local delete durability."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "client" / "core" / "database.py"
CONV = ROOT / "client" / "ui" / "conversations.py"
DEVICE = ROOT / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
MAIN = ROOT / "client" / "main.py"
BRIDGE = ROOT / "client" / "core" / "database_bridge.py"


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



def test_delete_is_remembered_before_async_sqlite():
    remove = _method(CONV, "ConversationsPanel", "remove_messages_by_id")
    assert remove.index("_remember_deleted_message_ids") < remove.index("delete_messages_batch_async")


def test_sync_filters_tombstones_before_memory_assignment():
    sync = _method(MAIN, "MainWindow", "sync_chat_messages")
    assert sync.index("_filter_tombstoned_messages") < sync.index("self.chats[remote_jid] = chat")
    assert "api_ok and (all_messages or tombstone_filtered_ids)" in sync
    assert "_recompute_chat_last_message" in sync


def test_live_and_history_redelivery_refuse_tombstoned_ids():
    live = _method(MAIN, "MainWindow", "on_new_message")
    history = _method(MAIN, "MainWindow", "on_historical_message")
    assert "_is_message_tombstoned" in live
    assert "_is_message_tombstoned" in history


def test_pending_id_transition_carries_tombstone_to_real_id():
    sent = _method(MAIN, "MainWindow", "_on_message_sent")
    update = _method(DB, "DatabaseManager", "update_message_id")
    assert "deleted_before_confirmation" in sent
    assert "_remember_deleted_message_ids(remote_jid, [real_id])" in sent
    assert "old_id in deleted" in update
    assert "INSERT OR REPLACE INTO deleted_messages" in update


def test_cancelled_pending_message_is_deleted_locally_immediately():
    delete_menu = _method(CONV, "ConversationsPanel", "_on_menu_delete_message")
    pending = delete_menu.split("if cancelled_pending:", 1)[1].split("elif for_everyone:", 1)[0]
    assert "message_queue.cancel" in pending
    assert "remove_messages_by_id" in pending
    assert "msg_id or pending_local_id" in pending


def test_startup_warms_memory_tombstones():
    prepare = _method(MAIN, "MainWindow", "prepare_sync")
    assert "get_all_deleted_message_keys" in prepare
    assert "_remember_deleted_message_ids" in prepare
    bridge = _method(BRIDGE, "DatabaseBridge", "get_all_deleted_message_keys")
    assert "_db.get_all_deleted_message_keys" in bridge


def test_f5_resync_preserves_tombstone_cache_but_real_wipe_clears_it():
    clear = _method(MAIN, "MainWindow", "clear_local_data")
    assert "if wipe_metadata:" in clear
    assert "_deleted_message_ids_by_jid = {}" in clear
    # The cache reset must live under the metadata wipe guard, because the
    # normal F5/resync path deliberately uses wipe_metadata=False.
    assert clear.index("if wipe_metadata:") < clear.index("_deleted_message_ids_by_jid = {}")


def test_sqlite_reads_never_surface_tombstoned_rows():
    for name in ("get_messages", "get_messages_asc", "get_message_count", "get_message"):
        method = _method(DB, "DatabaseManager", name)
        assert "NOT EXISTS" in method
        assert "deleted_messages" in method
