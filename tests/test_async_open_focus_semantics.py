from pathlib import Path
import ast


ROOT = Path(__file__).resolve().parents[1]
CONVERSATIONS = ROOT / "client" / "ui" / "conversations.py"


def _method_source(name: str) -> str:
    source = CONVERSATIONS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"method {name!r} not found")


def test_async_db_apply_restores_unread_or_last_landing_semantics():
    src = _method_source("_apply_conversation_db_load")
    assert 'get("focus_on_open", "message_field")' in src
    assert 'focus_setting == "unread_or_last"' in src
    assert "self.populate_messages(preserve_focus=False)" in src
    assert "wx.CallAfter(self.messages_list.SetFocus)" in src



def test_async_db_apply_does_not_steal_message_field_focus():
    src = _method_source("_apply_conversation_db_load")
    assert "wx.CallAfter(self.message_field.SetFocus)" in src
    # Guard against the regression that always treated first DB completion as
    # a preserve-focus background refresh regardless of the open-focus mode.
    assert "self.populate_messages(preserve_focus=True)" not in src
