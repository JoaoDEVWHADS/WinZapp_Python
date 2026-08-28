import glob
import json
import os

LANG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "client",
    "languages",
)

COMPOSER_LABELS = ("type_message", "type_message_group", "group_admins_only")

SIBLING_BUTTONS = (
    "add_attachment",
    "record_voice_message",
    "send_message",
    "emoji_button",
    "cancel_edit",
)


def _locales():
    for path in sorted(glob.glob(os.path.join(LANG_DIR, "*.json"))):
        if os.path.basename(path) == "language_map.json":
            continue
        with open(path, encoding="utf-8") as fh:
            yield os.path.basename(path), json.load(fh)


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
