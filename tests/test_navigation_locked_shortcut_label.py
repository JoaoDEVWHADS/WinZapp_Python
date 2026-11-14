"""The Locked chats navigation item names its Alt+7 shortcut, like Alt+4/5/6."""
from tests.locales import load_strings, registered_locale_codes


def test_every_locale_shows_alt7_on_the_locked_chats_nav_item():
    for locale in registered_locale_codes():
        assert load_strings(locale)["locked_chats_nav"].endswith(" alt+7"), locale
