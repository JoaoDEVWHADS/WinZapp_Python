"""Call sites must format a translation the way the locale files actually wrote it.

tests/test_language_files_in_sync.py checks that the five language files agree
with *each other* — same keys, same placeholders. Nothing checked that the
Python calling them agrees with any of them, and that is the half where the
damage lands: I18n.t() returns a plain string, so `.format()` on it is only
validated at runtime, by the user, at the moment the dialog was supposed to
appear.

The bug this file pins: ``self.i18n.t("error").format(self.app_name)``. Every
locale writes that key with a NAMED placeholder ("{app_name} Error", "Erro do
{app_name}"), so a positional argument raises KeyError('app_name') — and it
raises while *building the arguments* to wx.MessageBox, so the exception
replaces the whole call and takes whatever followed it down too. On the
confirmed-logout path in main.py that meant `self._on_disconnect()` on the very
next line never ran, while `_logout_handled` had already latched True so no
later reading would retry: a genuinely unlinked device was left with no route
back to pairing at all, and the log claimed it had been wiped.

Two of ~197 call sites had it. It survived review twice — both times it read
like the ~45 correct ones sitting a few lines away — and it survived the unit
tests of the very function it broke, because those stub I18n.t as
``lambda key: key``, and a bare key name has no placeholders for a positional
argument to be wrong about. Hence a source-level check: this is a property of
the *code as written*, so it is cheaper and far more complete to read it off
the source than to reach every dialog from a test.

Generalised past the one key, since nothing about the mistake was specific to
it: any translation with named placeholders formatted positionally fails the
same way, and one whose placeholders are not all supplied fails identically.
"""

import ast
import json
import pathlib
import re

import pytest

CLIENT = pathlib.Path(__file__).resolve().parents[1] / "client"
LANGUAGES = CLIENT / "languages"

# Directories under client/ that are not WinZapp's own Python: the vendored
# WPPConnect Server clone and the portable Node runtime (both git-ignored, both
# absent on a bare checkout).
_NOT_OUR_SOURCE = {"api", "api_patches", "node"}


def _placeholders_by_key():
    """{translation key: {placeholder names}} across every locale.

    The union, for the same reason test_language_files_in_sync.py takes the
    union of the key sets: no single locale is guaranteed to be the complete
    one. That file separately asserts the locales agree on placeholders, so a
    disagreement is reported there rather than turning into a confusing
    failure here.
    """
    found: dict[str, set[str]] = {}
    for path in LANGUAGES.glob("*.json"):
        if path.stem == "language_map":  # {code: display name}, not translations
            continue
        for key, text in json.loads(path.read_text(encoding="utf-8")).items():
            if isinstance(text, str):
                found.setdefault(key, set()).update(re.findall(r"\{([^{}]*)\}", text))
    return found


def _format_call_sites():
    """Every ``<something>.t("literal-key").format(...)`` under client/.

    Yields (path, lineno, key, ast.Call for the .format()). Only a literal key
    can be resolved against the language files; a computed one (``t(name)``) is
    skipped rather than guessed at.
    """
    for path in sorted(CLIENT.rglob("*.py")):
        if _NOT_OUR_SOURCE & set(path.relative_to(CLIENT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "format"):
                continue
            inner = node.func.value
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "t"
                    and len(inner.args) == 1
                    and isinstance(inner.args[0], ast.Constant)
                    and isinstance(inner.args[0].value, str)):
                continue
            yield path, node.lineno, inner.args[0].value, node


@pytest.fixture(scope="module")
def placeholders():
    return _placeholders_by_key()


@pytest.fixture(scope="module")
def call_sites():
    return list(_format_call_sites())


def test_there_are_call_sites_to_check(call_sites):
    """A matcher that silently stops matching turns this whole file green
    forever — the failure mode that makes a source-level guard worse than no
    guard, because the green run reads as evidence."""
    assert len(call_sites) > 50


def _describe(path, lineno, key, detail):
    return f"{path.relative_to(CLIENT.parent)}:{lineno} t({key!r}) — {detail}"


def test_named_placeholders_are_never_filled_positionally(call_sites, placeholders):
    bad = [
        _describe(path, lineno, key,
                  f"passes {len(node.args)} positional argument(s), but the "
                  f"translation uses named placeholders "
                  f"{sorted(placeholders[key])} — this raises KeyError")
        for path, lineno, key, node in call_sites
        if node.args and placeholders.get(key)
        and all(name.isidentifier() for name in placeholders[key])
    ]
    assert bad == [], "\n".join(bad)


def test_every_placeholder_the_translation_uses_is_supplied(call_sites, placeholders):
    """The other half of the same failure: a named placeholder nobody passes is
    a KeyError too, not a blank."""
    bad = []
    for path, lineno, key, node in call_sites:
        expected = placeholders.get(key)
        if not expected or not all(name.isidentifier() for name in expected):
            continue
        if any(keyword.arg is None for keyword in node.keywords):
            continue  # .format(**mapping) — the keys are not visible here
        missing = expected - {keyword.arg for keyword in node.keywords}
        if missing:
            bad.append(_describe(path, lineno, key,
                                 f"never supplies {sorted(missing)}"))
    assert bad == [], "\n".join(bad)


def test_every_formatted_key_exists_in_some_locale(call_sites, placeholders):
    """I18n.t() is ``translations.get(key, key)``, so a key no locale defines
    renders as its own raw name — and .format() on that name quietly succeeds,
    putting a string like "chat_deleted_ok" in front of the user with no
    error anywhere."""
    unknown = [
        _describe(path, lineno, key, "no locale defines this key")
        for path, lineno, key, _ in call_sites
        if key not in placeholders
    ]
    assert unknown == [], "\n".join(unknown)
