"""Read authoritative PO sources and find gettext references without UI imports."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from string import Formatter

import polib


SOURCE_LOCALE = "en-US"
_SKIP_DIRS = {"api", "api2", "api_patches", "node", "venv", ".venv", "__pycache__"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_object(path: Path) -> dict[str, str]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{path}: expected a nonempty object")
    if any(not key.strip() or not isinstance(text, str) or not text.strip()
           for key, text in value.items()):
        raise ValueError(f"{path}: keys and values must be nonempty strings")
    return value


def format_fields(text: str) -> set[str]:
    """Include fields in nested format specs, while ignoring escaped braces."""
    fields = set()
    for _, field, spec, _ in Formatter().parse(text):
        if field is not None:
            fields.add(field)
            fields.update(format_fields(spec))
    return fields


def language_names(root: Path) -> dict[str, str]:
    names = _read_object(root / "client" / "languages" / "language_map.json")
    if SOURCE_LOCALE not in names:
        raise ValueError(f"Source locale {SOURCE_LOCALE} is not registered")
    if any(not re.fullmatch(r"[a-zA-Z]{2,3}(?:-[a-zA-Z0-9]+)*", code) for code in names):
        raise ValueError("Invalid locale code in language_map.json")
    return names


def po_path(folder: Path, locale: str) -> Path:
    return folder / locale / "LC_MESSAGES" / "winzapp.po"


def load_po(path: Path) -> polib.POFile:
    return polib.pofile(str(path), encoding="utf-8", check_for_duplicates=True)


def active_entries(catalog: polib.POFile) -> dict[str, polib.POEntry]:
    """Contexts, not English text, uniquely identify WinZapp messages."""
    entries = {}
    for entry in catalog:
        if entry.obsolete:
            continue
        if not entry.msgctxt or not re.fullmatch(r"[a-zA-Z0-9_]+", entry.msgctxt):
            raise ValueError(f"Missing/invalid stable key (msgctxt): {entry.msgid!r}")
        if entry.msgctxt in entries:
            raise ValueError(f"Duplicate stable key: {entry.msgctxt}")
        if not entry.msgid.strip():
            raise ValueError(f"{entry.msgctxt}: empty source text")
        if entry.msgid_plural or entry.msgstr_plural:
            raise ValueError(f"{entry.msgctxt}: plural entries require a future plural API")
        if any(char in text for text in (entry.msgid, entry.msgstr) for char in ("\0", "\x04")):
            raise ValueError(f"{entry.msgctxt}: reserved gettext separator in text")
        format_fields(entry.msgid)
        entries[entry.msgctxt] = entry
    return entries


def source_references(root: Path) -> dict[str, list[tuple[str, str]]]:
    """AST scan handles single quotes and multiline calls without importing UI.

    References name the file only, never the line: a line number moves whenever
    anything above the call changes, which would mark every catalog stale (and
    fail every build) for an edit unrelated to translations."""
    refs: dict[str, set[tuple[str, str]]] = {}
    client = root / "client"
    for path in sorted(client.rglob("*.py")):
        if _SKIP_DIRS.intersection(path.relative_to(client).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "t" and node.args):
                continue
            receiver = node.func.value
            is_i18n = ((isinstance(receiver, ast.Name) and receiver.id == "i18n")
                       or (isinstance(receiver, ast.Attribute) and receiver.attr == "i18n"))
            key = node.args[0]
            if is_i18n and isinstance(key, ast.Constant) and isinstance(key.value, str):
                refs.setdefault(key.value, set()).add((path.relative_to(root).as_posix(), ""))
    return {key: sorted(places) for key, places in refs.items()}
