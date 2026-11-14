---
name: extract-from-god-file
description: Pull logic out of WinZapp's big classes (MainWindow in client/main.py + client/main_window/, ConversationsPanel in client/ui/conversations.py + client/ui/conversation_panel/, StatusPanel in client/status_panel.py) without changing behaviour. Use when asked to extract, split, shrink or refactor them, when a mixin module is outgrowing its size budget, when a method is too tangled to test, or when a bug fix keeps being blocked by not being able to reach the logic from a test.
---

# Extracting from the big classes

`MainWindow`, `ConversationsPanel` and `StatusPanel` are each one small file
(`client/main.py`, `client/ui/conversations.py`, `client/status_panel.py`)
plus one mixin module per responsibility (`client/main_window/`,
`client/ui/conversation_panel/`, `client/status_tab/`). Each package's
`__init__.py` is the map. A method on a mixin still needs a stub to be tested.

Two jobs:

1. **Extract logic from a method into a plain function** (the usual one).
2. **Split a module** that outgrew its budget (rare, tool-driven).

## Job 1 — extract into a plain function

Do it only if it turns a stub test into a direct one, or makes untestable
logic testable.

- Destination: a plain-function module in the same package
  (`main_window/message_rules.py`, `main_window/identity_rules.py`,
  `conversation_panel/media_paths.py`, `conversation_panel/selection_rules.py`,
  or a new `*_rules.py`), or `client/core/` when the slice has its own state
  or lifecycle.
- Shape: copy `is_countable_message()` in `main_window/message_rules.py` —
  type-annotated, arguments instead of `self`, a docstring that says why.

## Job 2 — split a module

Use the tool, never a hand move of hundreds of lines:

```
uv run python winzapp_tools/god_split/split_god_class.py <config.py>
uv run python winzapp_tools/god_split/verify_split.py main <god file> <Class> <package dir>
uv run python winzapp_tools/god_split/verify_imports.py
uv run python winzapp_tools/god_split/verify_instance_access.py main
```

`config_main_window.py` / `config_conversation_panel.py` in that folder are
worked examples. `verify_split.py` must report every node identical except
the ones rewritten on purpose; list those in the commit message.
`verify_instance_access.py` checks names reached through `self.main_window`,
`self._mw`, `mw`, `getattr(mw, "x", None)`.

Splitting one mixin module in two: move whole methods (with the comments
above them) into the new module's mixin class and add it to the class bases.

## Procedure

1. **Baseline**: `uv run pytest -q` for a split (job 2); the test files of the
   area for job 1. Record the count.
2. **Characterize first** (job 1): a test of today's behaviour that passes
   before and after, unchanged (see `write-test`).
3. **One responsibility per pass.**
4. **Move verbatim**: no renames, no reformatting, no drive-by fixes.
5. **Leave no copy behind**: the old method disappears or becomes a one-line
   call.
6. **Add the direct test** the extraction made possible (job 1).
7. **Verify**: same tests, same count plus the new ones.

## Traps of the split layout

- **A module global is looked up where the method is defined.** Tests patch
  through `tests/god_modules.py` (`patch_main_global()`,
  `patch_conversations_global()`), never `monkeypatch.setattr(main, ...)`.
- **Source-text tests** read through `main_window_source()` /
  `main_window_method_source()` (and the `conversations_*` twins), never by
  slicing a file between two `def`s.
- **A mixin never imports `main`** (it would execute `main.py` twice). Reach
  another mixin's static member by importing that mixin class, or through
  `self`.
- **Classmethods** called as `SomeMixin.method(...)` get `cls=SomeMixin`:
  any `cls.X` inside must be defined on that mixin.
- **`__file__`** in a moved method points into the package directory — see
  `_MAIN_PY` in `main_window/sending.py`.
- **Two mixins defining the same name**: the earlier in the MRO silently
  wins. `tests/test_god_file_split_structure.py` catches it.
- **`.claude/rules/*.md` fire by path**: a rule naming the old file must also
  name the module the code moved to.

## What must not change

JID normalization (`@lid`/phone bridge, 8/9-digit handling, fake-`@g.us`
guard), the `_live_events_ready()` gate, echo matching by message type,
speech and list mutation (`accessible-ui`), anything touching the locales
(`i18n-ui-string`). If a clean extraction seems to require changing one of
these, stop: the extraction is wrong.

Do not add ruff, mypy, a pre-commit hook or a coverage threshold — that is a
team decision.

## Finishing

Report `wc -l` before/after of every file touched, baseline and final test
counts, the `verify_split.py` summary line when code moved, and what is now
directly testable. Then hand the diff to `winzapp-reviewer`.
