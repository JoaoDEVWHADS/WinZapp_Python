"""What the macOS layer (macos/winzapp_mac) relies on in WinZapp still exists.

The Mac build does not edit WinZapp's files: it replaces functions and
methods at startup (``WppServerMixin._stop_wpp_server = stop``) and reads
others (``lf._translate_pattern``). Renaming or removing one of those names
breaks only the Mac build, and only when it runs — Windows CI would stay
green. These checks run on every platform and read the layer's source
without importing it (it needs PyObjC), so the rename fails here instead.

The layer is read with ``ast``: every WinZapp module it imports, every
module-level name and class attribute it reaches through those imports
(also through a local alias such as ``cls = wpp_server.WppServerMixin``) is
looked up in client/'s source. The layer must therefore name its targets
literally — a ``setattr(owner, name, ...)`` over a list of names cannot be
checked and is refused below.

The same goes for text: every literal key the layer passes to ``t()`` must
exist, and every Mac variant (``<key>_macos``, used in place of ``<key>`` on
the Mac) must have its Windows key and the same placeholders.
"""

import ast
import json
import pathlib
import re
import string

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CLIENT = _ROOT / "client"
_LAYER = _ROOT / "macos" / "winzapp_mac"
from tests.locales import load_strings, registered_locale_codes

_LOCALES = registered_locale_codes()
_MAC_SUFFIX = "_macos"

pytestmark = pytest.mark.skipif(not _LAYER.is_dir(), reason="no macOS layer in this checkout")


# ------------------------------------------------------------------ client source --

def _module_file(dotted):
    """client/ source file of module *dotted*, or None when it is not WinZapp's."""
    base = _CLIENT.joinpath(*dotted.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


_TREES = {}


def _tree(path):
    if path not in _TREES:
        _TREES[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _TREES[path]


def _bound_names(body):
    """Names a module or class body binds, looking into if/try/with blocks
    but not into functions."""
    names = {}
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        names[sub.id] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names[(alias.asname or alias.name).split(".")[0]] = node
        elif isinstance(node, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
            for field in ("body", "orelse", "finalbody"):
                names.update(_bound_names(getattr(node, field, []) or []))
            for handler in getattr(node, "handlers", []) or []:
                names.update(_bound_names(handler.body))
    return names


def _module_globals(path):
    """Module-level names, plus names functions declare ``global`` and assign."""
    tree = _tree(path)
    names = dict(_bound_names(tree.body))
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            for name in node.names:
                names.setdefault(name, node)
    return names


def _class_has(module, cls_node, attr, seen=frozenset()):
    """True when class *cls_node* (defined in *module*) or one of its bases
    that WinZapp defines has *attr*. A base from outside WinZapp (wx.Panel,
    ...) is not read; it can only supply wx's own CamelCase API
    (``SetLabel``), never a snake_case WinZapp method like ``init_UI``."""
    if attr in _bound_names(cls_node.body):
        return True
    for base in cls_node.bases:
        resolved = _resolve_class(module, base)
        if resolved is None:
            if attr[:1].isupper():
                return True                 # wx API on a base outside WinZapp
            continue
        key = (resolved[0], resolved[1].name)
        if key not in seen and _class_has(resolved[0], resolved[1], attr, seen | {key}):
            return True
    return False


def _resolve_class(module, expr):
    """(module, ClassDef) of a base-class expression, or None when it is not
    a class WinZapp defines."""
    path = _module_file(module)
    if isinstance(expr, ast.Name):
        node = _module_globals(path).get(expr.id)
        if isinstance(node, ast.ClassDef):
            return module, node
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                if (alias.asname or alias.name) == expr.id and _module_file(node.module):
                    target = _module_globals(_module_file(node.module)).get(alias.name)
                    if isinstance(target, ast.ClassDef):
                        return node.module, target
    elif isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        node = _module_globals(path).get(expr.value.id)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name) != expr.value.id:
                    continue
                mod = alias.name if isinstance(node, ast.Import) else f"{node.module}.{alias.name}"
                if _module_file(mod):
                    target = _module_globals(_module_file(mod)).get(expr.attr)
                    if isinstance(target, ast.ClassDef):
                        return mod, target
    return None


def _missing(module, parts):
    """Why ``module.parts[0].parts[1]`` does not exist in client/, or ""."""
    path = _module_file(module)
    if not parts:
        return ""
    if _module_file(f"{module}.{parts[0]}"):          # a submodule
        return _missing(f"{module}.{parts[0]}", parts[1:])
    node = _module_globals(path).get(parts[0])
    if node is None:
        return f"{module}.{parts[0]} is not defined"
    if len(parts) > 1 and isinstance(node, ast.ClassDef):
        if not _class_has(module, node, parts[1]):
            return f"{module}.{parts[0]} has no attribute {parts[1]}"
    return ""


# ------------------------------------------------------------------- layer source --

class _References(ast.NodeVisitor):
    """Every (module, attribute path, line) the layer reaches in WinZapp."""

    def __init__(self):
        self.aliases = {}       # local name -> (module, [attr, ...])
        self.refs = []
        self.dynamic = []

    def visit_Import(self, node):
        for alias in node.names:
            if _module_file(alias.name):
                if alias.asname:
                    self.aliases[alias.asname] = (alias.name, [])
                elif "." not in alias.name:
                    self.aliases[alias.name] = (alias.name, [])

    def visit_ImportFrom(self, node):
        if node.level or not node.module:
            return
        for alias in node.names:
            local = alias.asname or alias.name
            if _module_file(f"{node.module}.{alias.name}"):
                self.aliases[local] = (f"{node.module}.{alias.name}", [])
            elif _module_file(node.module):
                self.aliases[local] = (node.module, [alias.name])
                self.refs.append((node.module, [alias.name], node.lineno))

    def _chain(self, node):
        """(module, parts) for ``alias.a.b`` rooted at a WinZapp alias."""
        attrs = []
        while isinstance(node, ast.Attribute):
            attrs.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name) and node.id in self.aliases:
            module, parts = self.aliases[node.id]
            return module, parts + attrs[::-1]
        return None

    def visit_Assign(self, node):
        chain = self._chain(node.value)
        if chain and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            self.aliases[node.targets[0].id] = chain
        self.generic_visit(node)

    def visit_Attribute(self, node):
        chain = self._chain(node)
        if chain:
            self.refs.append((chain[0], chain[1], node.lineno))
            return                                  # the inner prefixes add nothing
        self.generic_visit(node)

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Name) and node.func.id in ("setattr", "delattr")
                and node.args and self._chain(node.args[0])):
            name = node.args[1] if len(node.args) > 1 else None
            if isinstance(name, ast.Constant) and isinstance(name.value, str):
                module, parts = self._chain(node.args[0])
                self.refs.append((module, parts + [name.value], node.lineno))
            else:
                self.dynamic.append(node.lineno)
        self.generic_visit(node)


