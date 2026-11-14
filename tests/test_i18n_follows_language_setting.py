"""I18n.t() answers in the user's language even before get_language() was
called (it used to start at pt-BR and stay there until someone did)."""

from core.i18n import I18n


class _MainWindow:
    def __init__(self, language):
        self.settings = {"general": {"language": language}}


def test_text_is_in_the_users_language_without_calling_get_language():
    i18n = I18n(_MainWindow("en-US"))
    assert i18n.t("no_pairing_code_received").startswith("Could not connect")


def test_text_follows_a_language_change():
    mw = _MainWindow("en-US")
    i18n = I18n(mw)
    english = i18n.t("no_pairing_code_received")
    mw.settings["general"]["language"] = "pt-BR"
    assert i18n.t("no_pairing_code_received") != english


def test_a_main_window_without_settings_keeps_the_default():
    class Bare:
        pass
    i18n = I18n(Bare())
    assert i18n.t("no_pairing_code_received")  # pt-BR default, no crash
