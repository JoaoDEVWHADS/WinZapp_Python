"""Tests for MainWindow._on_bookmark_hotkey_char() — Ctrl+0..9 jumping to an
existing message bookmark regardless of which control has focus.

Reported live: the user asked for bookmark-jump to work "outside the
messages panel" since it already works even with no conversation open at
all (a bookmark jump can navigate to and open a different conversation
entirely). Before this, Ctrl+<digit> only ever fired via
ConversationsPanel's own AcceleratorTable, which requires a descendant of
that specific panel to already have focus.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a stub —
same approach as tests/test_account_hotkey_falls_through.py.
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


class _FakePanel:
    def __init__(self, bookmarks=None):
        self._msg_bookmarks = bookmarks or {}
        self.jump_calls = []

    def _on_bookmark_set_or_jump(self, digit):
        self.jump_calls.append(digit)


class _Stub:
    _on_bookmark_hotkey_char = MainWindow._on_bookmark_hotkey_char

    def __init__(self, panel=None):
        self.conversations_panel = panel


class TestBookmarkHotkeyGlobal:
    def test_existing_bookmark_jumps_and_consumes_the_event(self):
        panel = _FakePanel(bookmarks={3: ("jid", "msg-id")})
        stub = _Stub(panel)
        event = _FakeEvent(wx.MOD_CONTROL, ord("3"))

        stub._on_bookmark_hotkey_char(event)

        assert panel.jump_calls == [3]
        assert event.skipped is False

    def test_no_bookmark_for_that_digit_falls_through(self):
        """Nothing to jump to — must not consume the combo, so
        ConversationsPanel's own AcceleratorTable can still handle it (e.g.
        setting a new bookmark, if the messages list happens to be focused)."""
        panel = _FakePanel(bookmarks={})
        stub = _Stub(panel)
        event = _FakeEvent(wx.MOD_CONTROL, ord("5"))

        stub._on_bookmark_hotkey_char(event)

        assert panel.jump_calls == []
        assert event.skipped is True

    def test_no_conversations_panel_yet_falls_through_safely(self):
        """E.g. very early in startup, before the panel exists."""
        stub = _Stub(panel=None)
        event = _FakeEvent(wx.MOD_CONTROL, ord("1"))

        stub._on_bookmark_hotkey_char(event)

        assert event.skipped is True

    def test_unrelated_combo_is_skipped(self):
        panel = _FakePanel(bookmarks={3: ("jid", "msg-id")})
        stub = _Stub(panel)
        event = _FakeEvent(wx.MOD_CONTROL | wx.MOD_SHIFT, ord("3"))  # Ctrl+Shift+3, not ours

        stub._on_bookmark_hotkey_char(event)

        assert panel.jump_calls == []
        assert event.skipped is True

    def test_non_digit_key_is_skipped(self):
        panel = _FakePanel(bookmarks={3: ("jid", "msg-id")})
        stub = _Stub(panel)
        event = _FakeEvent(wx.MOD_CONTROL, ord("A"))

        stub._on_bookmark_hotkey_char(event)

        assert panel.jump_calls == []
        assert event.skipped is True

    def test_digit_0_is_a_valid_bookmark_slot(self):
        """Unlike the account hotkey (slots 1..9 only), bookmarks use the
        full 0..9 range."""
        panel = _FakePanel(bookmarks={0: ("jid", "msg-id")})
        stub = _Stub(panel)
        event = _FakeEvent(wx.MOD_CONTROL, ord("0"))

        stub._on_bookmark_hotkey_char(event)

        assert panel.jump_calls == [0]
        assert event.skipped is False
