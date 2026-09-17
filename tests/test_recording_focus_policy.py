import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _method_source(relative: str, class_name: str, method_name: str) -> str:
    source = (ROOT / relative).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)) and member.name == method_name:
                    return ast.get_source_segment(source, member) or ""
    raise AssertionError(f"{class_name}.{method_name} not found in {relative}")


@pytest.mark.parametrize(
    ("relative", "class_name"),
    [
        ("client/ui/conversations.py", "ConversationsPanel"),
        ("client/status_panel.py", "StatusPanel"),
    ],
)
def test_silent_recording_does_not_manufacture_send_focus_event(relative, class_name):
    method = _method_source(relative, class_name, "_focus_recording_button_silently")

    assert "if self._voice_recording_focus_suppression_enabled():" in method
    assert "return False" in method
    assert method.count("button.SetFocus()") == 1
    assert method.index("return False") < method.index("button.SetFocus()")
    assert "cloak_focus_announcement" not in method
