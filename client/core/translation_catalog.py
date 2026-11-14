"""Shared settings-independent gettext loader for startup and the main UI.

Development reads editable PO and compiles in memory. Frozen distributions
read only built MO and the stable key map, using the standard library.
"""

from __future__ import annotations

import gettext
import io
import json
import logging
from pathlib import Path

from app_paths import _is_frozen, resource_path


class _Missing(gettext.NullTranslations):
    def pgettext(self, context, message):
        raise KeyError(context)


def _lookup(binary: bytes, sources: dict[str, str]) -> dict[str, str]:
    translator = gettext.GNUTranslations(io.BytesIO(binary))
    translator.add_fallback(_Missing())
    result = {}
    for key, message in sources.items():
        try:
            result[key] = translator.pgettext(key, message)
        except KeyError:
            pass
    return result


def load_catalog(locale: str) -> dict[str, str]:
    """No locale fallback here; only the first-launch dialog requests one."""
    try:
        if not isinstance(locale, str) or not locale or any(c in locale for c in "/\\."):
            return {}
        if not _is_frozen():
            path = Path(resource_path("..", "translations", locale, "LC_MESSAGES", "winzapp.po"))
            if path.is_file():
                import polib  # development only; frozen loading never needs it

                catalog = polib.pofile(str(path), encoding="utf-8", check_for_duplicates=True)
                sources = {e.msgctxt: e.msgid for e in catalog if e.msgctxt and not e.obsolete}
                return _lookup(catalog.to_binary(), sources)
        with open(resource_path("languages", "winzapp.keys"), encoding="utf-8") as stream:
            sources = json.load(stream)
        with open(resource_path("languages", locale, "LC_MESSAGES", "winzapp.mo"), "rb") as stream:
            return _lookup(stream.read(), sources)
    except Exception:
        logging.warning("Unable to load gettext translation catalog", exc_info=True)
        return {}
