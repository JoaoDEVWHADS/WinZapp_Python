"""Every attribute reached through an alias of the split classes still resolves
the way it did on the base ref.

usage: python winzapp_tools/god_split/verify_instance_access.py <base-ref>

Other modules rarely say ``MainWindow.x``; they hold the instance under some
name — ``self.main_window``, ``self._mw``, ``mw``, ``main_window``,
``self._main_window``, ``panel``, ``self.conversations_panel`` — or reach it
by string through ``getattr(mw, "x", default)`` / ``hasattr(mw, "x")``. This
collects every such attribute name across client/ and tests/, and classifies
it on the base ref and now as:

  member    defined on the class (method, property, class attribute)
  instance  assigned as ``self.<name> = ...`` somewhere in the class's code
  unknown   neither (a stub-only name in tests, a getattr probe for an
            optional attribute, or a pre-existing typo)

A split must not move any name from ``member``/``instance`` to ``unknown``.
Names that were ``unknown`` before are reported separately — they are not the
split's doing, but they are worth a look.
"""
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = sys.argv[1] if len(sys.argv) > 1 else "main"

TARGETS = {
    "MainWindow": {
        "entry": "client/main.py",
        "package": "client/main_window",
        "aliases": r"(?:self\.)?_?(?:mw|main_window|mainwindow|main_win)",
    },
    "ConversationsPanel": {
        "entry": "client/ui/conversations.py",
        "package": "client/ui/conversation_panel",
        "aliases": r"(?:self\.)?_?(?:conversations_panel|conv_panel|conversation_panel|panel|cp)",
    },
    "StatusPanel": {
        "entry": "client/status_panel.py",
        "package": "client/status_tab",
        "aliases": r"(?:self\.)?_?(?:status_panel|status_tab|sp)",
    },
}


def git_show(path):
    r = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else ""


def git_ls(pkg):
    r = subprocess.run(["git", "ls-tree", "--name-only", f"{BASE}", pkg + "/"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    return [p for p in r.stdout.split() if p.endswith(".py")]


def class_names(sources, cls):
    """(members, instance attrs) of `cls` assembled from `sources`: members of
    the class itself and of every *Mixin class, plus self.X assignments."""
    members, instance = set(), set()
    for src in sources:
        if not src:
            continue
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (node.name == cls or node.name.endswith("Mixin")):
                for n in node.body:
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        members.add(n.name)
                    elif isinstance(n, ast.Assign):
                        for t in n.targets:
                            for x in ast.walk(t):
                                if isinstance(x, ast.Name):
                                    members.add(x.id)
                    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                        members.add(n.target.id)
                for x in ast.walk(node):
                    targets = []
                    if isinstance(x, ast.Assign):
                        targets = x.targets
                    elif isinstance(x, (ast.AugAssign, ast.AnnAssign)):
                        targets = [x.target]
                    for t in targets:
                        for y in ast.walk(t):
                            if (isinstance(y, ast.Attribute) and isinstance(y.value, ast.Name)
                                    and y.value.id == "self"):
                                instance.add(y.attr)
                    if (isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "setattr"
                            and len(x.args) >= 2 and isinstance(x.args[0], ast.Name) and x.args[0].id == "self"
                            and isinstance(x.args[1], ast.Constant) and isinstance(x.args[1].value, str)):
                        instance.add(x.args[1].value)
    return members, instance


def wx_base_names(cls):
    sys.path.insert(0, str(ROOT / "client"))
    import wx  # noqa
    base = wx.Frame if cls == "MainWindow" else wx.Panel
    return set(dir(base))


files = [p for p in (ROOT / "client").rglob("*.py")
         if not any(part in ("api", "node", "lib", "__pycache__")
                    for part in p.relative_to(ROOT / "client").parts)]
files += list((ROOT / "tests").glob("*.py"))
texts = {p: p.read_text(encoding="utf-8") for p in files}

exit_code = 0
for cls, t in TARGETS.items():
    alias = t["aliases"]
    attr_re = re.compile(rf"(?<![\w.]){alias}\.([A-Za-z_]\w*)")
    str_re = re.compile(rf"(?:getattr|hasattr)\(\s*{alias}\s*,\s*[\"']([A-Za-z_]\w*)[\"']")
    used = {}
    for p, s in texts.items():
        for rx in (attr_re, str_re):
            for m in rx.finditer(s):
                used.setdefault(m.group(1), set()).add(p.relative_to(ROOT).as_posix())

    base_sources = [git_show(t["entry"])] + [git_show(p) for p in git_ls(t["package"])]
    now_sources = [(ROOT / t["entry"]).read_text(encoding="utf-8")] + [
        p.read_text(encoding="utf-8") for p in sorted((ROOT / t["package"]).glob("*.py"))]
    b_mem, b_inst = class_names(base_sources, cls)
    n_mem, n_inst = class_names(now_sources, cls)
    wx_names = wx_base_names(cls)

    def status(name, mem, inst):
        if name in mem:
            return "member"
        if name in inst:
            return "instance"
        if name in wx_names:
            return "wx"
        return "unknown"

    regressed, was_unknown, counts = [], [], {}
    for name, where in sorted(used.items()):
        b, n = status(name, b_mem, b_inst), status(name, n_mem, n_inst)
        counts[n] = counts.get(n, 0) + 1
        if b != "unknown" and n == "unknown":
            regressed.append((name, b, sorted(where)))
        elif b != n:
            regressed.append((name, f"{b}->{n}", sorted(where)))
        elif n == "unknown":
            was_unknown.append((name, sorted(where)))

    print(f"== {cls}: {len(used)} distinct attribute names reached through instance aliases "
          f"/ getattr / hasattr  {counts}")
    print(f"   member-set base={len(b_mem)} now={len(n_mem)} identical={b_mem == n_mem}; "
          f"instance-attr set identical={b_inst == n_inst}")
    print(f"   CHANGED STATUS (split regressions): {len(regressed)}")
    for name, how, where in regressed:
        exit_code = 1
        print(f"     {name}: {how}  <- {where[:4]}")
    print(f"   unknown both before and after (not the split's doing): {len(was_unknown)}")
    for name, where in was_unknown:
        print(f"     {name}  <- {where[:3]}")
sys.exit(exit_code)
