import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from core.node_compile_cache import cache_environment


def test_child_cache_is_persistent_and_parent_environment_is_unchanged(tmp_path):
    original = {"AUTHENTICATION_API_KEY": "private", "PATH": "node"}
    cache = tmp_path / "data" / "global" / "node-compile-cache"
    child = cache_environment(original, str(cache))
    assert cache.is_dir() and child["NODE_COMPILE_CACHE"] == str(cache)
    assert "NODE_COMPILE_CACHE" not in original
    assert child["AUTHENTICATION_API_KEY"] == "private"


def test_explicit_cache_is_respected(tmp_path):
    child = cache_environment({"NODE_COMPILE_CACHE": "custom"}, str(tmp_path / "unused"))
    assert child["NODE_COMPILE_CACHE"] == "custom" and not (tmp_path / "unused").exists()


def test_unwritable_cache_does_not_prevent_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("denied")))
    assert cache_environment({"PATH": "node"}, str(tmp_path)) == {"PATH": "node"}


def test_node_flush_persists_cache_without_starting_api(tmp_path):
    root = Path(__file__).resolve().parents[1]
    node = root / ("client/node/node.exe" if sys.platform == "win32" else "client/node/node")
    executable = str(node) if node.is_file() else shutil.which("node")
    if not executable:
        pytest.skip("Node unavailable")
    (tmp_path / "sample.js").write_text("module.exports = 42;")
    cache = tmp_path / "cache"
    environment = cache_environment(os.environ, str(cache))
    environment["NODE_COMPILE_CACHE"] = str(cache)
    environment.pop("NODE_DISABLE_COMPILE_CACHE", None)
    script = "const m=require('node:module'); if(!m.flushCompileCache) process.exit(77); require('./sample.js'); m.flushCompileCache();"
    result = subprocess.run([executable, "-e", script], cwd=tmp_path, env=environment,
                            capture_output=True, text=True, timeout=20,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode == 77:
        pytest.skip("Node lacks compile-cache API")
    assert result.returncode == 0, result.stderr
    assert any(p.is_file() for p in cache.rglob("*"))
