"""Validate editable gettext catalogs, with an all-or-nothing compile gate."""

from __future__ import annotations

import gettext
import io
import re
from pathlib import Path

import polib

from .catalog_merge import METADATA, catalog_signature, make_template, merge_catalog
from .translation_sources import (
    SOURCE_LOCALE, active_entries, format_fields, language_names, load_po, po_path, source_references,
)


class _MissingTranslation(gettext.NullTranslations):
    def pgettext(self, context, message):
        raise ValueError(f"MO is missing context {context}")


def updated_catalogs(root: Path, folder: Path | None = None) -> dict[Path, polib.POFile]:
    folder = folder or root / "translations"
    names = language_names(root)
    paths = {po_path(folder, locale) for locale in names}
    extra = set(folder.rglob("*.po")) - paths
    if extra:
        raise ValueError(f"Unregistered PO catalogs: {sorted(str(p) for p in extra)}")
    source = load_po(po_path(folder, SOURCE_LOCALE))
    template = make_template(source, source_references(root))
    result = {Path("winzapp.pot"): template}
    for locale in sorted(names):
        path = po_path(folder, locale)
        catalog = load_po(path) if path.exists() else polib.POFile(encoding="utf-8")
        result[path.relative_to(folder)] = merge_catalog(template, catalog, locale)
    return result


def save_catalogs(folder: Path, catalogs: dict[Path, polib.POFile]) -> None:
    """Read/merge everything before writing; do not overwrite unchanged files."""
    for relative, catalog in catalogs.items():
        path = folder / relative
        text = str(catalog)
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")


def check_freshness(folder: Path, catalogs: dict[Path, polib.POFile]) -> None:
    stale = []
    for relative, expected in catalogs.items():
        path = folder / relative
        if not path.exists():
            stale.append(relative)
        elif relative.suffix == ".pot":
            if path.read_text(encoding="utf-8") != str(expected):
                stale.append(relative)
        else:
            current = load_po(path)
            essential_metadata = {*METADATA, "Language"}
            if (catalog_signature(current) != catalog_signature(expected)
                    or any(current.metadata.get(key) != expected.metadata.get(key)
                           for key in essential_metadata)):
                stale.append(relative)
    if stale:
        raise ValueError("Stale catalogs: " + ", ".join(p.as_posix() for p in stale)
                         + "; run python -m winzapp_tools.translations update")


def validate_catalogs(catalogs: dict[Path, polib.POFile], *, complete: bool = True) -> None:
    source = active_entries(catalogs[Path("winzapp.pot")])
    errors = []
    for relative, catalog in catalogs.items():
        if relative.suffix != ".po":
            continue
        entries = active_entries(catalog)
        for key, reference in source.items():
            entry = entries.get(key)
            if entry is None or entry.fuzzy or not entry.msgstr.strip():
                if complete:
                    errors.append(f"{relative}/{key}: missing, untranslated or fuzzy")
                continue
            try:
                if format_fields(entry.msgstr) != format_fields(reference.msgid):
                    raise ValueError("placeholders differ from source")
                if any(not match.group(1).isalnum() for match in
                       re.finditer(r"&(.?)", entry.msgstr.replace("&&", ""))):
                    raise ValueError("malformed wx mnemonic (literal & must be &&)")
            except ValueError as exc:
                errors.append(f"{relative}/{key}: {exc}")
    if errors:
        raise ValueError("Catalog validation failed:\n" + "\n".join(errors[:20])
                         + (f"\n... {len(errors)} errors total" if len(errors) > 20 else ""))


def compile_catalogs(catalogs: dict[Path, polib.POFile]) -> dict[Path, bytes]:
    """Refuse incomplete/fuzzy catalogs, then prove every MO lookup is present."""
    validate_catalogs(catalogs)
    binaries = {}
    for relative, catalog in catalogs.items():
        if relative.suffix != ".po":
            continue
        binary = catalog.to_binary()
        translator = gettext.GNUTranslations(io.BytesIO(binary))
        translator.add_fallback(_MissingTranslation())
        for entry in active_entries(catalog).values():
            if translator.pgettext(entry.msgctxt, entry.msgid) != entry.msgstr:
                raise ValueError(f"{relative}/{entry.msgctxt}: MO round trip changed translation")
        binaries[relative.with_suffix(".mo")] = binary
    return binaries
