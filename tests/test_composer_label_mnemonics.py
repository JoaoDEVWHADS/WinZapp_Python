from tests.locales import load_strings, registered_locale_codes

COMPOSER_LABELS = ("type_message", "type_message_group", "group_admins_only")

SIBLING_BUTTONS = (
    "add_attachment",
    "record_voice_message",
    "send_message",
    "emoji_button",
    "cancel_edit",
)


def _locales():
    for locale in registered_locale_codes():
        yield locale, load_strings(locale)


def _mnemonic(text):
    i = text.find("&")
    if i < 0 or i == len(text) - 1:
        return None
    return text[i + 1].upper()


class TestTheComposerKeyDoesNotMoveWithGroupState:
    def test_every_composer_label_offers_the_same_key(self):
        for name, translations in _locales():
            found = {k: _mnemonic(translations[k]) for k in COMPOSER_LABELS}
            assert len(set(found.values())) == 1, (name, found)

    def test_no_composer_label_drops_its_key(self):
        for name, translations in _locales():
            for key in COMPOSER_LABELS:
                assert _mnemonic(translations[key]) is not None, (name, key)


class TestNoCollisionWithTheComposerButtons:
    def test_the_restricted_label_key_is_not_claimed_by_a_button(self):
        for name, translations in _locales():
            field = _mnemonic(translations["group_admins_only"])
            for key in SIBLING_BUTTONS:
                assert _mnemonic(translations.get(key, "")) != field, (
                    name, key, field,
                )


class TestTheDisabledChannelLabelHasNoKey:
    def test_a_key_on_a_disabled_field_would_do_nothing(self):
        for name, translations in _locales():
            assert _mnemonic(translations["channel_read_only"]) is None, name


class TestTheAttachButtonHasNoAltKey:
    def test_alt_a_does_not_open_the_attach_menu(self):
        """Reported: Alt+A opened the attach menu, whose shortcut is
        Ctrl+Shift+A. "Adicionar &anexo" made Alt+A press the button; like
        its siblings (Enviar, Gravar, Emoji) it carries no mnemonic."""
        for name, translations in _locales():
            assert _mnemonic(translations["add_attachment"]) is None, name
