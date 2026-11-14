"""The running version of a Mac release is its release tag (version_mac),
not the unstamped client/version.py of the tag's checkout."""

import ast
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import version  # noqa: E402
from winzapp_mac import updater_mac as um, version_mac  # noqa: E402

PLACEHOLDER = "2.1.0.0"
TAGGED = {"WinZappReleaseTag": "v2.1.0.4050alpha"}


@pytest.fixture
def unstamped(monkeypatch):
    monkeypatch.setattr(version, "__version__", PLACEHOLDER)
    monkeypatch.setattr(sys, "frozen", True, raising=False)


def test_a_release_build_runs_as_its_tag(monkeypatch, unstamped):
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    version_mac.install()
    assert version.__version__ == "2.1.0.4050alpha"


def test_the_updater_no_longer_offers_the_running_release(monkeypatch, unstamped):
    """The bug: UpdateChecker compares the latest release against the copy
    of __version__ updater bound at import, so an unstamped 2.1.0.0 saw its
    own release as newer on every check. Checked on that copy, as imported
    after version_mac.install(), not on version.__version__."""
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    # setitem records the original module, or its absence, for teardown;
    # delitem would record nothing when updater was not imported yet.
    monkeypatch.setitem(sys.modules, "updater", None)
    del sys.modules["updater"]
    version_mac.install()
    import updater
    assert updater.__version__ == "2.1.0.4050alpha"
    assert not updater.is_newer("2.1.0.4050alpha", updater.__version__)


@pytest.mark.parametrize("info", [{}, {"WinZappReleaseTag": ""},
                                  {"WinZappReleaseTag": "2.1.0.5"},
                                  {"WinZappReleaseTag": "not a tag"}])
def test_a_build_without_a_valid_tag_keeps_version_py(monkeypatch, unstamped, info):
    monkeypatch.setattr(um, "_info", lambda: info)
    version_mac.install()
    assert version.__version__ == PLACEHOLDER


def test_running_from_source_keeps_version_py(monkeypatch, unstamped):
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(um, "_info", lambda: TAGGED)
    version_mac.install()
    assert version.__version__ == PLACEHOLDER


def test_installed_before_the_modules_that_copy_the_version(monkeypatch):
    """`from version import __version__` binds a copy at import, so the
    swap must come right after paths_mac, before any install() that imports
    WinZapp modules."""
    import importlib
    import pkgutil
    import winzapp_mac
    order = []
    for info in pkgutil.iter_modules(winzapp_mac.__path__):
        mod = importlib.import_module(f"winzapp_mac.{info.name}")
        if callable(getattr(mod, "install", None)):
            monkeypatch.setattr(mod, "install", lambda name=info.name: order.append(name))
    winzapp_mac.install()
    assert order[:2] == ["paths_mac", "version_mac"]


def _top_level_imports(body):
    """Modules a module body imports when it is imported: if/try/with blocks
    included, function and class bodies not."""
    for node in body:
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module
        elif isinstance(node, (ast.If, ast.Try, ast.With)):
            for field in ("body", "orelse", "finalbody"):
                yield from _top_level_imports(getattr(node, field, []) or [])
            for handler in getattr(node, "handlers", []) or []:
                yield from _top_level_imports(handler.body)


def test_no_layer_module_copies_the_version_on_import():
    """winzapp_mac/__init__.py imports every layer module before
    version_mac.install() runs: one that imported version, updater, main or
    main_window at module level would bind the placeholder version first."""
    layer = os.path.join(ROOT, "macos", "winzapp_mac")
    found = []
    for name in sorted(os.listdir(layer)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(layer, name), encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=name)
        for module in _top_level_imports(tree.body):
            if module.split(".")[0] in ("version", "updater", "main", "main_window"):
                found.append(f"{name}: {module}")
    assert found == []
