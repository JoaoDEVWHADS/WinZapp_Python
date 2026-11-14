---
name: i18n-ui-string
description: Add, change or remove a user-facing string in WinZapp. Use for readable/spoken UI text or editing translations/*.po and language_map.json. Covers every registered locale, gettext updates, mnemonics, placeholders and validation.
---

# Adding a user-facing string

`I18n.t()` is `translations.get(key, key)` (`client/core/i18n.py`): no
fallback to another locale. A missing key is not an error — the screen reader
speaks the raw key name. So **a key added anywhere is owed by every locale
catalog listed in `client/languages/language_map.json`, in the same change: CI and release
builds reject a missing or fuzzy entry.**

## Polish

Before writing or reviewing any Polish `msgstr`, read
[the Polish glossary](../../../docs/reference/i18n-terminology-pl.md).
Its reviewed terminology takes precedence over older help, changelogs and
unreviewed translations. For a WhatsApp message thread, use `czat`, including
when the English source says `conversation`. Keep `rozmowa` where it actually
means a spoken or AI conversation; never apply a global word replacement.

## Arabic

Before writing or reviewing any Arabic `msgstr`, read
[the Arabic localization notes](../../../docs/reference/arabic-localization.md):
the product name **WinZapp** stays in English inside Arabic sentences, the
singular-key API has no gettext plural entries (write a count as "label:
{count}", never inflect it), and native wx controls are not mirrored for
right-to-left. Its Alt mnemonics are checked against every window the tests
group together, like every other locale.

## Procedure

1. Name the key in English `snake_case`, after its role
   (`status_reply_send`, not `send_button_2`).
2. Add `msgctxt` (stable key) and `msgid` (English source) to
   `translations/en-US/LC_MESSAGES/winzapp.po`.
3. Call it as a literal: `i18n.t("my_key")`. A key built at runtime escapes
   the static check.
4. Update POT and merge every locale with `uv run translations-update`.
   Translate the new blank entries and review changed `fuzzy` entries in
   `translations/<locale>/LC_MESSAGES/winzapp.po`. Preserve translator comments.
   Use `uv run translations-check-draft` while work is pending. When every PO
   is complete, run `uv run translations-compile` and then
   `uv run translations-check`. Never edit generated MO/key-map resources or POT.
   Details: `docs/reference/gettext-migration.md`.
5. Run the tests below.

## Rules

- **`&` is a wx mnemonic.** A literal ampersand is written `&&`. Which letter
  carries the mnemonic is each locale's choice.
- **Placeholders match across locales.** Every string goes through
  `str.format()`; a dropped `{name}` loses information, an invented one
  raises `KeyError`.
- **Reuse the locale's own vocabulary — no test catches this.** Grep the file
  for the term it already uses for the concept (pl says `czat`, en-US
  "chats", pt-BR "conversas") and use it. Where a file is mixed, match the
  strings of the same feature. Changing an established term is a native
  speaker's decision, never a side effect. See
  `docs/reference/i18n-terminology.md`.
- **The string is spoken.** Titles and list items show a contact or group
  name, never a raw JID.

## Verify

```
uv run pytest tests/test_language_files_in_sync.py tests/test_i18n_keys_exist.py
uv run pytest tests/test_gettext_catalogs.py
```

The first compares the locale files with each other (keys, blanks,
mnemonics, placeholders); the second checks every literal `i18n.t("...")` in
`client/**/*.py` exists.

## Adding a locale

Add `"<code>": "<Display Name>"` to `client/languages/language_map.json`
(dict order is the Settings combobox order), run `uv run translations-update`,
translate its new `translations/<code>/LC_MESSAGES/winzapp.po`, then run
`uv run translations-compile` and `uv run translations-check`.
Update the installer/uninstaller tables too (`docs/reference/build-and-setup.md`).
Tests derive the locale list from the map — never repeat it in a test.
