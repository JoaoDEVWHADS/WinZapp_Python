---
name: i18n-ui-string
description: Add, change or remove a user-facing string in WinZapp. Use whenever a change introduces text a person can read or a screen reader can speak — dialog titles, buttons, menu items, list labels, error boxes, notifications, tooltips — or whenever a file under client/languages/ needs editing. Covers all five locales, the mnemonic and placeholder rules, and the tests that enforce them.
---

# Adding a user-facing string

## The invariant

`I18n.t()` is `translations.get(key, key)` (`client/core/i18n.py`). There is **no
per-key fallback to any other locale** — not even to pt-BR, the locale the app
defaults to. A key missing from the file in use is not an error and is not
logged: the raw key name is what reaches the UI, and in an app built for blind
users, `about_license` is what the screen reader says out loud.

That is not hypothetical. `pl.json` once drifted 68 keys behind while features
were added, and nothing failed until someone switched the app to Polish
(`fe73e81`). Separately, the Status recorder asked for `voice_recording` and
`recording_paused` when *no* locale had them, so NVDA read those two literal
strings to users.

So: **a key added anywhere is owed by every locale.** All five files, same
commit.

## The procedure

1. Pick a key name: `snake_case`, English, descriptive of the role rather than
   the text (`status_reply_send`, not `send_button_2`). Keys are never
   translated — only values are.
2. Add the key to **all five** files in `client/languages/`:
   `pt-BR.json`, `pt-PT.json`, `en-US.json`, `es-ES.json`, `pl.json`.
   Every one gets a real translation; a blank value fails the suite.
3. Call it as a **literal**: `i18n.t("my_key")` / `self.i18n.t("my_key")`. A key
   assembled at runtime (f-string, variable) cannot be resolved statically, so
   it escapes the code-side check entirely and is back to failing silently.
4. Run the tests (below) before committing.

## The traps the tests exist for

- **`&` is a wx mnemonic, not the word "and".** wx reads `&` in a label as "the
  next character is this control's Alt shortcut", so a translator writing
  "Fotos & vídeos" silently eats a character and hands the shortcut to whatever
  followed — which is how pt-PT shipped a broken label. A literal ampersand
  must be written `&&`. Which letter carries the mnemonic is a per-language
  decision; the locales are not required to agree on placement.
- **Placeholders must match exactly across locales.** Every string goes through
  `str.format()`. A translation that drops `{name}` silently loses information;
  one that invents a placeholder the call site does not pass raises `KeyError`
  at runtime. The check compares all locales that define the key against each
  other, not against a reference file.
- **The expected key set is the union of all five files, not pt-BR's.** Adding
  a key to en-US and forgetting pt-BR is exactly as broken as the reverse, and
  the failure lands on the default locale. Whichever file is behind is the one
  that fails.
- **Accessibility outranks brevity.** The string is spoken, not skimmed. Dialog
  titles and list items must resolve a human-readable name (contact/group)
  rather than a raw JID, or NVDA reads phone-number digits aloud.

## Verify

```
pytest tests/test_language_files_in_sync.py tests/test_i18n_keys_exist.py
```

The first checks the five files against each other (union of keys, no blanks,
mnemonics, placeholders). The second scans `client/**/*.py` for literal
`i18n.t("...")` calls and asserts every key the code asks for exists — that is
the direction the first one cannot see, since five files can agree perfectly
while all missing the same key.

## Adding a whole new locale

Rarer, and the locale list is data rather than code: drop `<code>.json` into
`client/languages/` and add `"<code>": "<Display Name>"` to
`language_map.json`. Dict order there is the order of the Settings combobox.
No rebuild is needed.

Every test that iterates locales derives the list from `language_map.json`,
so a new locale is picked up on its own — `test_language_files_in_sync.py`,
`test_i18n_keys_exist.py`, `test_menu_mnemonics_dont_collide.py`,
`test_self_reference_label.py` and `test_mute.py`. Keep it that way: a list
written out in a test file goes stale the moment a locale is added and
silently stops checking it, which is exactly how `pl` ended up unchecked by
`test_self_reference_label.py` — the only place that verifies
`ui_self_reference_eu` and `ui_self_reference_voce` are *distinct*, since the
union check catches a missing or blank value but never two identical ones.
