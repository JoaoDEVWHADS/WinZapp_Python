"""Every key the code asks for must exist in the language files.

tests/test_language_files_in_sync.py checks the other direction — that the
five locales carry the same set of keys as each other. That passes happily
when a key is missing from ALL of them, which is exactly what happened with
``voice_recording`` and ``recording_paused``: the Status recorder asked for
them, no locale had them, and since ``I18n.t()`` is ``translations.get(key,
key)`` the panel showed the literal strings "voice_recording" and
"recording_paused" — read out loud, as-is, by the screen reader.

Nothing failed, nothing logged, and the two files agreed with each other the
whole time. This test closes that gap from the code side.

Only literal calls are checked (``i18n.t("some_key")``). Keys built at runtime
(f-strings, variables, ``t(key)``) can't be resolved statically and are out of
scope — the same limit any static check of this shape has.
"""

import json
import pathlib
import re

import pytest

_CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
_LANGUAGES = _CLIENT / "languages"
_LOCALES = ("pt-BR", "pt-PT", "en-US", "es-ES", "pl")

#: `i18n.t("key")`, `self.i18n.t("key")`, `mw.i18n.t("key")` — the literal
#: forms. Deliberately anchored on `i18n.t(` so unrelated `.t(` calls and
#: dict lookups like `msg.get("caption")` are not mistaken for translations.
_CALL = re.compile(r'\bi18n\.t\(\s*"([a-zA-Z0-9_]+)"')

#: Directories that are not WinZapp's own UI code.
_SKIP_PARTS = {"api", "api2", "node", "venv", "__pycache__"}


def _iter_sources():
    for path in _CLIENT.rglob("*.py"):
        if _SKIP_PARTS & set(path.parts):
            continue
        yield path


def _used_keys() -> dict[str, set[str]]:
    """key -> set of files that ask for it."""
    used: dict[str, set[str]] = {}
    for path in _iter_sources():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for key in _CALL.findall(text):
            used.setdefault(key, set()).add(str(path.relative_to(_CLIENT)))
    return used


def _locale(code: str) -> dict:
    return json.loads((_LANGUAGES / f"{code}.json").read_text(encoding="utf-8"))


def test_the_scan_finds_a_reasonable_number_of_keys():
    """Guards the regex itself: if it silently stopped matching, every other
    test here would pass by finding nothing to check."""
    used = _used_keys()
    assert len(used) > 200, f"only {len(used)} keys found — the scan is probably broken"


@pytest.mark.parametrize("code", _LOCALES)
def test_every_key_the_code_uses_exists_in_the_locale(code):
    translations = _locale(code)
    missing = {
        key: sorted(files)
        for key, files in sorted(_used_keys().items())
        if key not in translations
    }
    assert not missing, (
        f"{code}.json is missing keys the code asks for — I18n.t() renders the "
        f"raw key name in the UI (and the screen reader reads it): "
        + "; ".join(f"{k} (used in {', '.join(f)})" for k, f in missing.items())
    )


def test_the_two_keys_that_motivated_this_check_are_present():
    """Regression pin for the Status recorder labels specifically."""
    for code in _LOCALES:
        translations = _locale(code)
        for key in ("voice_recording", "recording_paused"):
            assert key in translations, f"{key} missing from {code}.json"
            assert translations[key] != key, (
                f"{key} in {code}.json is just the key name again"
            )
