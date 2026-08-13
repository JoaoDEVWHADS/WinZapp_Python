"""Tests for MainWindow._on_account_hotkey_char() correctly releasing
Ctrl+Alt+<digit> when there's no paired-account slot to switch to.

Originally Ctrl+Shift+1..9, moved to Ctrl+Alt+1..9: this frame-level
EVT_CHAR_HOOK handler (bound so the combo works "no matter which child
control holds focus") used to consume EVERY Ctrl+Shift+1..9 keystroke
unconditionally — even when _account_hotkey_slots had no entry for that
digit (any install with fewer than <digit> paired accounts, including
every single-account install) — instead of calling event.Skip() to let it
fall through. That silently broke the pre-existing, non-multi-account
message-bookmark-removal shortcut (ConversationsPanel._on_bookmark_remove,
Ctrl+Shift+0..9), which shared the same combo and never got a chance to
run. Fixed two ways: this handler now only ever consumes the combo when a
real target slot exists, AND the combo itself moved to Ctrl+Alt so the two
features no longer share one at all.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a stub —
same approach as the rest of this test suite.
"""

import wx

from main import MainWindow


class _FakeEvent:
    def __init__(self, modifiers, key_code):
        self._modifiers = modifiers
        self._key_code = key_code
        self.skipped = False

    def GetModifiers(self):
        return self._modifiers

    def GetKeyCode(self):
        return self._key_code

    def Skip(self):
        self.skipped = True


class _Stub:
    _on_account_hotkey_char = MainWindow._on_account_hotkey_char

    def __init__(self, slots=None, account_id="current-account"):
        self._account_hotkey_slots = slots or {}
        self.account_id = account_id
        self.switch_calls = []

    def _switch_to_account(self, target):
        self.switch_calls.append(target)


_CA = wx.MOD_CONTROL | wx.MOD_ALT


class TestAccountHotkeyFallsThrough:
    def test_no_account_at_that_slot_skips_the_event(self):
        """Single-account install (or fewer than <digit> paired accounts) —
        nothing to switch to, so the combo must fall through."""
        stub = _Stub(slots={})
        event = _FakeEvent(_CA, ord("3"))

        stub._on_account_hotkey_char(event)

        assert event.skipped is True
        assert stub.switch_calls == []

    def test_existing_slot_switches_and_consumes_the_event(self):
        stub = _Stub(slots={3: "other-account"})
        event = _FakeEvent(_CA, ord("3"))

        stub._on_account_hotkey_char(event)

        assert event.skipped is False
        assert stub.switch_calls == ["other-account"]

    def test_slot_matching_the_current_account_consumes_without_switching(self):
        """A no-op self-switch still consumes the combo — it IS the account
        hotkey feature's combo, just aimed at the account already running."""
        stub = _Stub(slots={3: "current-account"}, account_id="current-account")
        event = _FakeEvent(_CA, ord("3"))

        stub._on_account_hotkey_char(event)

        assert event.skipped is False
        assert stub.switch_calls == []

    def test_unrelated_combo_is_skipped(self):
        stub = _Stub(slots={3: "other-account"})
        event = _FakeEvent(wx.MOD_CONTROL, ord("3"))  # Ctrl+3, no Alt

        stub._on_account_hotkey_char(event)

        assert event.skipped is True
        assert stub.switch_calls == []

    def test_ctrl_shift_no_longer_belongs_to_this_handler(self):
        """The combo moved to Ctrl+Alt specifically so Ctrl+Shift+<digit>
        would stop being intercepted here — it's the message-bookmark-
        removal shortcut's combo now, unshared."""
        stub = _Stub(slots={3: "other-account"})
        event = _FakeEvent(wx.MOD_CONTROL | wx.MOD_SHIFT, ord("3"))

        stub._on_account_hotkey_char(event)

        assert event.skipped is True
        assert stub.switch_calls == []

    def test_digit_0_is_never_ours_and_always_falls_through(self):
        """Only slots 1..9 exist (_MAX_HOTKEY_SLOTS in account_ui.py) —
        Ctrl+Alt+0 was never this feature's combo."""
        stub = _Stub(slots={0: "should-not-happen"})
        event = _FakeEvent(_CA, ord("0"))

        stub._on_account_hotkey_char(event)

        assert event.skipped is True
        assert stub.switch_calls == []
