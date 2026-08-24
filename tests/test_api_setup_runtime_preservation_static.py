"""Static session-preservation contract for WPPConnect reinstall."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_SETUP = ROOT / "client" / "ui" / "dialogs" / "api_setup.py"


def test_runtime_keep_set_contains_current_and_legacy_token_stores():
    tree = ast.parse(API_SETUP.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "_KEEP_RUNTIME" for t in node.targets):
                values = ast.literal_eval(node.value)
                assert {"tokens", "wppconnect_tokens", "userDataDir"} <= set(values)
                return
    raise AssertionError("_KEEP_RUNTIME not found")
