"""Tests for the Ctrl+Shift+0 Win32 hotkey that reclaims bookmark-0 removal.

Windows binds Ctrl+Shift+0 to a default IME "direct switch" hotkey
(HKCU\\Control Panel\\Input Method\\Hot Keys\\00000104: Virtual Key 0x30,
Key Modifiers 0x06 = Ctrl+Shift) and consumes it before it is dispatched to
any window — so ConversationsPanel's AcceleratorTable, which handles
Ctrl+Shift+1..9 fine, never sees the zero. MainWindow reclaims the combo with
::RegisterHotKey(), which outranks the IME hotkey, but only while its window
is active: the registration is system-global and would otherwise deny the
combo to every other application for as long as WinZapp runs.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the methods under test are exercised as plain functions against a small
stub carrying just the attributes they touch — same approach as
tests/test_send_jid_resolution.py and tests/test_message_bookmarks.py.
"""

import pytest

from main import BOOKMARK_ZERO_HOTKEY_ID, MainWindow


class _FakeConvPanel:
    """Stand-in for the ConversationsPanel's inner conversation view."""

    def __init__(self, shown=True):
        self._shown = shown
        self._parent = None

    def IsShown(self):
        return self._shown

    def GetParent(self):
        return self._parent


class _FakeChild:
    """A control nested somewhere inside the conversation view."""

    def __init__(self, parent):
        self._parent = parent

    def GetParent(self):
        return self._parent


class _FakePanel:
    """Stand-in for ConversationsPanel: records bookmark removals."""

    def __init__(self, conversation_panel):
        self.conversation_panel = conversation_panel
        self.removed = []

    def _on_bookmark_remove(self, digit):
        self.removed.append(digit)


class _Stub:
    """Minimal stand-in for MainWindow for the Ctrl+Shift+0 hotkey paths."""

    def __init__(self, panel=None, focus=None, bound=True, register_ok=True):
        self.conversations_panel = panel
        self._focus = focus
        self._bookmark_zero_hotkey_bound = bound
        self._bookmark_zero_hotkey_on = False
        self._register_ok = register_ok
        self.registered = []
        self.unregistered = []

    # wx.Window.FindFocus() is patched to read this in the fixture below.
    def RegisterHotKey(self, hotkey_id, modifiers, keycode):
        self.registered.append((hotkey_id, modifiers, keycode))
        return self._register_ok

    def UnregisterHotKey(self, hotkey_id):
        self.unregistered.append(hotkey_id)
        return True

    _bookmark_hotkey_panel = MainWindow._bookmark_hotkey_panel
    _set_bookmark_zero_hotkey = MainWindow._set_bookmark_zero_hotkey
    _on_bookmark_zero_hotkey = MainWindow._on_bookmark_zero_hotkey


@pytest.fixture
def focus(monkeypatch):
    """Redirect wx.Window.FindFocus() to a value the test controls."""
    import wx

    holder = {"window": None}
    monkeypatch.setattr(wx.Window, "FindFocus", staticmethod(lambda: holder["window"]))
    return holder


class TestRegistration:
    def test_activation_registers_ctrl_shift_zero(self):
        import wx

        stub = _Stub()
        stub._set_bookmark_zero_hotkey(True)
        assert stub.registered == [
            (BOOKMARK_ZERO_HOTKEY_ID, wx.MOD_CONTROL | wx.MOD_SHIFT, ord("0"))
        ]
        assert stub._bookmark_zero_hotkey_on is True

    def test_deactivation_releases_it_for_other_apps(self):
        stub = _Stub()
        stub._set_bookmark_zero_hotkey(True)
        stub._set_bookmark_zero_hotkey(False)
        assert stub.unregistered == [BOOKMARK_ZERO_HOTKEY_ID]
        assert stub._bookmark_zero_hotkey_on is False

    def test_repeated_activation_does_not_register_twice(self):
        # Modal dialogs toggle the frame's activation state repeatedly; a
        # second ::RegisterHotKey() for the same id would fail.
        stub = _Stub()
        stub._set_bookmark_zero_hotkey(True)
        stub._set_bookmark_zero_hotkey(True)
        assert len(stub.registered) == 1

    def test_deactivation_before_any_registration_is_a_noop(self):
        stub = _Stub()
        stub._set_bookmark_zero_hotkey(False)
        assert stub.unregistered == []

    def test_refused_registration_is_not_treated_as_held(self):
        # Another process already owns the combo: stay off, and don't try to
        # unregister something we never got.
        stub = _Stub(register_ok=False)
        stub._set_bookmark_zero_hotkey(True)
        assert stub._bookmark_zero_hotkey_on is False
        stub._set_bookmark_zero_hotkey(False)
        assert stub.unregistered == []

    def test_nothing_registered_when_the_hotkey_was_never_bound(self):
        # No wx.EVT_HOTKEY support (non-MSW): registering would leave a hotkey
        # nobody listens to.
        stub = _Stub(bound=False)
        stub._set_bookmark_zero_hotkey(True)
        assert stub.registered == []


class TestScope:
    def test_removes_bookmark_zero_when_the_conversation_view_has_focus(self, focus):
        conv = _FakeConvPanel()
        panel = _FakePanel(conv)
        focus["window"] = conv
        _Stub(panel=panel)._on_bookmark_zero_hotkey(None)
        assert panel.removed == [0]

    def test_focus_nested_inside_the_conversation_view_still_counts(self, focus):
        # The accelerator table serving Ctrl+Shift+1..9 fires for any focused
        # descendant, so the zero must too.
        conv = _FakeConvPanel()
        panel = _FakePanel(conv)
        focus["window"] = _FakeChild(_FakeChild(conv))
        _Stub(panel=panel)._on_bookmark_zero_hotkey(None)
        assert panel.removed == [0]

    def test_ignored_when_focus_is_outside_the_conversation_view(self, focus):
        conv = _FakeConvPanel()
        panel = _FakePanel(conv)
        focus["window"] = _FakeChild(None)   # e.g. the conversations list
        _Stub(panel=panel)._on_bookmark_zero_hotkey(None)
        assert panel.removed == []

    def test_ignored_when_no_conversation_is_open(self, focus):
        conv = _FakeConvPanel(shown=False)
        panel = _FakePanel(conv)
        focus["window"] = conv
        _Stub(panel=panel)._on_bookmark_zero_hotkey(None)
        assert panel.removed == []

    def test_ignored_before_the_conversations_panel_exists(self, focus):
        focus["window"] = None
        _Stub(panel=None)._on_bookmark_zero_hotkey(None)   # must not raise
