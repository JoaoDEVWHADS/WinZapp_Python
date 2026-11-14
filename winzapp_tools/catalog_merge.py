"""Merge a generated POT by stable key, preserving translator work and history."""

from __future__ import annotations

from copy import deepcopy

import polib

from .translation_sources import SOURCE_LOCALE, active_entries, format_fields


HEADER = (
    "WinZapp translations. Edit the PO files; winzapp.pot is generated.\n"
    "msgctxt is the stable i18n.t() key. Preserve Python {placeholders}.\n"
    "In wx labels, & marks a mnemonic and && means a literal ampersand."
)
METADATA = {
    "Project-Id-Version": "WinZapp",
    "Report-Msgid-Bugs-To": "https://github.com/gabrielhhaber/WinZapp_Python/issues",
    "MIME-Version": "1.0",
    "Content-Type": "text/plain; charset=UTF-8",
    "Content-Transfer-Encoding": "8bit",
}


def make_template(source: polib.POFile, refs: dict) -> polib.POFile:
    template = polib.POFile(encoding="utf-8", wrapwidth=78)
    template.header = HEADER
    template.metadata = dict(METADATA)
    entries = active_entries(source)
    if not entries:
        raise ValueError("The English source catalog must not be empty")
    unknown = refs.keys() - entries.keys()
    if unknown:
        raise ValueError(f"Code uses missing translation keys: {sorted(unknown)}")
    for key, entry in sorted(entries.items()):
        template.append(polib.POEntry(
            msgctxt=key, msgid=entry.msgid, comment=entry.comment,
            occurrences=[("translations/en-US/LC_MESSAGES/winzapp.po", ""), *refs.get(key, [])],
            flags=["python-brace-format"] if format_fields(entry.msgid) else [],
        ))
    return template


def merge_catalog(template: polib.POFile, catalog: polib.POFile, locale: str) -> polib.POFile:
    """New -> blank; changed source -> fuzzy; removed -> obsolete; no lost comments."""
    current = active_entries(catalog)
    previous = {e.msgctxt: e for e in catalog if e.obsolete}
    merged = polib.POFile(encoding="utf-8", wrapwidth=78)
    merged.metadata = dict(catalog.metadata)
    merged.metadata.update(METADATA)
    merged.metadata["Language"] = locale
    merged.header = (HEADER if not catalog.header or "Generated snapshot SHA256:" in catalog.header
                     or "Generated JSON migration snapshot" in catalog.header else catalog.header)
    keys = {e.msgctxt for e in template}
    for reference in template:
        old = current.get(reference.msgctxt) or previous.get(reference.msgctxt)
        entry = deepcopy(old) if old is not None else deepcopy(reference)
        entry.obsolete = False
        if old is not None and old.msgid != reference.msgid:
            entry.previous_msgid = old.msgid
            entry.fuzzy = True
        entry.msgid = reference.msgid
        entry.occurrences = list(reference.occurrences)
        entry.comment = reference.comment
        entry.flags = sorted(set(reference.flags) | (set(entry.flags) - {"python-brace-format"}))
        if locale == SOURCE_LOCALE:
            entry.msgstr = entry.msgid
            entry.fuzzy = False
        merged.append(entry)
    for old in catalog:
        if old.msgctxt not in keys:
            entry = deepcopy(old)
            entry.obsolete = True
            merged.append(entry)
    return merged


def catalog_signature(catalog: polib.POFile) -> list[tuple]:
    """Ignore wrapping, entry order and translator metadata; check template state."""
    return sorted((e.msgctxt or "", e.msgid, e.msgstr, bool(e.obsolete),
                   tuple(sorted(e.flags)), tuple(sorted(e.occurrences)), e.comment,
                   e.previous_msgid or "", e.tcomment) for e in catalog)
