"""Issue #381: translator updates preserve work and MO cannot hide missing text.

Exercise the editable-PO workflow, release gates and real gettext lookups.
"""

from __future__ import annotations

import gettext
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import polib
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.i18n import I18n
from winzapp_tools import translations
from winzapp_tools.gettext_catalogs import (
    check_freshness, compile_catalogs, save_catalogs, updated_catalogs, validate_catalogs,
)
from winzapp_tools.translation_build import prepare_runtime
from winzapp_tools.translation_sources import active_entries, format_fields, load_po, po_path, source_references


@pytest.fixture
def example_root(tmp_path):
    languages = tmp_path / "client" / "languages"
    languages.mkdir(parents=True)
    (languages / "language_map.json").write_text(
        json.dumps({"en-US": "English", "pl": "Polski"}), encoding="utf-8"
    )
    english = {"first": "Open", "second": "Open", "computed": "&Help && info",
               "message": 'Hello {name}\n"quoted"\tC:\\path'}
    polish = {"first": "Otwórz", "second": "Otwarte", "computed": "&Pomoc && info",
              "message": 'Cześć {name}\n"cytat"\tC:\\ścieżka'}
    for code, values in (("en-US", english), ("pl", polish)):
        catalog = polib.POFile(encoding="utf-8")
        for key, text in english.items():
            catalog.append(polib.POEntry(msgctxt=key, msgid=text, msgstr=values[key]))
        path = po_path(tmp_path / "translations", code)
        path.parent.mkdir(parents=True)
        catalog.save(str(path))
    (tmp_path / "client" / "panel.py").write_text(
        "i18n.t('first')\nself.i18n.t(\n    'message'\n)\ni18n.t(key)\nother.t('unrelated')\n",
        encoding="utf-8",
    )
    save_catalogs(tmp_path / "translations", updated_catalogs(tmp_path))
    prepare_runtime(tmp_path)
    return tmp_path


def edit_catalog(root, code, edit):
    path = po_path(root / "translations", code)
    catalog = load_po(path)
    edit(catalog)
    catalog.save(str(path))


def merge(root):
    catalogs = updated_catalogs(root)
    save_catalogs(root / "translations", catalogs)
    return catalogs


