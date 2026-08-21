"""Top-level menu bar labels (Arquivo/Sincronização/Ajuda, ...) must not
share an Alt+<letter> mnemonic within the same locale.

Reported live: pt-BR and es-ES both had "Arquivo"/"Ayuda" ("&Arquivo" /
"&Ayuda") mnemonic-ed on the same letter as the File menu (both starting
with A) — Alt+A opened whichever menu wx.MenuBar happened to resolve the
collision to, and the other one had no working Alt shortcut at all.

wx uses the same "&<letter>" convention MainWindow._build_menubar() already
relies on elsewhere (see its own nav_letter-extraction comment in
create_accelerator_table) — a leading "&" before a letter marks that letter
as the mnemonic; "&&" is a literal ampersand and carries no mnemonic.
"""

import json
import re

from app_paths import resource_path

LOCALES = ["pt-BR", "pt-PT", "en-US", "es-ES", "pl"]

# Every label MainWindow._build_menubar() adds directly to the wx.MenuBar,
# in i18n key form. acc_menu_title (Accounts) is intentionally excluded: it
# is only appended under the multi-account system and today carries no "&"
# mnemonic in any locale at all.
TOP_LEVEL_MENU_KEYS = ["menu_file", "menu_sync", "menu_help"]


def _load(name):
    with open(resource_path("languages", f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _mnemonic(label: str) -> "str | None":
    """The letter after a single '&' (not '&&', a literal ampersand),
    lowercased — or None if the label has no mnemonic at all."""
    # Strip literal "&&" first so it can't be mistaken for a marker, then
    # look for a real "&<letter>".
    stripped = label.replace("&&", "")
    m = re.search(r"&(\w)", stripped)
    return m.group(1).lower() if m else None


class TestTopLevelMenuMnemonicsAreUnique:
    def test_no_two_top_level_menus_share_a_mnemonic(self):
        for locale in LOCALES:
            translations = _load(locale)
            seen = {}
            for key in TOP_LEVEL_MENU_KEYS:
                label = translations.get(key, "")
                letter = _mnemonic(label)
                if letter is None:
                    continue
                assert letter not in seen, (
                    f"{locale}: {key!r} ({label!r}) and {seen.get(letter)!r} "
                    f"both mnemonic on Alt+{letter.upper()}"
                )
                seen[letter] = key

    def test_every_top_level_menu_actually_has_a_mnemonic(self):
        """Not strictly required by wx, but losing the "&" entirely (instead
        of just colliding) is the same bug wearing a different hat — no
        Alt-key shortcut opens that menu at all."""
        for locale in LOCALES:
            translations = _load(locale)
            for key in TOP_LEVEL_MENU_KEYS:
                label = translations.get(key, "")
                assert _mnemonic(label) is not None, f"{locale}: {key!r} ({label!r}) has no '&' mnemonic"
