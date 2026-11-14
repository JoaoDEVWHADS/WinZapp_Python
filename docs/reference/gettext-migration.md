# gettext translation workflow — issue #381

## Authoritative files

Translations are edited in `translations/<locale>/LC_MESSAGES/winzapp.po`.
English source text and the complete stable-key inventory live in
`translations/en-US/LC_MESSAGES/winzapp.po`. Each entry has a stable `msgctxt`
(the existing `i18n.t("key")` key), a readable English `msgid`, and a translated
`msgstr`. Identical English text with different keys remains distinct.
`client/languages/language_map.json` registers the supported locales and their
display names. Changelogs retain their existing format.

`translations/winzapp.pot` is generated. The runtime carries only compiled MO
files and its generated key map; locale JSON translation files do not exist.

## New and changed messages

Add a key and its original text to the English PO, then call it from Python:

```po
msgctxt "my_new_label"
msgid "New label"
msgstr "New label"
```

From the repository root, using the existing environment:

```powershell
uv run translations-update
```

This regenerates the POT and merges it into every registered locale:

- New keys get an empty `msgstr` and appear as untranslated in PO editors.
- Changed English text retains the existing translation, marks it `fuzzy`,
  and records `previous_msgid` for review. Clear `fuzzy` only after reviewing.
- Removed messages become obsolete rather than being deleted. Reintroducing
  a key can recover its old translation; changed source still needs review.
- Translator comments and metadata survive merges. Extracted source comments
  (`#.` in the English PO) and Python file references (never line numbers, so unrelated edits cannot make the catalogs stale) accompany messages.

The key inventory includes computed keys: it is never inferred from literal
calls alone. An AST scanner adds references to literal `i18n.t(...)` calls and
rejects keys absent from the English catalog. Regenerate after adding/moving
call sites too. Updates are deterministic and do not introduce timestamps.

Translators edit their PO using a text editor, Poedit or another PO editor,
filtering untranslated and fuzzy entries. They do not edit JSON or MO files.
The catalogs become visible in the repository diff; automatic translator
notifications or Weblate account integration are not configured here.

## Validation and compilation

While translations are in progress:

```powershell
uv run translations-check-draft
```

This checks template freshness and completed translations' syntax without
requiring all new/fuzzy entries to be ready. It is not a release gate.
When every translation is reviewed:

```powershell
uv run translations-compile
uv run translations-check
```

Compilation validates **all** locales before writing resources. It refuses
missing, blank and fuzzy required translations, mismatched/malformed Python
format fields and malformed wx mnemonics. Every compiled contextual lookup
is compared with PO, including cases where gettext's ordinary English
fallback could hide a missing entry. Strict checks in the normal pytest suite
exercise the authoritative PO and compiled MO catalogs. A stale POT/PO fails
CI; CI does not commit catalog updates automatically.

The default `compile` generates `client/languages/<locale>/LC_MESSAGES/winzapp.mo`,
the `winzapp.keys` source-text map. MO and the map
are generated resources, ignored by Git. To prepare a separate MO-only bundle:

```powershell
uv run translations-compile --mo-dir build\gettext-preview
```

That folder contains MO, the key map and `language_map.json`, with no PO/POT
or locale JSON files. Windows onefile/onedir/ZIP and macOS build entry points
prepare and package these resources automatically, failing before compilation
if catalogs are stale or incomplete. These changes do not alter signing or
publication workflows.

The `translations-*` aliases run through the project environment. `polib` is a pinned development/build dependency (also needed to run the app from source, which reads the PO files directly);
installed catalog loading uses Python's standard `gettext` library.

## Runtime and manual testing

In development, the shared loader reads editable PO and compiles it in memory,
so direct `cd client; python main.py` works in a clean checkout without MO.
Frozen applications load only MO plus the key map through `resource_path()`.
Neither mode reads locale JSON translation files. The main UI and first-launch language
dialog share this loader; bootstrap retains its English/emergency fallback.
`I18n.t()` still follows the configured language on every lookup and keeps
its existing per-locale cache and raw-key behavior for missing messages.
Development skips untranslated/fuzzy text too; restart the app or invalidate
the cache after editing PO. Release builds refuse to ship such entries.

For a manual test, run `uv run winzapp` normally, switch languages and exercise
startup, language selection and dialogs with formatted messages. The automated
tests do not create visible windows. The Mac layer still receives the same
dictionary from `_load_translations`, so its wording and shortcut adaptations
continue to work.

Plural entries are explicitly rejected until a plural API and locale-specific
`Plural-Forms` policy are implemented; this migration preserves the current
singular-key behavior. Do not add plural entries expecting `I18n.t()` to choose
a form.

To add a locale: register it in `language_map.json`, run `update` to create its
empty PO, translate every entry, then `compile`. Installer/uninstaller locale
tables still need the updates documented in `build-and-setup.md`.

References: [issue #381](https://github.com/gabrielhhaber/WinZapp_Python/issues/381),
[polib API](https://polib.readthedocs.io/en/latest/api.html), and
[Python contextual gettext API](https://docs.python.org/3/library/gettext.html).