def _layer_files():
    return sorted(p for p in _LAYER.glob("*.py"))


def _scan(path):
    visitor = _References()
    visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return visitor


def test_the_scan_sees_the_layers_patches():
    """Guards the guard: if the scan stopped resolving imports or aliases,
    every check below would pass on nothing."""
    found = {(m, ".".join(p)) for f in _layer_files() for m, p, _ in _scan(f).refs}
    assert ("main_window.wpp_server", "WppServerMixin._stop_wpp_server") in found
    assert ("core.locale_format", "_windows_date_strftime") in found
    assert ("ui.conversations", "ConversationsPanel.init_UI") in found
    assert len(found) > 40


def test_a_renamed_target_is_reported():
    assert _missing("main_window.wpp_server", ["WppServerMixin", "_stop_wpp_server"]) == ""
    assert _missing("main_window.wpp_server", ["WppServerMixin", "_stop_wpp_server_renamed"])
    assert _missing("core.locale_format", ["_windows_date_strftime_renamed"])
    # A wx base class does not hide a missing WinZapp method.
    assert _missing("ui.conversations", ["ConversationsPanel", "init_UI"]) == ""
    assert _missing("ui.conversations", ["ConversationsPanel", "init_UI_renamed"])


@pytest.mark.parametrize("path", _layer_files(), ids=lambda p: p.name)
def test_everything_the_layer_patches_or_reads_still_exists(path):
    problems = []
    for module, parts, line in _scan(path).refs:
        why = _missing(module, parts)
        if why:
            problems.append(f"{path.name}:{line}: {why}")
    assert not problems, (
        "The macOS layer relies on names WinZapp no longer has (renamed or "
        "removed?). Update macos/winzapp_mac to the new name:\n" + "\n".join(problems)
    )


@pytest.mark.parametrize("path", _layer_files(), ids=lambda p: p.name)
def test_the_layer_names_its_targets_literally(path):
    lines = _scan(path).dynamic
    assert not lines, (
        f"{path.name} lines {lines}: setattr() on a WinZapp object with a computed "
        "name cannot be checked here; assign each target explicitly."
    )


# --------------------------------------------------------------------------- text --

def _translations(locale):
    return load_strings(locale)


def _placeholders(text):
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def _has_mnemonic(text):
    """A wx mnemonic: "&" before a character, not "&&" nor "Privacy & Security"."""
    return bool(re.search(r"&[^&\s]", text.replace("&&", "")))


_T_CALL = re.compile(r"""\bt\(\s*["']([A-Za-z0-9_]+)["']\s*\)""")


def test_every_key_the_layer_asks_for_exists():
    keys = {k for f in _layer_files() for k in _T_CALL.findall(f.read_text(encoding="utf-8"))}
    assert keys, "the pattern no longer finds the layer's t() calls"
    for locale in _LOCALES:
        missing = sorted(keys - set(_translations(locale)))
        assert not missing, f"{locale}: {missing}"


@pytest.mark.parametrize("locale", _LOCALES)
def test_mac_variants_match_their_windows_key(locale):
    data = _translations(locale)
    for key, text in data.items():
        if not key.endswith(_MAC_SUFFIX):
            continue
        base = key[: -len(_MAC_SUFFIX)]
        assert base in data, f"{locale}: {key} has no {base} to stand in for"
        assert _placeholders(text) == _placeholders(data[base]), (locale, key)
        assert _has_mnemonic(text) == _has_mnemonic(data[base]), (
            f"{locale}: {key} and {base} disagree on having a mnemonic"
        )
        assert "Windows" not in text, (locale, key)
