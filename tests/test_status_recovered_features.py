"""Regression coverage for status features recovered from the legacy branch."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _method(relative: str, class_name: str, method_name: str) -> str:
    source = _source(relative)
    tree = ast.parse(source)
    lines = source.splitlines()
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    node = next(item for item in cls.body if isinstance(item, ast.FunctionDef) and item.name == method_name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def test_text_status_rejects_unsent_ack_and_refreshes_after_success():
    controller = _source("client/api_patches/src/controller/statusController.ts")
    sender = _method("client/status_panel.py", "StatusPanel", "_send_text_status_bg")
    assert "ack" in controller and "sendTextStatus" in controller
    assert "_post_was_rejected" in sender
    assert "_on_status_sent" in sender


def test_my_status_is_loaded_from_browser_store():
    controller = _source("client/api_patches/src/controller/statusController.ts")
    panel = _source("client/status_panel.py")
    assert "Own posted statuses" in controller
    assert "_my_statuses" in panel
    assert "_populate_list" in panel


def test_status_media_and_selected_actions_use_shared_viewer():
    panel = _source("client/status_panel.py")
    assert "MediaViewerDialog" in panel
    assert "_open_status_media_viewer" in panel
    assert "_on_viewer_status_opened" in panel
    assert "_viewer_reply_status" in panel


def test_status_like_and_viewed_state_are_scoped_by_status_id():
    panel = _source("client/status_panel.py")
    assert "_mark_status_viewed" in panel
    assert "_is_status_liked" in panel
    assert "_update_focused_status_row_text" in panel
