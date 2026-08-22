"""Source-level checks for durable end-of-history handling.

An empty public getMessages page can be transient while the linked-device store
is warming.  It therefore takes repeated anchored empties to persist exhaustion,
and an explicit user scroll must always be able to challenge the cached result.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "client" / "main.py"


def _method_source(name: str) -> str:
    source = MAIN.read_text(encoding="utf-8")
    tree = ast.parse(source)
    lines = source.splitlines()
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MainWindow")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    return "\n".join(lines[node.lineno - 1:node.end_lineno])


def test_transient_empty_pages_need_six_confirmations():
    src = _method_source("fetch_older_messages")
    assert "if n < 6:" in src
    assert "(%d/6)" in src
    assert "after 6 empty pages" in src


def test_user_scroll_can_challenge_persisted_exhaustion():
    src = _method_source("fetch_older_messages")
    start = src.index('if remote_jid in getattr(self, "_exhausted_chats", set()):')
    early = src[start:src.index('if remote_jid.endswith("@g.us"):', start)]
    assert "if store_only:" in early
    assert "return []" in early
    assert "self._exhausted_chats.discard(remote_jid)" in early


def test_f5_resync_forgets_exhaustion_and_transient_counters():
    src = _method_source("_forget_history_exhaustion")
    assert "self._exhausted_chats = set()" in src
    assert 'getattr(self, "_older_empty_strikes", {}).clear()' in src
    assert 'getattr(self, "_deep_stalled_anchors", {}).clear()' in src
    assert "self._persist_exhausted_chats()" in src


def test_upgrade_invalidates_bad_v2_exhaustion_cache_once():
    src = MAIN.read_text(encoding="utf-8")
    assert 'history_exhaustion_semantics_v3' in src
    assert 'self.db.set_metadata_json("exhausted_chats", [])' in src
