"""Regression checks for outgoing document upload UI lifecycle.

A just-attached document is pre-cached locally, so file existence alone must
not unlock Open/Save As. Its gauge exists only while bytes are transferring;
WhatsApp's later SENT acknowledgement independently unlocks the actions.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONV = ROOT / "client" / "ui" / "conversations.py"
MAIN = ROOT / "client" / "main.py"


def _method_source(path: Path, class_name: str, method_name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method_name:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{class_name}.{method_name} not found")


def test_outgoing_document_has_explicit_sent_ack_latch():
    src = _method_source(CONV, "ConversationsPanel", "_on_send_attachment")
    assert '"_awaiting_sent_ack": media_type == "document"' in src
    assert "self._media_upload_progress[local_id] = 0.0" in src


def test_document_selection_keeps_actions_locked_while_ack_pending():
    src = _method_source(CONV, "ConversationsPanel", "on_message_selected")
    assert 'if msg.get("_awaiting_sent_ack")' in src
    assert "_sync_pending_document_gauge" in src
    # The cached-file path is deliberately the *else* branch after the ACK latch.
    assert 'elif is_downloaded:' in src


def test_enter_and_save_as_are_blocked_until_sent_ack():
    activate = _method_source(CONV, "ConversationsPanel", "_do_activate_message")
    save_as = _method_source(CONV, "ConversationsPanel", "_on_action_save_as")
    open_action = _method_source(CONV, "ConversationsPanel", "_on_action_open")
    for src in (activate, save_as, open_action):
        assert 'msg.get("_awaiting_sent_ack")' in src
        assert "_sync_pending_document_gauge" in src


def test_upload_100_percent_hides_gauge_without_unlocking_actions():
    progress = _method_source(CONV, "ConversationsPanel", "update_media_upload_progress")
    sync = _method_source(CONV, "ConversationsPanel", "_sync_pending_document_gauge")
    mark = _method_source(CONV, "ConversationsPanel", "_mark_message_sent")
    assert "self._media_upload_progress[upload_id] = progress" in progress
    assert "< 1.0" in sync
    assert "self._sync_pending_document_gauge()" in progress
    assert "self._hide_media_transfer_gauge()" not in mark


def test_sent_or_later_status_retires_document_gauge():
    refresh = _method_source(CONV, "ConversationsPanel", "refresh_message_status")
    assert '_stage in ("sent", "delivered", "read", "played", "failed")' in refresh
    assert 'msg["_awaiting_sent_ack"] = False' in refresh
    assert "self._media_upload_progress.pop" in refresh
    assert "self._sync_pending_document_gauge()" in refresh


def test_send_file_http_ack_is_preserved_to_close_socket_ack_race():
    send = _method_source(MAIN, "MainWindow", "send_media_attachment")
    sent = _method_source(MAIN, "MainWindow", "_on_message_sent")
    assert 'raw_ack = resp.get("ack")' in send
    assert 'self._media_send_ack_by_local_id[upload_id] = raw_ack' in send
    assert "send_status = ack_to_status(raw_ack)" in sent
    assert "send_status=send_status" in sent


def test_late_sent_ack_is_not_dropped_by_sent_side_effect_dedupe():
    """A second completion callback may be the first one carrying ACK SENT."""
    src = _method_source(CONV, "ConversationsPanel", "_mark_message_sent")
    # _played only deduplicates one-time effects; it must not return before the
    # send_status block, otherwise a document can sit at 100% forever.
    assert "already_played = local_id in _played" in src
    assert "if local_id in _played:\n            return" not in src
    assert "send_status is not None" in src
    assert "not already_played" in src
    assert "self._show_document_actions_if_ready(i, msg)" in src


def test_sent_ack_immediately_unlocks_selected_cached_document_actions():
    mark = _method_source(CONV, "ConversationsPanel", "_mark_message_sent")
    refresh = _method_source(CONV, "ConversationsPanel", "refresh_message_status")
    helper = _method_source(CONV, "ConversationsPanel", "_show_document_actions_if_ready")
    assert "self._show_document_actions_if_ready(i, msg)" in mark
    assert "self._show_document_actions_if_ready(i, msg)" in refresh
    assert 'msg.get("_awaiting_sent_ack")' in helper
    assert "self._action_open_btn.Show()" in helper
    assert "self._action_save_as_btn.Show()" in helper


def test_upload_progress_is_monotonic_across_python_and_wpp_events():
    progress = _method_source(CONV, "ConversationsPanel", "update_media_upload_progress")
    assert "previous = self._media_upload_progress.get(upload_id, 0.0)" in progress
    assert "progress = max(previous, progress)" in progress


def test_deleting_pending_send_cancels_locally_even_if_everyone_was_selected():
    src = _method_source(CONV, "ConversationsPanel", "_on_menu_delete_message")
    cancel_at = src.index("self.main_window.message_queue.cancel(pending_local_id)")
    revoke_at = src.index("elif for_everyone:")
    assert cancel_at < revoke_at
    assert "cancelled_pending = bool(msg.get(\"_local_pending\")" in src
    assert "self._media_transfer_started.discard(pending_local_id)" in src
