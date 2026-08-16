"""Regression checks for network calls that run during connection setup."""

import ast
from pathlib import Path


def test_connect_dialog_requests_have_timeouts():
    source = Path("client/ui/dialogs/connect.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls_without_timeout = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if not isinstance(owner, ast.Name) or owner.id != "requests":
            continue
        if node.func.attr not in {"get", "post", "put", "patch", "delete", "request"}:
            continue
        if not any(keyword.arg == "timeout" for keyword in node.keywords):
            calls_without_timeout.append(node.lineno)

    assert calls_without_timeout == []
