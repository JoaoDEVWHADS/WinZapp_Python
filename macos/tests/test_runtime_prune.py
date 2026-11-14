"""Leaving the server's development packages out of the bundled runtime
(macos/runtime_prune.py).

The measured trap this guards: `npm prune --omit=dev` on the 2.1.0 runtime
trusted the lockfile's "dev" flags and deleted @babel/runtime, mongoose,
redis, crypto-js and prom-client, all required by dist/. Here a lockfile
says exactly that, and the package dist/ requires must survive.
"""

import json
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS build")

import build_app  # noqa: E402
import runtime_prune  # noqa: E402

NODE = shutil.which("node")


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _package(api, path, deps=None):
    _write(os.path.join(api, *path.split("/"), "package.json"),
           json.dumps({"name": path.rsplit("node_modules/", 1)[-1], "version": "1.0.0",
                       "main": "index.js", "dependencies": deps or {}}))
    _write(os.path.join(api, *path.split("/"), "index.js"), "module.exports = 1;")


def _api(tmp_path):
    """express (runtime) -> body-parser; @babel/runtime is a devDependency
    the lockfile flags dev though dist/ requires it; eslint is dev only and
    holds a nested copy of body-parser; jest is required by dist/tests only."""
    api = str(tmp_path / "api")
    lock = {"": {"dependencies": {"express": "^4"},
                 "devDependencies": {"@babel/runtime": "^7", "eslint": "^9", "jest": "^29"}},
            "node_modules/express": {"dependencies": {"body-parser": "^1"}},
            "node_modules/body-parser": {},
            "node_modules/@babel/runtime": {"dev": True},
            "node_modules/eslint": {"dev": True, "dependencies": {"body-parser": "^2"}},
            "node_modules/eslint/node_modules/body-parser": {"dev": True},
            "node_modules/jest": {"dev": True}}
    for path, entry in lock.items():
        if path:
            _package(api, path, entry.get("dependencies"))
    _write(os.path.join(api, "package.json"), json.dumps(
        {"name": "api", "version": "2.8.0", "dependencies": {"express": "^4"},
         "devDependencies": {"@babel/runtime": "^7", "eslint": "^9", "jest": "^29"},
         "scripts": {"prepare": "husky install"}}))
    _write(os.path.join(api, "package-lock.json"), json.dumps({"lockfileVersion": 3, "packages": lock}))
    _write(os.path.join(api, "dist", "server.js"),
           "var _x = require(\"@babel/runtime/helpers/interopRequireDefault\");\n"
           "var e = require('express');\n"
           "page.evaluate(() => window.require('WAWebMobilePlatforms'));\n"
           "var p = require('path'); var f = require('node:fs'); var r = require('./util');\n")
    _write(os.path.join(api, "dist", "tests", "server.test.js"), "require('jest');")
    _write(os.path.join(api, "start.js"), "require('express');")
    os.makedirs(os.path.join(api, "node_modules", ".bin"))
    os.symlink("../eslint/index.js", os.path.join(api, "node_modules", ".bin", "eslint"))
    os.symlink("../express/index.js", os.path.join(api, "node_modules", ".bin", "express"))
    _write(os.path.join(api, "node_modules", ".package-lock.json"), "{}")
    return api


def test_entry_imports_are_the_servers_node_packages(tmp_path):
    assert runtime_prune.entry_imports(_api(tmp_path)) == {"@babel/runtime", "express", "path"}


def test_nested_copies_resolve_the_way_node_does():
    lock = {"packages": {"": {}, "node_modules/a": {"dependencies": {"b": "2"}},
                         "node_modules/a/node_modules/b": {"dependencies": {"c": "1"}},
                         "node_modules/b": {}, "node_modules/c": {},
                         "node_modules/d": {"peerDependencies": {"missing": "1"},
                                            "optionalDependencies": {"gone": "1"}}}}
    keep = runtime_prune.runtime_closure(lock, {"a", "d"})
    assert keep == {"node_modules/a", "node_modules/a/node_modules/b", "node_modules/c",
                    "node_modules/d"}
    assert runtime_prune.removable(lock, keep) == ["node_modules/b"]


