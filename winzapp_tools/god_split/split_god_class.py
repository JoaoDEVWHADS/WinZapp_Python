"""Mechanical, verbatim split of a god class into mixin modules.

Usage: python winzapp_tools/god_split/split_god_class.py <config.py>

This is how client/main.py and client/ui/conversations.py were split (their
configs sit next to this file). It moves every class member verbatim — with
the comment lines above it — into the mixin module its anchor names, moves
the listed module-level defs into helper modules, computes each new module's
imports from the names its code actually uses, and rewrites the god file to
re-export the helpers and inherit from the mixins. It overwrites the god file
in place: run it on a clean tree, then verify with verify_split.py (AST
identity against the base ref) and verify_imports.py, then the full suite.

What it deliberately does NOT do, so a human decides it: rewrite
``<GodClass>.x`` references into ``<OwnerMixin>.x`` inside helper modules
(the config's POST hooks do that, one reviewed case at a time), or make any
change that is not movement.

The config module defines:
  SRC          path of the god file (relative to repo root)
  CLASS        name of the god class
  PKG          dotted package the mixins go into (e.g. "main_window")
  PKG_DIR      directory of that package
  IMPORT_PREFIX  how sibling modules are imported from inside the package
  ANCHORS      list of (method_name, module_or_KEEP) in file order
  MODULE_DEFS  {top-level name: helper module} for module-level defs to move
  MIXIN_NAMES  {module: MixinClassName}
  MIXIN_DOCS   {module: docstring}
  HELPER_DOCS  {helper module: docstring}
  FILE_FIX     optional {module: [(old, new), ...]} textual fixes
  MIXIN_ORDER  list of modules in MRO order
"""
import ast
import builtins
import importlib.util
import os
import re
import sys
import textwrap
from collections import OrderedDict, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

cfg_path = sys.argv[1]
spec = importlib.util.spec_from_file_location("cfg", cfg_path)
cfg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cfg)

src_path = os.path.join(ROOT, cfg.SRC)
src = open(src_path, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)


def seg_text(a, b):
    """1-based inclusive line range → text."""
    return "".join(lines[a - 1:b])


def node_start(n):
    decos = getattr(n, "decorator_list", None) or []
    return min([n.lineno] + [d.lineno for d in decos])


# ── Top-level: imports, defs ────────────────────────────────────────────────
dotted_imports = {}
import_bind = OrderedDict()   # name -> (module_key, import text for that one binding, conditional prefix)
toplevel_defs = OrderedDict()  # name -> node
class_node = None


def record_import(node, cond=None):
    if isinstance(node, ast.Import):
        for a in node.names:
            bound = a.asname or a.name.split(".")[0]
            text = f"import {a.name}" + (f" as {a.asname}" if a.asname else "")
            if not a.asname and "." in a.name:
                # `import wx.adv` also binds `wx`; keep the plain `import wx`
                # as the binding and emit the submodule only where it is used.
                dotted_imports.setdefault(bound, []).append(a.name)
                if bound in import_bind:
                    continue
            import_bind[bound] = ("import", text, cond)
    elif isinstance(node, ast.ImportFrom):
        mod = "." * node.level + (node.module or "")
        for a in node.names:
            bound = a.asname or a.name
            import_bind[bound] = ("from", (mod, a.name, a.asname), cond)


for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        record_import(node)
    elif isinstance(node, ast.If) and all(isinstance(x, (ast.Import, ast.ImportFrom)) for x in node.body) and not node.orelse:
        cond = ast.get_source_segment(src, node.test)
        for x in node.body:
            record_import(x, cond)
    elif isinstance(node, ast.Try) and all(isinstance(x, (ast.Import, ast.ImportFrom)) for x in node.body):
        # try: import optional_dep / except ImportError: optional_dep = None
        # — reproduced verbatim (comments included) wherever the name is used.
        raw = seg_text(node.lineno, node.end_lineno).rstrip("\n")
        for x in node.body:
            for a in x.names:
                import_bind[a.asname or a.name.split(".")[0]] = ("raw", raw, None)
    elif isinstance(node, ast.ClassDef) and node.name == cfg.CLASS:
        class_node = node
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        toplevel_defs[node.name] = node
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            for n in ast.walk(t):
                if isinstance(n, ast.Name):
                    toplevel_defs[n.id] = node

assert class_node is not None

# ── Module-level segments that move to helper modules ───────────────────────
# Each moved top-level node takes with it the comment lines directly above it
# (back to the previous top-level node's end).
top_nodes = tree.body
helper_segments = defaultdict(list)   # helper -> [(start, end)]
moved_top_ranges = []
for i, node in enumerate(top_nodes):
    names = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        names = [node.name]
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        names = [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]
    dest = {cfg.MODULE_DEFS.get(n) for n in names} - {None}
    if not dest:
        continue
    assert len(dest) == 1, (names, dest)
    dest = dest.pop()
    prev_end = top_nodes[i - 1].end_lineno if i else 0
    start = node_start(node)
    # take comment lines immediately above (stop at a blank-line gap of 2+?)
    s = start
    while s - 1 > prev_end and lines[s - 2].strip().startswith("#"):
        s -= 1
    helper_segments[dest].append((s, node.end_lineno))
    moved_top_ranges.append((s, node.end_lineno))

