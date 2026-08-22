"""Regression checks for history pagination using only public WPPConnect APIs.

These tests are intentionally source-level so they run even on CI hosts without
wxPython.  repos.zip is the contract: getMessages delegates to the public
client.getMessages() implementation; WinZapp must not depend on private
WhatsApp Web modules whose names change between web builds.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client" / "main.py"
CONTROLLER = ROOT / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
ROUTES = ROOT / "client" / "api_patches" / "src" / "routes" / "index.ts"


def _method_source(name: str) -> str:
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def _ts_function(name: str) -> str:
    source = CONTROLLER.read_text(encoding="utf-8")
    start = source.index(f"export async function {name}(")
    end = source.find("\nexport async function ", start + 1)
    return source[start:] if end < 0 else source[start:end]


def test_get_messages_delegates_to_the_public_client_api():
    src = _ts_function("getMessages")
    assert "req.client.getMessages(`${phone}`" in src
    assert "count: parseInt(count as string)" in src
    assert "direction: direction.toString() as any" in src
    assert "id: id as string" in src
    assert "page.evaluate" not in src


def test_private_history_sync_endpoints_are_not_shipped():
    routes = ROUTES.read_text(encoding="utf-8")
    controller = CONTROLLER.read_text(encoding="utf-8")
    for obsolete in (
        "request-older-messages",
        "history-sync-status",
        "unblock-history-sync",
        "WAWebUserPrefsHistorySync",
        "WAWebApiHistorySyncNotification",
        "restartBackend",
    ):
        assert obsolete not in routes
        assert obsolete not in controller


def test_scroll_pagination_uses_public_anchored_get_messages_only():
    src = _method_source("fetch_older_messages")
    assert "/get-messages/" in src
    assert "direction=before&id=" in src
    assert "_older_empty_strikes" in src
    assert "if n < 6:" in src
    assert "return None" in src
    assert "request_older_messages(" not in src


def test_short_histories_require_repeated_valid_confirmation():
    src = _method_source("_note_backfill_state")
    assert "if not api_ok:" in src
    assert "pending.add(remote_jid)" in src
    assert "if strikes < 6 or gap:" in src
    assert "count < previous" in src


def test_empty_remote_snapshot_cannot_mean_remote_clear():
    src = _method_source("_fetch_remote_message_ids")
    assert "if not wpp_messages:" in src
    assert "return None" in src


def test_partial_remote_snapshot_cannot_delete_local_messages():
    src = _method_source("_reconcile_active_conversation_with_remote")
    assert "if len(remote_ids) < len(local_ids):" in src
    block = src[src.index("if len(remote_ids) < len(local_ids):"):]
    assert "return" in block.split("missing_ids =", 1)[0]


def test_empty_api_response_preserves_durable_db_history():
    src = _method_source("sync_chat_messages")
    assert "if api_ok and not all_messages and not local_records:" in src
    assert "self.db.get_messages(remote_jid, limit=limit, offset=0)" in src
    assert "if all_messages:" in src
