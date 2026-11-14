"""Prepare MO-only distribution resources."""

from __future__ import annotations

import json
from pathlib import Path

from .gettext_catalogs import check_freshness, compile_catalogs, updated_catalogs
from .translation_sources import active_entries, language_names


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def prepare_runtime(root: Path, destination: Path | None = None, *,
                    folder: Path | None = None) -> dict[Path, bytes]:
    """Validate all catalogs before writing any resource; build imports stay lazy."""
    folder = folder or root / "translations"
    catalogs = updated_catalogs(root, folder)
    check_freshness(folder, catalogs)
    payload = compile_catalogs(catalogs)
    source = active_entries(catalogs[Path("winzapp.pot")])
    payload[Path("winzapp.keys")] = json_bytes({key: e.msgid for key, e in source.items()})
    payload[Path("language_map.json")] = json_bytes(language_names(root))
    destination = destination or root / "client" / "languages"
    for relative, data in payload.items():
        path = destination / relative
        if not path.exists() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    return payload
