"""Prove a god-file split is pure movement.

usage: python winzapp_tools/god_split/verify_split.py <base-ref> <god file> <class> <package dir>
  e.g. verify_split.py main client/main.py MainWindow client/main_window

Compares the AST of every class member and every top-level def/assign of
<god file> at <base-ref> with the same-named node in the working tree
(god file + every module in <package dir>). Prints each node whose AST
differs, with a unified diff of its source, and a summary.
"""
import ast
import difflib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
base, god, cls_name, pkg = sys.argv[1:5]

old_src = subprocess.run(["git", "show", f"{base}:{god}"], cwd=ROOT, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout


def members(src, only_class=None):
    tree = ast.parse(src)
    out = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and (node.name == only_class or node.name.endswith("Mixin")):
            for n in node.body:
                key = None
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    key = ("method", n.name)
                    if key in out:  # property getter/setter pairs
                        key = ("method", n.name + "#2")
                elif isinstance(n, (ast.Assign, ast.AnnAssign)):
                    t = n.targets[0] if isinstance(n, ast.Assign) else n.target
                    key = ("attr", ast.unparse(t))
                if key:
                    out[key] = n
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[("func", node.name)] = node
        elif isinstance(node, ast.ClassDef):
            out[("class", node.name)] = node
        elif isinstance(node, ast.Assign):
            out[("global", ast.unparse(node.targets[0]))] = node
    return out


old = members(old_src, cls_name)
new = {}
files = [ROOT / god] + sorted((ROOT / pkg).glob("*.py"))
for f in files:
    for k, v in members(f.read_text(encoding="utf-8"), cls_name).items():
        if k in new and k[0] != "class":
            k = (k[0], k[1] + f"@{f.name}")
        new[k] = v

same = changed = missing = 0
for key, node in old.items():
    if key not in new:
        missing += 1
        print("MISSING", key)
        continue
    a, b = ast.dump(node), ast.dump(new[key])
    if a == b:
        same += 1
        continue
    changed += 1
    print(f"\n=== CHANGED {key[0]} {key[1]}")
    for line in difflib.unified_diff(ast.unparse(node).splitlines(), ast.unparse(new[key]).splitlines(), lineterm="", n=1):
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            print("   ", line)
print(f"\nidentical: {same}  changed: {changed}  missing: {missing}  (of {len(old)} nodes in {god}@{base})")
