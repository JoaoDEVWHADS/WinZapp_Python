"""Tests for MainWindow.self_reference_label() — the "Como se referir a
mim?" ("How should I be referred to?") setting's runtime word, and the two
i18n keys backing its "eu" (first-person) vs "voce" (second-person) modes.

Reported live (en-US only): the settings dialog's radio group showed two
identical "You"/"You" options instead of a real first-/second-person
choice. Root cause: the "eu" mode's word — both in the settings dialog's
own radio label and in self_reference_label()'s actual runtime return value
— was self.i18n.t("sender_you"), a key meant for "You: ..." message-sender
labels elsewhere in the app. Its natural translation is second-person in
every language; pt-BR/pt-PT ("Eu") and es-ES ("Yo") only ever happened to
already read first-person by coincidence, while en-US's is genuinely
"You" — making "eu" and "voce" mode produce the exact same word and the
setting have literally no effect for English users. Fixed with a dedicated
ui_self_reference_eu key, translated as an actual first-person word in
every language.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so the method is exercised as a plain function against a small
stub — same approach as tests/test_serialize_msg_id.py.
"""

import json
import os

import pytest

from main import MainWindow


class _FakeI18n:
    _STRINGS = {
        "ui_self_reference_eu": "Me",
        "ui_self_reference_voce": "You",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


class _Stub:
    self_reference_label = MainWindow.self_reference_label

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.i18n = _FakeI18n()


class TestSelfReferenceLabelModes:
    def test_default_mode_is_eu_and_uses_the_dedicated_key(self):
        stub = _Stub()
        assert stub.self_reference_label() == "Me"

    def test_explicit_eu_mode(self):
        stub = _Stub({"user_interface": {"self_reference_mode": "eu"}})
        assert stub.self_reference_label() == "Me"

    def test_voce_mode(self):
        stub = _Stub({"user_interface": {"self_reference_mode": "voce"}})
        assert stub.self_reference_label() == "You"

    def test_eu_and_voce_are_never_the_same_word(self):
        stub = _Stub()
        eu = stub.self_reference_label()
        voce = _Stub({"user_interface": {"self_reference_mode": "voce"}}).self_reference_label()
        assert eu != voce

    def test_custom_mode_with_a_word_set(self):
        stub = _Stub({"user_interface": {
            "self_reference_mode": "custom",
            "self_reference_custom_word": "Boss",
        }})
        assert stub.self_reference_label() == "Boss"

    def test_custom_mode_with_no_word_falls_back_to_eu(self):
        stub = _Stub({"user_interface": {
            "self_reference_mode": "custom",
            "self_reference_custom_word": "   ",
        }})
        assert stub.self_reference_label() == "Me"


LANG_DIR = os.path.join(os.path.dirname(__file__), "..", "client", "languages")


#: Every registered locale, from language_map.json — pl used to be left out
#: of this list, and this is the only check that the two keys are *distinct*
#: (the union check in test_language_files_in_sync.py catches a missing or
#: blank value, never two identical ones).
_LANG_FILES = [
    f"{code}.json"
    for code in sorted(
        json.load(open(os.path.join(LANG_DIR, "language_map.json"), encoding="utf-8"))
    )
]


@pytest.mark.parametrize("lang_file", _LANG_FILES)
class TestSelfReferenceKeysDifferAcrossEveryLanguage:
    def test_eu_and_voce_keys_are_both_present_and_distinct(self, lang_file):
        with open(os.path.join(LANG_DIR, lang_file), encoding="utf-8") as f:
            strings = json.load(f)

        eu = strings.get("ui_self_reference_eu")
        voce = strings.get("ui_self_reference_voce")

        assert eu, f"{lang_file} is missing ui_self_reference_eu"
        assert voce, f"{lang_file} is missing ui_self_reference_voce"
        assert eu != voce, f"{lang_file}: ui_self_reference_eu and ui_self_reference_voce are identical ({eu!r})"
