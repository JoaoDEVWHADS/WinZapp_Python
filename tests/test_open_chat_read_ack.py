"""Opening a conversation must send the real WhatsApp seen ACK."""

import ast
from pathlib import Path

CONV = Path(__file__).resolve().parents[1] / "client" / "ui" / "conversations.py"


def _method_source(class_name: str, method_name: str) -> str:
    source = CONV.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == method_name:
                    return "\n".join(lines[item.lineno - 1:item.end_lineno])
    raise AssertionError(f"{class_name}.{method_name} not found")


def test_opening_chat_forces_remote_seen_even_when_local_count_is_zero():
    src = _method_source("ConversationsPanel", "navigate_to_conversation")
    assert "target=self.main_window.mark_conversation_as_read" in src
    assert "args=(jid, True)" in src
