"""Regression test: starring/unstarring a message (Ctrl+Shift+O / the
"Favoritar"/"Desfavoritar" context-menu item) must survive leaving and
reopening the conversation, not just the current in-memory session.

Root cause of the reported bug ("a opção continua dizendo 'Favoritar' depois
de favoritar uma mensagem"): _on_menu_star() only called
MainWindow._schedule_save(), which persists CHAT metadata via
db.upsert_chat() — it never touches the per-message row in the "messages"
table. navigate_to_conversation() unconditionally reloads a conversation's
messages fresh from the database (db.get_messages()) every time it's opened,
so the in-memory-only "starred" flag was silently dropped the next time the
conversation was reopened, and the context menu offered "Favoritar" again
even though the message was still starred in the currently-open view.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are exercised as plain functions against a
small stub carrying just the attributes they touch — same approach as
tests/test_message_bookmarks.py.
"""

import threading

import pytest

from ui.conversations import ConversationsPanel


class _FakeDB:
    def __init__(self):
        self.inserted = []
        self._event = threading.Event()

    def insert_message(self, jid, msg):
        self.inserted.append((jid, msg))
        self._event.set()

    def wait(self, timeout=2.0):
        """Block until the background persistence thread has run."""
        assert self._event.wait(timeout), "insert_message was never called"


class _FakeI18n:
    def t(self, key):
        return key


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.db = _FakeDB()
        self.save_calls = 0
        self.outputs = []

    def _schedule_save(self, *a, **kw):
        self.save_calls += 1

    def output(self, text, interrupt=False):
        self.outputs.append(text)


class _Stub:
    """Minimal stand-in for ConversationsPanel."""

    _on_menu_star = ConversationsPanel._on_menu_star
    _persist_message_local_flag = ConversationsPanel._persist_message_local_flag
    # _persist_message_local_flag delegates to the bulk form so both share
    # one code path (see its docstring) — the stub needs it bound too.
    _persist_message_local_flags = ConversationsPanel._persist_message_local_flags
    _reject_system_event_action = ConversationsPanel._reject_system_event_action
    _is_system_event = staticmethod(ConversationsPanel._is_system_event)

    def __init__(self, conversation_jid="a@s.whatsapp.net"):
        self.main_window = _FakeMainWindow()
        self.conversation = {"remoteJid": conversation_jid}
        self.populate_calls = []
        self.repainted = []

    def populate_messages(self, preserve_focus=False):
        self.populate_calls.append(preserve_focus)

    def _repaint_or_repopulate(self, msg_ids):
        # The real one repaints the affected rows and only rebuilds the list
        # when it can't — see ConversationsPanel._repaint_message_rows().
        self.repainted.append(sorted(i for i in msg_ids if i))


def _msg(msg_id="MSG1", starred=False, message_type="conversation"):
    return {
        "key": {"id": msg_id, "fromMe": False},
        "message": {"conversation": "oi"},
        "messageType": message_type,
        "starred": starred,
    }


class TestStarPersistsToDatabase:
    def test_starring_writes_the_message_row(self):
        panel = _Stub()
        msg = _msg(starred=False)

        panel._on_menu_star(msg)

        assert msg["starred"] is True
        panel.main_window.db.wait()
        [(jid, saved)] = panel.main_window.db.inserted
        assert jid == "a@s.whatsapp.net"
        assert saved["starred"] is True
        assert saved["key"]["id"] == "MSG1"

    def test_unstarring_persists_false_too(self):
        panel = _Stub()
        msg = _msg(starred=True)

        panel._on_menu_star(msg)

        assert msg["starred"] is False
        panel.main_window.db.wait()
        [(jid, saved)] = panel.main_window.db.inserted
        assert saved["starred"] is False

    def test_toggle_refreshes_only_the_message_row(self):
        panel = _Stub()
        msg = _msg(starred=False)

        panel._on_menu_star(msg)

        assert panel.repainted == [["MSG1"]]
        assert panel.populate_calls == [], "starring one message must not rebuild the whole list"
        assert panel.main_window.save_calls == 1

    def test_system_event_is_not_starred_or_persisted(self):
        panel = _Stub()
        msg = _msg(starred=False, message_type="groupNotification")

        panel._on_menu_star(msg)

        assert msg["starred"] is False
        assert panel.main_window.db.inserted == []
        assert panel.populate_calls == []
        assert panel.repainted == []