def test_a_kept_package_is_never_inside_a_removed_one():
    lock = {"packages": {"node_modules/x": {}, "node_modules/x/node_modules/y": {}}}
    assert runtime_prune.removable(lock, {"node_modules/x/node_modules/y"}) == []
    assert runtime_prune.removable(lock, set()) == ["node_modules/x"]


@pytest.mark.skipif(not NODE, reason="needs node")
def test_dev_packages_go_and_what_dist_requires_stays(tmp_path):
    api = _api(tmp_path)
    removed, missing = runtime_prune.prune_dev_modules(api, NODE)
    nm = os.path.join(api, "node_modules")
    assert missing == []
    assert removed == 2
    for kept in ("express", "body-parser", os.path.join("@babel", "runtime")):
        assert os.path.isfile(os.path.join(nm, kept, "index.js")), kept
    assert not os.path.exists(os.path.join(nm, "eslint"))
    assert not os.path.exists(os.path.join(nm, "jest"))
    assert sorted(os.listdir(os.path.join(nm, ".bin"))) == ["express"]
    assert not os.path.exists(os.path.join(nm, ".package-lock.json"))
    # The same manifest an end user's npm install gets on Windows.
    manifest = json.load(open(os.path.join(api, "package.json")))
    assert "@babel/runtime" in manifest["dependencies"]
    assert "prepare" not in manifest["scripts"]


@pytest.mark.skipif(not NODE, reason="needs node")
def test_a_package_dist_needs_but_nobody_installed_is_reported(tmp_path):
    api = _api(tmp_path)
    shutil.rmtree(os.path.join(api, "node_modules", "express"))
    _, missing = runtime_prune.prune_dev_modules(api, NODE)
    assert missing == ["express"]


def test_unknown_install_scripts_keep_everything(tmp_path):
    api = _api(tmp_path)
    manifest = json.load(open(os.path.join(api, "package.json")))
    manifest["scripts"]["postinstall"] = "node fetch-things.js"
    _write(os.path.join(api, "package.json"), json.dumps(manifest))
    assert runtime_prune.prune_dev_modules(api, NODE or "node") == (0, [])
    assert os.path.isdir(os.path.join(api, "node_modules", "eslint"))


def test_the_build_stops_when_the_pruned_runtime_cannot_load(tmp_path, monkeypatch):
    node_dir = tmp_path / "node"
    _write(str(node_dir / "bin" / "node"), "#!node")
    os.makedirs(node_dir / "lib" / "node_modules" / "npm")
    client = tmp_path / "client"
    _write(str(client / "api" / "start.js"))
    monkeypatch.setattr(build_app, "APP", str(tmp_path / "WinZapp.app"))
    monkeypatch.setattr(build_app, "CLIENT", str(client))
    monkeypatch.setattr(build_app.runtime_prune, "prune_dev_modules", lambda api, node: (3, ["mongoose"]))
    with pytest.raises(SystemExit, match="mongoose"):
        build_app.bundle_runtime(str(node_dir))


def test_build_app_loads_by_path_without_its_directory_on_sys_path(monkeypatch):
    """appcast.py's sign_update_tool() loads build_app.py by file path, where
    the script's own directory is not on sys.path: its runtime_prune import
    must still resolve."""
    import importlib.util
    import os
    import sys

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    monkeypatch.setattr(sys, "path", [p for p in sys.path if os.path.abspath(p or ".") != here])
    monkeypatch.delitem(sys.modules, "runtime_prune", raising=False)
    spec = importlib.util.spec_from_file_location("build_app_by_path", os.path.join(here, "build_app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.runtime_prune.__file__.startswith(here)
