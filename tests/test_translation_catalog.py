"""The live gettext loader must work before settings, without JSON fallback.

Both development PO and packaged MO keep the stable-key API, and fuzzy/absent
entries must not silently turn into English. No window is constructed.
"""

import builtins
import json
from pathlib import Path
from types import SimpleNamespace

import polib
import pytest

from core import i18n, translation_catalog
import app_paths
from ui.dialogs import language_dialog


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    client = tmp_path / "client"
    folder = tmp_path / "translations/pl/LC_MESSAGES"
    folder.mkdir(parents=True)
    client.mkdir()
    catalog = polib.POFile(encoding="utf-8")
    catalog.metadata = {"Content-Type": "text/plain; charset=UTF-8"}
    catalog.append(polib.POEntry(msgctxt="key", msgid="English", msgstr="Polski"))
    catalog.append(polib.POEntry(msgctxt="pending", msgid="Pending", msgstr="", flags=[]))
    catalog.append(polib.POEntry(msgctxt="review", msgid="Changed", msgstr="Old", flags=["fuzzy"]))
    catalog.save(str(folder / "winzapp.po"))
    languages = client / "languages"
    mo = languages / "pl/LC_MESSAGES/winzapp.mo"
    mo.parent.mkdir(parents=True)
    mo.write_bytes(catalog.to_binary())
    (languages / "winzapp.keys").write_text(json.dumps({
        "key": "English", "pending": "Pending", "review": "Changed"
    }), encoding="utf-8")
    monkeypatch.setattr(translation_catalog, "resource_path", lambda *parts: str(client.joinpath(*parts)))
    monkeypatch.setattr(translation_catalog, "_is_frozen", lambda: False)
    i18n.I18n.invalidate_cache()
    yield client, folder, catalog
    i18n.I18n.invalidate_cache()


def test_dev_reads_po_even_if_mo_and_json_are_stale(catalog_env):
    _, folder, catalog = catalog_env
    catalog[0].msgstr = "Nowy tekst"
    catalog.save(str(folder / "winzapp.po"))
    runtime = i18n.I18n(SimpleNamespace(settings={"general": {"language": "pl"}}))
    assert runtime.t("key") == "Nowy tekst"
    assert runtime.t("pending") == "pending"
    assert runtime.t("review") == "review"
    assert runtime.t("unknown") == "unknown"


def test_packaged_loader_uses_mo_without_importing_polib(catalog_env, monkeypatch):
    monkeypatch.setattr(translation_catalog, "_is_frozen", lambda: True)
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        assert name != "polib", "Packaged runtime must use only standard gettext"
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", importing)
    assert translation_catalog.load_catalog("pl") == {"key": "Polski"}


@pytest.mark.parametrize("layout", ["onedir", "onefile"])
def test_packaged_loader_uses_real_resource_paths_for_both_layouts(catalog_env, monkeypatch, layout):
    client, _, _ = catalog_env
    if layout == "onedir":
        executable_dir = client
        extraction = client / "_internal"
    else:
        executable_dir = client / "elsewhere"
        extraction = client
    monkeypatch.setattr(app_paths.sys, "executable", str(executable_dir / "WinZapp.exe"))
    monkeypatch.setattr(app_paths.sys, "_MEIPASS", str(extraction), raising=False)
    monkeypatch.setattr(translation_catalog, "_is_frozen", lambda: True)
    monkeypatch.setattr(translation_catalog, "resource_path", app_paths.resource_path)
    assert translation_catalog.load_catalog("pl") == {"key": "Polski"}


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_missing_or_corrupt_mo_does_not_fall_back_to_legacy_json(catalog_env, monkeypatch, damage):
    client, _, _ = catalog_env
    monkeypatch.setattr(translation_catalog, "_is_frozen", lambda: True)
    path = client / "languages/pl/LC_MESSAGES/winzapp.mo"
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"invalid MO")
    assert translation_catalog.load_catalog("pl") == {}


def test_cache_invalidation_reloads_an_edited_po(catalog_env):
    _, folder, catalog = catalog_env
    runtime = i18n.I18n(SimpleNamespace(settings={"general": {"language": "pl"}}))
    assert runtime.t("key") == "Polski"
    catalog[0].msgstr = "New"
    catalog.save(str(folder / "winzapp.po"))
    assert runtime.t("key") == "Polski"
    runtime.invalidate_cache()
    assert runtime.t("key") == "New"


@pytest.mark.parametrize("locale", ["../pl", "pl/other", "pl\\other", "", None])
def test_invalid_locale_cannot_escape_the_catalog_directory(catalog_env, locale):
    assert translation_catalog.load_catalog(locale) == {}


def test_bootstrap_falls_back_if_requested_catalog_lacks_any_required_key(monkeypatch):
    english = {key: f"English {key}" for key in language_dialog._BOOTSTRAP_KEYS}
    monkeypatch.setattr(language_dialog, "load_catalog", lambda code: (
        {"ok": "&OK"} if code == "pl" else english
    ))
    assert language_dialog._load_bootstrap_strings("pl") == english


def test_bootstrap_has_emergency_copy_if_no_catalog_can_be_read(monkeypatch):
    monkeypatch.setattr(language_dialog, "load_catalog", lambda code: {})
    assert language_dialog._load_bootstrap_strings("pl") == language_dialog._HARDCODED_BOOTSTRAP_STRINGS
