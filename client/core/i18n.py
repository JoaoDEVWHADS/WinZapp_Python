import json
import logging
from app_paths import resource_path
from core.translation_catalog import load_catalog

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
    installing languages/<code>/LC_MESSAGES/winzapp.mo plus an entry here.
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
    """Load gettext into the shared dict cache (also patched by the Mac layer)."""
    data = load_catalog(lang_code)
    _TRANSLATIONS_CACHE[lang_code] = data
    return data


class I18n:
    def __init__(self, main_window):
        self.main_window = main_window
        self.language = "pt-BR"  # default, overwritten by get_language()
        # Whether get_language() has read the settings yet; see t().
        self._language_read = False

    def get_language(self):
        """Set self.language to the language this window shows, and return it.

        The window's own instance (`main_window.i18n`) reads it from settings:
        it is asked only where a language is being applied -- startup, the
        Settings dialog's OK, a settings import -- each followed by
        apply_language_changes(). Every other instance (the tray, the
        notification manager, the WebSocket client, a few dialogs) follows
        that instance instead of the settings.

        They used to read the settings too, and the language setting is
        install-wide: when another account changes it, this window's copy is
        updated on its next save, and the window applies it as a whole only
        once it is not the active one
        (MainWindow._apply_pending_language_switch()). The helpers switched on
        their own before that -- toasts and tray menus in the new language
        over a window still in the old one, or the window's own strings
        switching one at a time. Before the window's instance exists (early
        startup), there is
        nothing to follow and the settings are read.
        """
        window_i18n = getattr(self.main_window, "i18n", None)
        if isinstance(window_i18n, I18n) and window_i18n is not self:
            self.language = window_i18n.language
            return self.language
        self.language = self.main_window.settings.get("general", {}).get("language", "pt-BR")
        self._language_read = True
        return self.language

    def t(self, key: str) -> str:
        """Translate *key* into the user's current language.

        The language is refreshed on every lookup: an I18n starts at "pt-BR"
        and used to follow the user's choice only after someone called
        get_language(), so text produced before that came out in Portuguese
        on, say, an English install (seen with the pairing error
        "no_pairing_code_received"). The read is a dict lookup.

        Except on the window's own instance once it has a language: that one
        changes only when asked (see get_language()). Refreshing it here read
        the settings another account's change had just reached, so each
        string drawn after that came out in the new language over a window
        still in the old one, and _apply_pending_language_switch() then found
        the language "already applied" and never repainted the rest.
        """
        if not (self._language_read and getattr(self.main_window, "i18n", None) is self):
            try:
                self.get_language()
            except Exception:
                pass  # no settings yet: keep the last known language
        lang = self.language
        translations = _TRANSLATIONS_CACHE.get(lang)
        if translations is None:
            translations = _load_translations(lang)
        return translations.get(key, key)

    @staticmethod
    def invalidate_cache():
        """Clear the module-level translation cache (call after a language change)."""
        _TRANSLATIONS_CACHE.clear()
