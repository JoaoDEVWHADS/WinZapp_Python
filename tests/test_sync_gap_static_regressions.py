"""Static regression checks for the sync gaps reproduced by logs.zip.

These are intentionally source-level so they can run in CI environments that
cannot import wxPython. Behavioural tests elsewhere cover the same helpers on
Windows where the full application dependencies are installed.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client" / "main.py"
CONV = ROOT / "client" / "ui" / "conversations.py"
START = ROOT / "client" / "api_patches" / "start.js"


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


def test_pin_install_failure_never_reenables_blanket_interception():
    src = START.read_text(encoding="utf-8")
    assert "falling back to WPPConnect's blanket one" not in src
    assert "continuing without the version pin" in src
    # Success + catch + wa-version-miss branches all consume the version.
    assert src.count("version = undefined;") >= 3


def test_temporary_empty_older_page_does_not_mean_reached_start():
    fetch = _method_source(MAIN, "MainWindow", "fetch_older_messages")
    loader = _method_source(CONV, "ConversationsPanel", "_load_older_messages_from_server")
    assert "confirmed_end_of_history = False" in fetch
    assert "return [] if confirmed_end_of_history else None" in fetch
    assert "if fetched is not None:" in loader
    assert "self._set_reached_start" in loader
    assert "self._clear_loading_more" in loader


def test_live_messages_before_first_sync_are_buffered_and_replayed():
    init = _method_source(MAIN, "MainWindow", "__init__")
    on_new = _method_source(MAIN, "MainWindow", "on_new_message")
    start_sync = _method_source(MAIN, "MainWindow", "start_sync")
    assert "self._early_live_messages = []" in init
    assert "pending.append(msg)" in on_new
    assert "del pending[:-500]" in on_new
    assert "early_live = list" in start_sync
    assert "wx.CallAfter(self.on_new_message, early_msg)" in start_sync


def test_read_ack_is_sent_to_every_known_jid_alias():
    src = _method_source(MAIN, "MainWindow", "mark_conversation_as_read")
    assert "candidates = []" in src
    assert "_lid_to_phone" in src
    assert "_phone_to_lid" in src
    assert "for phone in candidates:" in src
    assert 'payload["isLid"] = True' in src


def test_document_gauge_is_made_visible_before_enqueue_worker_starts():
    send = _method_source(CONV, "ConversationsPanel", "_on_send_attachment")
    show_at = send.index('if media_type == "document":\n                self._show_media_transfer_gauge()')
    worker_at = send.index("threading.Thread(target=_cache_then_enqueue, daemon=True).start()")
    assert show_at < worker_at


def test_gauge_visibility_toggles_the_sizer_item_and_forces_repaint():
    src = _method_source(CONV, "ConversationsPanel", "_set_media_transfer_gauge_visible")
    assert "sizer.Show(gauge, visible" in src
    assert "self.conversation_panel.Layout()" in src
    assert "self.conversation_panel.Refresh()" in src
    assert "self.conversation_panel.Update()" in src
