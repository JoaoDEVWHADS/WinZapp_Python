"""Mac wording (strings_mac). The variants themselves live in
client/languages and are checked on every platform by
tests/test_language_files_in_sync.py and tests/test_macos_layer_contract.py."""

import os
import sys

import pytest

from tests.locales import registered_locale_codes

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

from winzapp_mac import strings_mac  # noqa: E402

LOCALES = registered_locale_codes()


def test_mac_variant_wins_and_other_windows_mentions_become_macos():
    data = {"autostart_ask_title": "Iniciar o WinZapp com o Windows",
            "autostart_ask_title_macos": "Iniciar o WinZapp ao iniciar sessão",
            "x": "padrão do Windows", "WindowsLike": "Windowsfoo"}
    out = strings_mac.mac_wording(data)
    assert out is data                     # in place: core.i18n caches this dict
    assert out["autostart_ask_title"] == "Iniciar o WinZapp ao iniciar sessão"
    assert out["x"] == "padrão do macOS"
    assert out["WindowsLike"] == "Windowsfoo"


@pytest.mark.parametrize("locale", LOCALES)
def test_no_locale_names_windows_on_the_mac(locale):
    from core import i18n
    data = strings_mac.mac_wording(i18n._load_translations(locale))
    left = [k for k, v in data.items() if isinstance(v, str) and "Windows" in v
            and not k.endswith(strings_mac.MAC_SUFFIX)]
    assert not left, f"{locale}: {left}"


def test_the_cached_translations_keep_the_mac_wording():
    from core import i18n
    strings_mac.install()
    i18n._TRANSLATIONS_CACHE.clear()

    class MW:
        settings = {"general": {"language": "en-US"}}

    tr = i18n.I18n(MW())
    first = tr.t("autostart_ask_title")
    assert first == tr.t("autostart_ask_title") == "Start WinZapp at login"
