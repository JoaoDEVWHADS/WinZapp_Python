"""Every UI language ships the same set of keys.

I18n.t() is `translations.get(key, key)` — there is no per-key fallback to
pt-BR. A key present in pt-BR but missing from another language file therefore
reaches the user as the raw key name ("about_license", "status_reply_send") in
the middle of the UI, which is exactly what happened to pl.json: it drifted 68
keys behind while features were added, and nothing failed until someone
actually switched the app to Polish.

pt-BR is the reference set (it is the locale the app defaults to and the one
new strings get written in first). These tests are what "add the key to all
five files" in CLAUDE.md is enforced by.
"""

import json
import re

import pytest

from app_paths import resource_path

REFERENCE = "pt-BR"


def _load(name):
    with open(resource_path("languages", f"{name}.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _language_map():
    return _load("language_map")


LOCALES = sorted(_language_map())


@pytest.fixture(scope="module")
def reference():
    return _load(REFERENCE)


def test_the_reference_locale_is_registered():
    assert REFERENCE in _language_map()


@pytest.mark.parametrize("locale", LOCALES)
def test_every_registered_locale_has_a_language_file(locale):
    assert _load(locale), f"{locale}.json is missing or empty"


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_has_no_missing_keys(locale, reference):
    missing = sorted(set(reference) - set(_load(locale)))
    assert missing == [], (
        f"{locale}.json is missing {len(missing)} key(s) that pt-BR defines — "
        f"they would render as the raw key name in the UI: {missing[:10]}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_has_no_unknown_keys(locale, reference):
    # A key only some locales know is either a typo or a string that was never
    # added to pt-BR — both mean somebody sees the raw key name.
    extra = sorted(set(_load(locale)) - set(reference))
    assert extra == [], f"{locale}.json defines keys pt-BR does not: {extra[:10]}"


@pytest.mark.parametrize("locale", LOCALES)
def test_locale_has_no_blank_translations(locale):
    blank = sorted(k for k, v in _load(locale).items() if not v.strip())
    assert blank == [], f"{locale}.json has empty translations: {blank[:10]}"


@pytest.mark.parametrize("locale", LOCALES)
def test_every_ampersand_is_a_well_formed_mnemonic(locale):
    # wx reads "&" in a label as "the next character is this control's Alt
    # shortcut", so a translator using it as the word "and" silently eats a
    # character and hands the shortcut to whatever followed. pt-PT shipped
    # "Fotos & vídeos" for exactly that reason; a literal ampersand has to be
    # written "&&". WHICH letter carries the mnemonic is a per-language
    # decision, so this checks only that every "&" is well formed — never that
    # locales agree on where mnemonics go.
    malformed = sorted(
        key for key, text in _load(locale).items()
        # "&&" is the escape for a literal "&" — drop those first, then no
        # surviving "&" may sit before anything but a letter or digit.
        if any(not m.group(1).isalnum()
               for m in re.finditer(r"&(.?)", text.replace("&&", "")))
    )
    assert malformed == [], (
        f"{locale}.json uses & as text rather than as a mnemonic marker "
        f"(write it as &&): {malformed}"
    )


@pytest.mark.parametrize("locale", LOCALES)
def test_placeholders_match_the_reference(locale, reference):
    # Every string is fed through str.format(): a translation that drops
    # {name} silently loses information, and one that invents a placeholder
    # pt-BR does not pass raises KeyError at the call site instead.
    translations = _load(locale)
    mismatched = {}
    for key, text in translations.items():
        if key not in reference:
            continue
        want = sorted(re.findall(r"\{(\w+)\}", reference[key]))
        got = sorted(re.findall(r"\{(\w+)\}", text))
        if want != got:
            mismatched[key] = (want, got)
    assert mismatched == {}, (
        f"{locale}.json placeholders diverge from pt-BR (key: expected, got): {mismatched}"
    )
