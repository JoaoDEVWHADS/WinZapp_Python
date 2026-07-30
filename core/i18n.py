import json
import logging
from app_paths import resource_path

# Fallback used only if languages/language_map.json is missing or unreadable
# — should never happen in a normal install, but adding a language must not
# require a rebuild, so the real source of truth is that JSON file.
_FALLBACK_LANGUAGE_NAMES = {
    "pt-BR": "Português (Brasil)",
    "en-US": "English (United States)",
}


def _load_language_names() -> dict:
    """Load { lang_code: display_name } from languages/language_map.json.

    Dict order (== file order, preserved by json.load) determines the order
    shown in the Settings combobox. Adding a new locale only requires
    dropping languages/<code>.json + a new entry here — no rebuild.
    """
    try:
        with open(resource_path("languages", "language_map.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except Exception:
        logging.warning("Failed to load languages/language_map.json — using fallback list", exc_info=True)
    return dict(_FALLBACK_LANGUAGE_NAMES)


# Human-readable display names for each supported locale.
LANGUAGE_NAMES = _load_language_names()

# Module-level translation cache: { lang_code: { key: value } }
_TRANSLATIONS_CACHE: dict = {}


def _load_translations(lang_code: str) -> dict:
    """Load the JSON file for *lang_code* into the cache and return it."""
    try:
        with open(resource_path("languages", f"{lang_code}.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    _TRANSLATIONS_CACHE[lang_code] = data
    return data


class I18n:
    def __init__(self, main_window):
        self.main_window = main_window
        self.language = "pt-BR"  # default, overwritten by get_language()

    def get_language(self):
        """Read the current language from settings and cache it in self.language."""
        self.language = self.main_window.settings.get("general", {}).get("language", "pt-BR")
        return self.language

    def t(self, key: str) -> str:
        """Translate *key* using the language currently stored in self.language."""
        lang = self.language
        translations = _TRANSLATIONS_CACHE.get(lang)
        if translations is None:
            translations = _load_translations(lang)
        return translations.get(key, key)

    @staticmethod
    def invalidate_cache():
        """Clear the module-level translation cache (call after a language change)."""
        _TRANSLATIONS_CACHE.clear()
