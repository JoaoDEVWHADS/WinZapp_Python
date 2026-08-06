"""Tests for pinning/unpinning an individual message in a chat
(Ctrl+Shift+P / "Fixar mensagem" context menu item).

Unlike _on_menu_star (a local-only flag), pinning a message is WhatsApp's own
feature — visible to every other participant — so it goes through the
WPPConnect API (MainWindow.pin_message) via a background thread, applied
optimistically and rolled back if the server rejects it, mirroring how
conversation pin/unpin (_sync_pin_to_server) already behaves.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against a
small stub — same approach as tests/test_message_bookmarks.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeI18n:
    _STRINGS = {
        "pin_message": "Fixar mensagem",
        "pin_message_failed": "Não foi possível fixar esta mensagem.",
        "unpin_message_failed": "Não foi possível desafixar esta mensagem.",
    }

    def t(self, key):
        return self._STRINGS[key]


class _FakeMainWindow:
    def __init__(self, pin_result=True):
        self.i18n = _FakeI18n()
        self.pin_result = pin_result
        self.pin_calls = []
        self.save_calls = 0

    def pin_message(self, jid, msg_key, pin):
        self.pin_calls.append((jid, dict(msg_key), pin))
        return self.pin_result

    def _schedule_save(self):
        self.save_calls += 1


class _Stub:
    _on_menu_pin_message = ConversationsPanel._on_menu_pin_message
    _on_pin_message_failed = ConversationsPanel._on_pin_message_failed

    def __init__(self, main_window):
        self.main_window = main_window
        self.conversation = {"remoteJid": "5521999999999@s.whatsapp.net"}
        self.populate_calls = []

    def populate_messages(self, preserve_focus=False):
        self.populate_calls.append(preserve_focus)


def _msg(mid="a", pinned=False):
    m = {"key": {"id": mid, "fromMe": True}}
    if pinned:
        m["pinInChat"] = True
    return m


class _ImmediateThread:
    """threading.Thread stand-in that runs the target synchronously on
    .start(), so tests don't race a real background thread."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


@pytest.fixture(autouse=True)
def _synchronous_threads(monkeypatch):
    monkeypatch.setattr("ui.conversations.threading.Thread", _ImmediateThread)
    monkeypatch.setattr("ui.conversations.wx.CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr("ui.conversations.wx.MessageBox", lambda *a, **kw: None)


class TestPinMessage:
    def test_pinning_an_unpinned_message_marks_it_optimistically(self):
        mw = _FakeMainWindow(pin_result=True)
        s = _Stub(mw)
        msg = _msg("a", pinned=False)

        s._on_menu_pin_message(msg)

        assert msg["pinInChat"] is True
        assert mw.save_calls >= 1
        assert s.populate_calls, "list should be re-rendered after the toggle"
        assert mw.pin_calls == [("5521999999999@s.whatsapp.net", {"id": "a", "fromMe": True}, True)]

    def test_unpinning_a_pinned_message_toggles_the_other_way(self):
        mw = _FakeMainWindow(pin_result=True)
        s = _Stub(mw)
        msg = _msg("a", pinned=True)

        s._on_menu_pin_message(msg)

        assert msg["pinInChat"] is False
        assert mw.pin_calls == [("5521999999999@s.whatsapp.net", {"id": "a", "fromMe": True}, False)]

    def test_a_rejected_pin_is_rolled_back(self):
        """The server refusing the request must not leave the message stuck
        showing as pinned/unpinned locally when it never actually took effect."""
        mw = _FakeMainWindow(pin_result=False)
        s = _Stub(mw)
        msg = _msg("a", pinned=False)

        s._on_menu_pin_message(msg)

        assert msg["pinInChat"] is False, "rollback must undo the optimistic pin"

    def test_no_open_conversation_is_a_no_op(self):
        mw = _FakeMainWindow(pin_result=True)
        s = _Stub(mw)
        s.conversation = None
        msg = _msg("a")

        s._on_menu_pin_message(msg)

        assert "pinInChat" not in msg
        assert mw.pin_calls == []