helper_of = {}  # name -> helper module
for name, h in cfg.MODULE_DEFS.items():
    helper_of[name] = h
unknown = set(cfg.MODULE_DEFS) - set(toplevel_defs)
assert not unknown, unknown

# ── Class body segments ─────────────────────────────────────────────────────
body = class_node.body
seg = []  # (name_or_None, start, end, is_def)
prev_end = class_node.lineno  # the "class X(...):" line
for n in body:
    start = node_start(n)
    s = prev_end + 1
    name = getattr(n, "name", None)
    seg.append([name, s, n.end_lineno, isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))])
    prev_end = n.end_lineno
class_end = class_node.end_lineno

# assign modules by anchors
anchor_map = OrderedDict(cfg.ANCHORS)
assign_to = []
current = "KEEP"
names_seen = set()
for i, (name, s, e, is_def) in enumerate(seg):
    if is_def and name in anchor_map and name not in names_seen:
        current = anchor_map[name]
        # pull back contiguous preceding non-def statements (class constants)
        j = len(assign_to) - 1
        while j >= 0 and not seg[j][3]:
            assign_to[j] = current
            j -= 1
    if name:
        names_seen.add(name)
    assign_to.append(current)
missing = [a for a, _ in cfg.ANCHORS if a not in names_seen]
assert not missing, missing

# names defined per module (methods + class attrs)
member_owner = {}
for (name, s, e, is_def), mod in zip(seg, assign_to):
    node = body[seg.index([name, s, e, is_def])]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        member_owner.setdefault(node.name, set()).add(mod)
    elif isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for t in targets:
            for x in ast.walk(t):
                if isinstance(x, ast.Name):
                    member_owner.setdefault(x.id, set()).add(mod)
split_members = {k: v for k, v in member_owner.items() if len(v) > 1}
assert not split_members, split_members

mod_segments = defaultdict(list)
for (name, s, e, is_def), mod in zip(seg, assign_to):
    mod_segments[mod].append((s, e))


# ── Free-name analysis ─────────────────────────────────────────────────────
BUILTINS = set(dir(builtins))


def names_used(text):
    t = ast.parse(textwrap.dedent(text)) if text.strip() else ast.Module(body=[], type_ignores=[])
    out = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def class_prefix_fix(text, this_mod):
    """MainWindow.X → OwnerMixin.X (the god class name is not importable
    from inside the package — importing main from a mixin would re-run it)."""
    needed = set()

    def repl(m):
        attr = m.group(1)
        owners = member_owner.get(attr)
        if not owners:
            return m.group(0)
        owner = next(iter(owners))
        if owner == "KEEP":
            return m.group(0)
        needed.add(owner)
        return f"{cfg.MIXIN_NAMES[owner]}.{attr}"

    new = re.sub(rf"\b{cfg.CLASS}\.(\w+)", repl, text)
    return new, needed


def render_imports(used, this_mod, extra_mixins=(), code=""):
    out_plain = []
    out_from = OrderedDict()
    cond_lines = defaultdict(list)
    raw_blocks = []
    local = []
    used = set(used)
    for name in list(used):
        if name in import_bind and import_bind[name][2]:
            used |= names_used(import_bind[name][2])
    for name in sorted(used):
        if name in BUILTINS and name not in import_bind and name not in helper_of:
            continue
        if name in import_bind:
            kind, data, cond = import_bind[name]
            if kind == "raw":
                raw_blocks.append(data)
            elif kind == "import":
                line = data
                (cond_lines[cond].append(line) if cond else out_plain.append(line))
                for dotted in dotted_imports.get(name, []):
                    if (dotted + ".") in code and not cond:
                        out_plain.append(f"import {dotted}")
            else:
                mod, orig, asname = data
                piece = orig + (f" as {asname}" if asname else "")
                if cond:
                    cond_lines[cond].append(f"from {mod} import {piece}")
                else:
                    out_from.setdefault(mod, []).append(piece)
        elif name in helper_of:
            h = helper_of[name]
            if h != this_mod:
                out_from.setdefault(cfg.IMPORT_PREFIX + h, []).append(name)
    for m in sorted(set(extra_mixins)):
        if m != this_mod:
            out_from.setdefault(cfg.IMPORT_PREFIX + m, []).append(cfg.MIXIN_NAMES[m])
    res = []
    for l in sorted(set(out_plain), key=lambda x: out_plain.index(x)):
        res.append(l)
    for mod, pieces in out_from.items():
        pieces = sorted(set(pieces), key=pieces.index)
        if len(pieces) == 1:
            res.append(f"from {mod} import {pieces[0]}")
        else:
            res.append(f"from {mod} import (\n" + "".join(f"    {p},\n" for p in pieces) + ")")
    for cond, ls in cond_lines.items():
        res.append(f"if {cond}:\n" + "".join(f"    {l}\n" for l in ls).rstrip("\n"))
    for block in sorted(set(raw_blocks), key=raw_blocks.index):
        res.append(block)
    return "\n".join(res)


