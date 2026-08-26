---
name: accessible-ui
description: Build or change WinZapp UI so screen readers keep working. Use for any edit to client/ui/ (especially conversations.py), client/status_panel.py or the wx code in main.py — adding a control, changing a list, announcing something, wiring a keyboard shortcut. Covers the plain-controls rule, funnelling all speech through speak_output, Freeze/Thaw around list mutations, and the SysListView32 text limit.
---

# Accessible UI

Accessibility is not a finishing pass on this project — it is the reason the
project exists. Users are blind or low-vision and drive the whole app through
NVDA, JAWS or Narrator. A change that "looks fine" and is silent to a screen
reader is a broken change.

## Plain wx controls only

Build from `wx.ListCtrl`, `wx.ListBox`, `wx.TextCtrl`, `wx.Button`,
`wx.CheckBox`, standard menus and standard dialogs. Screen readers read these
through the OS accessibility layer because they are real native controls.

**Never** introduce a custom-drawn or owner-drawn control, or a widget that
paints its own content — it exposes nothing to the OS layer and is simply
invisible to a screen reader. This is not theoretical: the messages list was
once DataView-based and had to be replaced precisely because it was not
natively accessible.

What *is* the house pattern is enriching a standard control with a
`wx.Accessible` subclass. `client/ui/accessible.py` holds ~20 of them, most
just answering `GetKeyboardShortcut()` so the reader announces "Ctrl+Shift+F"
along with the button. Add one there rather than inventing a mechanism, and
wire it with `control.SetAccessible(...)` (`tests/test_setaccessible_wiring.py`
checks the wiring).

## All speech goes through `speak_output`

`MainWindow.speak_output` is an `AccessibleSpeechOutput`
(`client/core/accessible_speech.py`) wrapping accessible_output2's `Auto`. It
is the single gate every spoken announcement passes through, from `main.py`,
`conversations.py`, `websocket_client.py` and `connect.py` alike.

```python
self.main_window.speak_output.output(i18n.t("some_key"))
```

**Never** call accessible_output2 directly and never construct a second `Auto`.
The gate is what makes the Settings > Acessibilidade toggles work at all, and
they are gated in one place on purpose rather than at each call site:

- `extended_sr_compat_enabled` — master switch; off means nothing is spoken.
- `sapi_fallback_enabled` — off means speak only through a real screen reader,
  never the system SAPI voice. Re-evaluated per call, because `is_active()`
  queries the reader live, so turning NVDA off mid-session silences WinZapp
  immediately.

A call site that bypasses the wrapper ignores both toggles and speaks over a
user who asked for silence.

### `output()` vs `silence()`

`output()` is dropped while the "silence while recording a voice message"
suppression window is open. `silence()` deliberately **bypasses** that check:
it exists to cancel speech already in flight — typically the reader's own focus
announcement on the Enviar button as recording starts — which is triggered *by*
the very window that suppresses `output()`.

If you cut off a focus announcement, fire it twice, as
`_silence_for_recording()` does:

```python
self.main_window.speak_output.silence()
wx.CallLater(60, self.main_window.speak_output.silence)
```

Windows dispatches the focus WinEvent to the reader's hook synchronously, but
NVDA speaks it asynchronously on its own thread — an immediate `silence()` can
run before the speech is even queued and cancel nothing. `silence()` is
idempotent, so twice is harmless and covers both schedulings.

## Freeze / Thaw around list mutations

Mutating a list row by row emits one accessibility event per row, and the
reader announces the flood. Batch every multi-row change:

```python
focused = self.messages_list.GetFocusedItem()
self.messages_list.Freeze()
try:
    ...  # inserts, deletes, DeleteAllItems + rebuild
finally:
    self.messages_list.Thaw()
# restore focus, adjusting the index if rows before it moved
```

`try/finally` is not optional — an exception between `Freeze()` and `Thaw()`
leaves the control frozen and the UI dead. Capture and restore the focused row
around the batch, or the user loses their place in the conversation.

## The 511-character limit

Windows' native SysListView32 (what `wx.ListCtrl` wraps) reads item text
through a 512-byte buffer whose last slot holds the terminating NUL, so exactly
**511** characters survive — `_LIST_CTRL_TEXT_LIMIT` in `conversations.py`.
That is what "Ler mais" exists for, and slicing the remainder at 512 instead of
511 is what once made it resume mid-word with a letter missing.

The messages list therefore has two modes (`user_interface.message_list_mode`):
`classic` (`wx.ListCtrl`, truncated) and `listbox`
(`CompatListBoxMessagesCtrl`, a `wx.ListBox` subclass in `client/ui/accessible.py`,
not truncated). Code touching the list must work under **both** — check with
`isinstance(self.messages_list, CompatListBoxMessagesCtrl)` where the two
genuinely differ, as the key-handler wiring does.

## Two things that get read out loud by accident

- **Strip `&` from accessible names and column headers.** `&` is a mnemonic
  marker in a *label*, but headers and accessible names do not interpret it, so
  a stray ampersand is shown and spoken. Existing code writes
  `i18n.t("messages").replace("&", "")`.
- **Never let a raw JID reach the UI.** Dialog titles and list items must
  resolve the contact or group name; otherwise the reader spells out
  phone-number digits, or worse, `@lid` digits that are not even a phone
  number.

Every user-facing string added here also has to exist in all five locales —
see the `i18n-ui-string` skill.

## Verify

```
pytest tests/test_accessible_speech.py tests/test_setaccessible_wiring.py tests/test_silence_while_recording.py tests/test_presence_speech_gating.py tests/test_compat_listbox_refresh_item.py tests/test_accessible_emoji_button.py
```

Most UI behaviour here cannot be asserted headlessly — see the `write-test`
skill for the stub route. What these do cover is the part that regresses
silently: that speech is gated, that `SetAccessible` is actually wired, and
that both list modes get the same treatment.
