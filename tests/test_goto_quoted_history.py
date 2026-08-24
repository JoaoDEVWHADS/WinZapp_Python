"""Regression coverage for quoted-message navigation outside the visible page."""

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "client/ui/conversations.py"


def _method_source(name: str) -> str:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ConversationsPanel")
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    return "\n".join(lines[method.lineno - 1:method.end_lineno])


def test_goto_quoted_loads_message_from_database_before_reporting_failure():
    source = _method_source("_on_menu_goto_quoted")
    lookup = source.index("self.main_window.db.get_message")
    failure = source.rindex("self._show_quoted_not_found_error")
    assert lookup < failure
    assert "self.populate_messages(preserve_focus=True)" in source
    assert "self.messages_list.EnsureVisible" in source


def test_goto_quoted_keeps_status_fallback_after_database_lookup():
    source = _method_source("_on_menu_goto_quoted")
    assert source.index("self.main_window.db.get_message") < source.index("self._goto_quoted_status")