class TestTranslatorWorkflow:
    def test_new_key_is_blank_in_target_and_translated_in_source(self, example_root):
        edit_catalog(example_root, "en-US", lambda c: c.append(
            polib.POEntry(msgctxt="new_key", msgid="New label")))
        catalogs = merge(example_root)
        target = active_entries(catalogs[Path("pl/LC_MESSAGES/winzapp.po")])
        source = active_entries(catalogs[Path("en-US/LC_MESSAGES/winzapp.po")])
        assert target["new_key"].msgstr == ""
        assert not target["new_key"].fuzzy
        assert source["new_key"].msgstr == "New label"
        assert "computed" in active_entries(catalogs[Path("winzapp.pot")])

    def test_changed_source_preserves_translation_comments_and_marks_fuzzy(self, example_root):
        def annotate(catalog):
            active_entries(catalog)["first"].tcomment = "Translator explanation"
            catalog.metadata["Last-Translator"] = "Example translator"
        edit_catalog(example_root, "pl", annotate)
        def change(catalog):
            active_entries(catalog)["first"].msgid = "Open the item"
            active_entries(catalog)["first"].comment = "Source context for translators"
        edit_catalog(example_root, "en-US", change)
        catalogs = merge(example_root)
        target = catalogs[Path("pl/LC_MESSAGES/winzapp.po")]
        entry = active_entries(target)["first"]
        assert entry.msgstr == "Otwórz"
        assert entry.msgid == "Open the item"
        assert entry.fuzzy and entry.previous_msgid == "Open"
        assert entry.tcomment == "Translator explanation"
        assert entry.comment == "Source context for translators"
        assert target.metadata["Last-Translator"] == "Example translator"
        # Updating twice must not lose history or clear the pending review.
        assert active_entries(merge(example_root)[Path("pl/LC_MESSAGES/winzapp.po")])["first"].fuzzy

    def test_translation_edits_survive_update_and_are_not_marked_fuzzy(self, example_root):
        def translate(catalog):
            entry = active_entries(catalog)["first"]
            entry.msgstr = "Nowy tekst"
            entry.tcomment = "Reviewed"
        edit_catalog(example_root, "pl", translate)
        entry = active_entries(merge(example_root)[Path("pl/LC_MESSAGES/winzapp.po")])["first"]
        assert entry.msgstr == "Nowy tekst" and entry.tcomment == "Reviewed"
        assert not entry.fuzzy

    def test_removed_key_is_obsolete_and_can_be_restored_without_losing_translation(self, example_root):
        edit_catalog(example_root, "en-US", lambda c: setattr(active_entries(c)["computed"], "obsolete", True))
        catalog = merge(example_root)[Path("pl/LC_MESSAGES/winzapp.po")]
        assert "computed" not in active_entries(catalog)
        obsolete = next(e for e in catalog if e.msgctxt == "computed")
        assert obsolete.obsolete and obsolete.msgstr == "&Pomoc && info"
        edit_catalog(example_root, "en-US", lambda c: setattr(
            next(e for e in c if e.msgctxt == "computed"), "obsolete", False))
        restored = active_entries(merge(example_root)[Path("pl/LC_MESSAGES/winzapp.po")])["computed"]
        assert not restored.obsolete and restored.msgstr == "&Pomoc && info"

    def test_new_registered_locale_gets_untranslated_entries(self, example_root):
        path = example_root / "client/languages/language_map.json"
        names = json.loads(path.read_text(encoding="utf-8"))
        names["ro"] = "Română"
        path.write_text(json.dumps(names), encoding="utf-8")
        catalog = merge(example_root)[Path("ro/LC_MESSAGES/winzapp.po")]
        assert len(catalog) == 4 and all(e.msgstr == "" for e in catalog)

    def test_scan_skips_vendored_python_and_handles_multiline_single_quotes(self, example_root):
        path = example_root / "client/api/broken.py"
        path.parent.mkdir()
        path.write_text("invalid Python !!!", encoding="utf-8")
        assert source_references(example_root) == {
            "first": [("client/panel.py", "")], "message": [("client/panel.py", "")]
        }

    def test_moving_a_call_inside_a_source_file_does_not_make_catalogs_stale(self, example_root):
        """Line numbers are not part of the freshness check: an unrelated edit
        above an i18n.t() call must not fail every build until regenerated."""
        panel = example_root / "client/panel.py"
        panel.write_text("# unrelated edit\n\n" + panel.read_text(encoding="utf-8"), encoding="utf-8")
        check_freshness(example_root / "translations", updated_catalogs(example_root))

    def test_unknown_literal_key_is_rejected(self, example_root):
        (example_root / "client/missing.py").write_text("i18n.t('unknown')", encoding="utf-8")
        with pytest.raises(ValueError, match="missing translation keys.*unknown"):
            updated_catalogs(example_root)


class TestCatalogGates:
    @pytest.mark.parametrize("problem", ["empty", "fuzzy", "placeholder", "mnemonic"])
    def test_invalid_target_cannot_be_compiled(self, example_root, problem):
        def damage(catalog):
            entry = active_entries(catalog)["message"]
            if problem == "empty":
                entry.msgstr = " "
            elif problem == "fuzzy":
                entry.fuzzy = True
            elif problem == "placeholder":
                entry.msgstr = "Hello {invented}"
            else:
                entry.msgstr = "{name} & info"
        edit_catalog(example_root, "pl", damage)
        catalogs = updated_catalogs(example_root)
        with pytest.raises(ValueError, match="Catalog validation failed"):
            compile_catalogs(catalogs)
        destination = example_root / "rejected"
        with pytest.raises(ValueError):
            prepare_runtime(example_root, destination)
        assert not destination.exists()

    def test_incomplete_check_allows_review_but_compile_does_not(self, example_root, monkeypatch):
        monkeypatch.setattr(translations, "ROOT", example_root)
        edit_catalog(example_root, "en-US", lambda c: c.append(
            polib.POEntry(msgctxt="new_key", msgid="New label")))
        assert translations.main(["update"]) == 0
        assert translations.main(["check", "--allow-incomplete"]) == 0
        assert translations.main(["check"]) == 1
        assert translations.main(["compile"]) == 1

    def test_source_change_must_be_merged_before_build(self, example_root):
        edit_catalog(example_root, "en-US", lambda c: setattr(active_entries(c)["first"], "msgid", "Changed"))
        with pytest.raises(ValueError, match="Stale catalogs"):
            prepare_runtime(example_root, example_root / "rejected")

    def test_duplicate_context_even_with_different_msgid_is_rejected(self, example_root):
        edit_catalog(example_root, "pl", lambda c: c.append(
            polib.POEntry(msgctxt="first", msgid="Another source", msgstr="Text")))
        with pytest.raises(ValueError, match="Duplicate stable key"):
            updated_catalogs(example_root)

    def test_empty_source_cannot_turn_into_an_empty_release(self, example_root):
        edit_catalog(example_root, "en-US", lambda c: c.clear())
        with pytest.raises(ValueError, match="source catalog must not be empty"):
            updated_catalogs(example_root)

    def test_wrong_charset_metadata_requires_update_before_build(self, example_root):
        edit_catalog(example_root, "pl", lambda c: c.metadata.update({"Content-Type": "text/plain; charset=ASCII"}))
        with pytest.raises(ValueError, match="Stale catalogs"):
            check_freshness(example_root / "translations", updated_catalogs(example_root))
        merge(example_root)
        check_freshness(example_root / "translations", updated_catalogs(example_root))

    def test_unregistered_po_cannot_escape_validation(self, example_root):
        (example_root / "translations/unknown.po").write_text("# Unexpected catalog", encoding="utf-8")
        with pytest.raises(ValueError, match="Unregistered PO"):
            updated_catalogs(example_root)

    def test_freshness_ignores_po_order_wrapping_and_translator_dates(self, example_root):
        def reorder(catalog):
            catalog.reverse()
            catalog.wrapwidth = 60
            catalog.metadata["PO-Revision-Date"] = "2026-10-06 12:00-0300"
        edit_catalog(example_root, "pl", reorder)
        check_freshness(example_root / "translations", updated_catalogs(example_root))

    def test_format_fields_include_nested_specs_but_ignore_escaped_braces(self):
        assert format_fields("{{literal}} {value:{width}.{precision}f}") == {"value", "width", "precision"}

    def test_missing_mo_entry_cannot_hide_behind_english_fallback(self, example_root, monkeypatch):
        original = polib.POFile.to_binary
        def drop_entry(catalog):
            catalog[0].msgstr = ""
            return original(catalog)
        monkeypatch.setattr(polib.POFile, "to_binary", drop_entry)
        with pytest.raises(ValueError, match="MO is missing context"):
            compile_catalogs(updated_catalogs(example_root))


