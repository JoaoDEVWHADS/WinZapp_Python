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


def test_history_recovery_restarts_backend_before_page_reload():
    controller = (
        ROOT / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
    ).read_text(encoding="utf-8")
    restart_at = controller.index("cmd.restartBackend()")
    reload_at = controller.index("req.client.page.reload", restart_at)
    assert restart_at < reload_at
    assert "staleForMs >= 30_000" in controller
    assert "staleForMs >= 75_000" in controller


def test_live_whatsapp_web_is_default_with_opt_in_cached_pin():
    src = START.read_text(encoding="utf-8")
    assert "WINZAPP_WA_WEB_VERSION" in src
    assert "Using live WhatsApp Web (no HTML version pin)" in src
    assert "return undefined;" in src


def test_periodic_poll_recovers_messages_when_live_event_is_missed():
    src = _method_source(MAIN, "MainWindow", "start_periodic_contacts_sync")
    assert "before_activity" in src
    assert "now_t > old_t" in src
    assert "self.sync_chat_messages(current)" in src
    assert "len(changed) >= 6" in src


def test_temporary_empty_older_page_does_not_mean_reached_start():
    fetch = _method_source(MAIN, "MainWindow", "fetch_older_messages")
    loader = _method_source(CONV, "ConversationsPanel", "_load_older_messages_from_server")
    assert "confirmed_end_of_history = False" in fetch
    assert "return [] if confirmed_end_of_history else None" in fetch
    assert "if fetched is None:" in loader
    assert "keeping scroll re-queryable" in loader
    assert "wx.CallAfter(self._clear_loading_more, phone_jid_val)" in loader
    assert "elif fetched:" in loader
    assert "wx.CallAfter(self._on_older_messages_loaded, fetched, phone_jid_val)" in loader
    assert "else:" in loader
    assert "wx.CallAfter(self._set_reached_start, phone_jid_val)" in loader
    assert loader.count("wx.CallAfter(self._set_reached_start, phone_jid_val)") == 1
    assert loader.count("wx.CallAfter(self._clear_loading_more, phone_jid_val)") >= 2


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


def test_attachment_gauge_waits_for_real_transfer_progress():
    send = _method_source(CONV, "ConversationsPanel", "_on_send_attachment")
    progress = _method_source(CONV, "ConversationsPanel", "update_media_upload_progress")
    assert "self._show_media_transfer_gauge()" not in send
    assert "self._media_transfer_started.add(upload_id)" in progress
    assert "self._update_media_transfer_gauge(progress)" in progress


def test_gauge_visibility_toggles_the_sizer_item_and_forces_repaint():
    src = _method_source(CONV, "ConversationsPanel", "_set_media_transfer_gauge_visible")
    assert "sizer.Show(gauge, visible" in src
    assert "self.conversation_panel.Layout()" in src
    assert "self.conversation_panel.Refresh()" in src
    assert "self.conversation_panel.Update()" in src


def test_native_gauge_uses_the_same_laid_out_slot_as_media_actions():
    src = CONV.read_text(encoding="utf-8")
    assert "self._media_action_slot = wx.Panel(self.conversation_panel)" in src
    assert "self._media_transfer_gauge = _FocusedTransferGauge(\n            self._media_action_slot," in src
    assert "self._action_open_btn = wx.Button(\n            self._media_action_slot," in src
    assert "self._action_save_as_btn = wx.Button(\n            self._media_action_slot," in src
    assert "sizer = gauge.GetContainingSizer()" in src


def test_progress_output_is_exposed_only_while_native_gauge_has_focus():
    src = CONV.read_text(encoding="utf-8")
    assert "class _FocusedTransferGaugeAccessible(wx.Accessible):" in src
    assert "if self._gauge.HasFocus():" in src
    assert "state |= wx.ACC_STATE_SYSTEM_INVISIBLE" in src
    assert "def AcceptsFocusFromKeyboard(self):" in src


def test_empty_media_action_slot_is_removed_from_layout():
    init = _method_source(CONV, "ConversationsPanel", "init_UI")
    sync = _method_source(CONV, "ConversationsPanel", "_sync_media_action_slot_visibility")
    assert "self._media_action_slot.Hide()" in init
    assert "slot.Show(visible)" in sync
    assert "outer.Show(slot, visible" in sync


def test_get_messages_merges_outgoing_tail_after_last_received_anchor():
    controller = (
        ROOT / "client" / "api_patches" / "src" / "controller" / "deviceController.ts"
    ).read_text(encoding="utf-8")
    assert "const isPrivateChat" in controller
    assert "if (tailAnchor && isPrivateChat)" in controller
    assert "direction: 'after'" in controller
    assert "id: String(tailAnchor)" in controller
    assert "result.push(...tail)" in controller
    assert "result = result.filter" in controller
    assert "seen.has(serialized)" in controller
