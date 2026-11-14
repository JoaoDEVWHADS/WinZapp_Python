"""Integration checks for the configurable spelling-error sound event."""

import json
from pathlib import Path
from tests.locales import load_strings, registered_locale_codes

from core.sound_system import SOUND_EVENTS


ROOT = Path(__file__).resolve().parents[1]


def test_spelling_error_event_has_a_bundled_default_sound():
    assert ("spelling_error", "textError.ogg") in SOUND_EVENTS

    manifest_path = ROOT / "client" / "sounds" / "default" / "default.pack.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_sound = manifest["events"]["spelling_error"]

    assert relative_sound == "textError.ogg"
    assert (manifest_path.parent / relative_sound).is_file()


def test_every_supported_language_names_the_spelling_error_event():
    for locale in registered_locale_codes():
        assert load_strings(locale).get("sound_event_spelling_error"), locale