unresolved_report = {}


def unresolved(used, this_mod, locals_defined):
    """Top-level names of the god file that stay there but the new module uses."""
    bad = set()
    for name in used:
        if name in toplevel_defs and name not in helper_of and name not in import_bind:
            bad.add(name)
    return bad


pkg_dir = os.path.join(ROOT, cfg.PKG_DIR)
os.makedirs(pkg_dir, exist_ok=True)
written = []

# helper modules
for h, ranges in helper_segments.items():
    merged = []
    for a, b in sorted(ranges):
        if merged and all(not lines[k - 1].strip() for k in range(merged[-1][1] + 1, a)):
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    code = "\n\n\n".join(seg_text(a, b).rstrip("\n") for a, b in merged) + "\n"
    used = names_used(code)
    own = {n for n, hh in helper_of.items() if hh == h}
    bad = unresolved(used - own, h, own)
    if bad:
        unresolved_report[h] = bad
    imports = render_imports(used - own, h, code=code)
    doc = cfg.HELPER_DOCS[h]
    text = f'"""{doc}"""\n\n{imports}\n\n\n{code}'
    post = getattr(cfg, "POST", {}).get(h)
    if post:
        text = post(text)
    path = os.path.join(pkg_dir, h + ".py")
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    written.append(path)

# mixin modules
for mod, ranges in mod_segments.items():
    if mod == "KEEP":
        continue
    code = "".join(seg_text(a, b) for a, b in sorted(ranges))
    code, needed = class_prefix_fix(code, mod)
    for old, new in getattr(cfg, "FILE_FIX", {}).get(mod, []):
        assert old in code, (mod, old)
        code = code.replace(old, new)
    used = names_used(code)
    bad = unresolved(used, mod, set())
    if bad:
        unresolved_report[mod] = bad
    imports = render_imports(used, mod, needed, code=code)
    doc = textwrap.indent(textwrap.fill(cfg.MIXIN_DOCS[mod], 75), "    ").strip()
    head = f'"""{cfg.MIXIN_FILE_DOCS[mod]}"""\n\n' if hasattr(cfg, "MIXIN_FILE_DOCS") else ""
    text = (head + imports + "\n\n\n"
            + f"class {cfg.MIXIN_NAMES[mod]}:\n    \"\"\"{doc}\n    \"\"\"\n"
            + code.rstrip("\n") + "\n")
    post = getattr(cfg, "POST", {}).get(mod)
    if post:
        text = post(text)
    path = os.path.join(pkg_dir, mod + ".py")
    open(path, "w", encoding="utf-8", newline="\n").write(text)
    written.append(path)

# ── Rewrite the god file ────────────────────────────────────────────────────
removed = set()
for mod, ranges in mod_segments.items():
    if mod != "KEEP":
        for a, b in ranges:
            removed.update(range(a, b + 1))
for a, b in moved_top_ranges:
    removed.update(range(a, b + 1))

out = []
cls_line = class_node.lineno
first_import_after = max(n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom)) and n.end_lineno < cls_line)
for i, l in enumerate(lines, start=1):
    if i in removed:
        continue
    if i == cls_line:
        order = [m for m in cfg.MIXIN_ORDER]
        assert set(order) == set(mod_segments) - {"KEEP"}, (set(order) ^ (set(mod_segments) - {"KEEP"}))
        bases = ",\n".join(f"    {cfg.MIXIN_NAMES[m]}" for m in order)
        m = re.match(rf"class {cfg.CLASS}\((.*)\):", l.strip())
        out.append(f"class {cfg.CLASS}(\n{bases},\n    {m.group(1)},\n):\n")
        continue
    out.append(l)
    if i == first_import_after:
        # re-export helper names (tests and a few lazy imports reach them
        # through the god module) and import the mixins
        by_h = defaultdict(list)
        for n, h in helper_of.items():
            by_h[h].append(n)
        block = ["", cfg.REEXPORT_COMMENT]
        for h in sorted(by_h):
            block.append(f"from {cfg.IMPORT_PREFIX}{h} import (  # noqa: F401\n" + "".join(f"    {n},\n" for n in by_h[h]) + ")")
        for m in cfg.MIXIN_ORDER:
            block.append(f"from {cfg.IMPORT_PREFIX}{m} import {cfg.MIXIN_NAMES[m]}")
        out.append("\n".join(block) + "\n")

new_src = "".join(out)
# collapse 3+ blank lines runs left by removals
new_src = re.sub(r"\n{4,}", "\n\n\n", new_src)
open(src_path, "w", encoding="utf-8", newline="\n").write(new_src)

print("written:", len(written))
for p in written:
    print(" ", os.path.relpath(p, ROOT), sum(1 for _ in open(p, encoding="utf-8")))
print("god file:", len(new_src.splitlines()))
if unresolved_report:
    print("UNRESOLVED (top-level names still in god file used by moved code):")
    for k, v in unresolved_report.items():
        print(" ", k, sorted(v))
