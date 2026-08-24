"""wx-independent contracts for backup behaviours restored after regressions."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client" / "main.py"
CONNECT = ROOT / "client" / "ui" / "dialogs" / "connect.py"
UPDATER = ROOT / "client" / "updater.py"
CONFIG = ROOT / "client" / "config.py"
SENDER = ROOT / "client" / "core" / "wppconnect_sender_layer_patch.py"


def _method(path: Path, cls: str, method: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == method:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{cls}.{method} not found")


def test_history_request_understands_server_state_contract():
    source = _method(MAIN, "MainWindow", "request_older_messages")
    assert 'payload.get("inFlight")' in source
    assert 'payload.get("endOfHistoryTransferType") == 1' in source
    assert 'payload.get("initialHistoryIncomplete") is True' in source
    assert '_older_request_confirmed_end' in source


def test_deep_backfill_is_passive_at_phone_boundary():
    source = _method(MAIN, "MainWindow", "deep_backfill_chat")
    assert "allow_phone_request=False" in source
    assert "request_older_messages(" not in source


def test_large_file_patch_restores_whatsapp_browser_limit():
    source = SENDER.read_text(encoding="utf-8")
    assert "WPP.whatsapp?.MediaGatingUtils" in source
    assert "1 * 1024 * 1024 * 1024" in source


def test_pairing_has_local_hash_fallback_without_restoring_long_create_timeout():
    source = CONNECT.read_text(encoding="utf-8")
    assert "hmac.new(" in source
    assert "hashlib.sha256" in source
    assert "for attempt, timeout in enumerate((3, 5)" in source
    assert "timeout=15" in source
    create_instance = _method(CONNECT, "Connect", "_create_instance")
    assert "timeout=90" not in create_instance


def test_update_checker_methods_are_really_members_of_the_class():
    for method in (
        "_alpha_enabled", "_fetch_releases", "_show_update_dialog",
        "_do_install", "_schedule_retry", "stop",
    ):
        _method(UPDATER, "UpdateChecker", method)


def test_update_checker_merges_listing_and_stable_endpoint():
    config = CONFIG.read_text(encoding="utf-8")
    updater = _method(UPDATER, "UpdateChecker", "_fetch_releases")
    assert "GITHUB_API_LATEST_STABLE_RELEASE" in config
    assert 'f"https://api.github.com/repos/{GITHUB_REPO}/releases"' in config
    assert "GITHUB_API_LATEST_RELEASE" in updater
    assert "GITHUB_API_LATEST_STABLE_RELEASE" in updater
