"""Static regressions for attachment progress across chat navigation."""

import ast
from pathlib import Path


CONV = Path(__file__).resolve().parents[1] / "client" / "ui" / "conversations.py"
SOURCE = CONV.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def method_source(name: str) -> str:
    cls = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ConversationsPanel")
    node = next(n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SOURCE, node) or ""


def test_pending_attachment_is_kept_outside_open_conversation():
    init = method_source("__init__")
    register = method_source("_register_virtual_msg")
    navigate = method_source("navigate_to_conversation")
    assert "self._outgoing_virtual_messages: dict = {}" in init
    assert "self._outgoing_virtual_messages[local_id] = virtual_msg" in register
    assert "for local_id, pending in list(self._outgoing_virtual_messages.items())" in navigate
    assert "db_msgs.append(pending)" in navigate


def test_inactive_send_completion_updates_stable_virtual_row():
    mark = method_source("_mark_message_sent")
    inactive = method_source("_update_inactive_virtual_sent")
    assert "if not matched_visible_row" in mark
    assert "self._update_inactive_virtual_sent(" in mark
    assert 'msg["_local_pending"] = False' in inactive
    assert 'msg.setdefault("key", {})["id"] = real_id' in inactive


def test_reopening_chat_restores_current_upload_gauge():
    navigate = method_source("navigate_to_conversation")
    sync = method_source("_sync_pending_document_gauge")
    assert "self._sync_pending_document_gauge()" in navigate
    assert 'msg.get("_local_pending")' in sync
    assert 'msg.get("_awaiting_sent_ack")' in sync


def test_upload_progress_is_visible_after_attachment_panel_teardown():
    send = method_source("_on_send_attachment")
    hide = send.index("self._hide_attachment_panel()")
    assert send.index("self._sync_pending_document_gauge()", hide) > hide


def test_upload_progress_repaints_message_row_with_percentage():
    update = method_source("update_media_upload_progress")
    assert "self.messages_list.SetItemText" in update
    assert "self.messages_list.RefreshItem" in update
