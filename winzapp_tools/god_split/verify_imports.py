"""Every name anyone imports from (or reads off) the split modules resolves.

Walks every .py under client/ (minus vendored trees) and tests/, including
imports inside function bodies, and checks:
  1. `from <mod> import name` for mod in main, ui.conversations, main_window.*,
     ui.conversation_panel.* -> the attribute exists;
  2. `<alias>.name` where alias is bound (anywhere in the file) by
     `import main [as alias]`, `import ui.conversations as alias`,
     `from ui import conversations` -> the attribute exists;
  3. MainWindow / ConversationsPanel member names used as `MainWindow.x` /
     `ConversationsPanel.x` anywhere -> exist on the class.
"""
import ast
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client"))
sys.path.insert(0, str(ROOT))

WATCHED = ("main", "ui.conversations", "status_panel")
WATCHED_PREFIX = ("main_window", "ui.conversation_panel", "status_tab")


def watched(mod):
    return mod in WATCHED or mod.startswith(tuple(p + "." for p in WATCHED_PREFIX)) or mod in WATCHED_PREFIX


files = [p for p in (ROOT / "client").rglob("*.py")
         if not any(part in ("api", "node", "lib", "__pycache__") for part in p.relative_to(ROOT / "client").parts)]
files += list((ROOT / "tests").glob("*.py"))

problems = []
checked = 0
import main  # noqa: E402  (loads everything)
from ui.conversations import ConversationsPanel  # noqa: E402
from status_panel import StatusPanel  # noqa: E402
classes = {"MainWindow": main.MainWindow, "ConversationsPanel": ConversationsPanel,
           "StatusPanel": StatusPanel}

for f in files:
    tree = ast.parse(f.read_text(encoding="utf-8"))
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and watched(node.module):
            mod = importlib.import_module(node.module)
            for a in node.names:
                checked += 1
                if a.name != "*" and not hasattr(mod, a.name):
                    try:
                        importlib.import_module(f"{node.module}.{a.name}")
                    except ImportError:
                        problems.append(f"{f.relative_to(ROOT)}:{node.lineno} from {node.module} import {a.name}")
        elif isinstance(node, ast.ImportFrom) and node.module == "ui":
            for a in node.names:
                if a.name == "conversations":
                    aliases[a.asname or a.name] = "ui.conversations"
        elif isinstance(node, ast.Import):
            for a in node.names:
                if watched(a.name):
                    if a.asname:
                        aliases[a.asname] = a.name
                    elif a.name == "main":
                        aliases["main"] = "main"
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            base = node.value.id
            if base in aliases:
                checked += 1
                mod = importlib.import_module(aliases[base])
                if not hasattr(mod, node.attr):
                    problems.append(f"{f.relative_to(ROOT)}:{node.lineno} {base}.{node.attr}")
            elif base in classes:
                checked += 1
                if not hasattr(classes[base], node.attr) and not isinstance(node.ctx, ast.Store):
                    problems.append(f"{f.relative_to(ROOT)}:{node.lineno} {base}.{node.attr}")

print(f"files: {len(files)}  references checked: {checked}  unresolved: {len(problems)}")
for p in problems:
    print("  ", p)