class TestCompilation:
    def test_duplicate_english_text_unicode_newlines_and_wx_markers_survive(self, example_root):
        binaries = compile_catalogs(updated_catalogs(example_root))
        translator = gettext.GNUTranslations(io.BytesIO(binaries[Path("pl/LC_MESSAGES/winzapp.mo")]))
        assert translator.pgettext("first", "Open") == "Otwórz"
        assert translator.pgettext("second", "Open") == "Otwarte"
        assert translator.pgettext("message", 'Hello {name}\n"quoted"\tC:\\path') == (
            'Cześć {name}\n"cytat"\tC:\\ścieżka'
        )
        assert translator.pgettext("computed", "&Help && info") == "&Pomoc && info"

    def test_build_payload_has_only_key_map_language_names_and_mo(self, example_root):
        destination = example_root / "packaged"
        payload = prepare_runtime(example_root, destination)
        assert set(payload) == {
            Path("language_map.json"), Path("winzapp.keys"),
            Path("en-US/LC_MESSAGES/winzapp.mo"), Path("pl/LC_MESSAGES/winzapp.mo")
        }
        assert not list(destination.rglob("*.po"))
        assert not (destination / "pl.json").exists()
        assert json.loads((destination / "winzapp.keys").read_text(encoding="utf-8"))["first"] == "Open"

    def test_update_check_compile_commands(self, example_root, monkeypatch):
        monkeypatch.setattr(translations, "ROOT", example_root)
        assert translations.main(["update"]) == 0
        assert translations.main(["compile"]) == 0
        assert translations.main(["check"]) == 0
        assert translations.main(["compile", "--mo-dir", str(example_root / "mo")]) == 0


def test_all_authoritative_po_translations_match_runtime():
    """CI gate covers every key in every registered locale, plus MO completeness."""
    catalogs = updated_catalogs(ROOT)
    check_freshness(ROOT / "translations", catalogs)
    validate_catalogs(catalogs)
    binaries = compile_catalogs(catalogs)
    english = active_entries(catalogs[Path("en-US/LC_MESSAGES/winzapp.po")])
    I18n.invalidate_cache()
    try:
        for relative, catalog in catalogs.items():
            if relative.suffix != ".po":
                continue
            locale = relative.parts[0]
            runtime = I18n(SimpleNamespace(settings={"general": {"language": locale}}))
            translator = gettext.GNUTranslations(io.BytesIO(binaries[relative.with_suffix(".mo")]))
            for key, entry in active_entries(catalog).items():
                assert translator.pgettext(key, english[key].msgid) == runtime.t(key) == entry.msgstr
    finally:
        I18n.invalidate_cache()
