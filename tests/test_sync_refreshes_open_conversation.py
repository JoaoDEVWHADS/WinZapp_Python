"""Regression test: reconnecting from offline mode and resyncing left an
already-open conversation showing stale messages until closed and reopened.

sync_chat_messages() does `self.chats[remote_jid] = chat` — a NEW dict
object, not a mutation of the old one (see main.py). ConversationsPanel.
conversation, if that chat was open, kept pointing at the now-orphaned old
object: its message list showed exactly what was loaded before the sync
(e.g. before the app went offline) no matter how many messages the sync
merged in, until the user pressed Esc and reopened the conversation.

MainWindow._refresh_open_conversation_after_sync() now points the panel at
the new object and forces a repaint when the synced chat is the one open.
Exercised as a plain function bound to a stub, per the project's convention
for MainWindow (a wx.Frame) — see tests/test_reported_bugfixes.py.
"""

import wx

from main import MainWindow


class _FakePanel:
    def __init__(self, conversation):
        self.conversation = conversation
        self.refresh_calls = 0

    def refresh_messages_if_changed(self):
        self.refresh_calls += 1


class _MainWindowStub:
    _refresh_open_conversation_after_sync = MainWindow._refresh_open_conversation_after_sync
    _chat_jids_equivalent = MainWindow._chat_jids_equivalent
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _jid_address_forms = MainWindow._jid_address_forms

    def __init__(self, conversations_panel=None):
        self.conversations_panel = conversations_panel
        self._lid_to_phone = {}
        self._phone_to_lid = {}


def test_swaps_the_open_conversation_to_the_new_object_and_repaints(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    old_chat = {"remoteJid": "a@g.us", "messages": {"messages": {"records": []}}}
    panel = _FakePanel(old_chat)
    mw = _MainWindowStub(panel)
    new_chat = {"remoteJid": "a@g.us", "messages": {"messages": {"records": [{"key": {"id": "M1"}}]}}}

    mw._refresh_open_conversation_after_sync("a@g.us", new_chat)

    assert panel.conversation is new_chat
    assert panel.refresh_calls == 1


def test_a_different_open_conversation_is_left_alone(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    old_chat = {"remoteJid": "b@g.us"}
    panel = _FakePanel(old_chat)
    mw = _MainWindowStub(panel)

    mw._refresh_open_conversation_after_sync("a@g.us", {"remoteJid": "a@g.us"})

    assert panel.conversation is old_chat
    assert panel.refresh_calls == 0


def test_no_conversation_open_is_a_no_op(monkeypatch):
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    panel = _FakePanel(None)
    mw = _MainWindowStub(panel)

    mw._refresh_open_conversation_after_sync("a@g.us", {"remoteJid": "a@g.us"})

    assert panel.conversation is None
    assert panel.refresh_calls == 0


def test_no_conversations_panel_yet_is_a_no_op():
    mw = _MainWindowStub(conversations_panel=None)

    mw._refresh_open_conversation_after_sync("a@g.us", {"remoteJid": "a@g.us"})  # must not raise


def test_user_navigated_away_before_callafter_runs_is_not_overwritten():
    """CallAfter defers to the main thread — re-check at that point, not
    just when the background sync thread made the call."""
    old_chat = {"remoteJid": "a@g.us"}
    panel = _FakePanel(old_chat)
    mw = _MainWindowStub(panel)
    deferred = []

    import wx as wx_module
    real_call_after = wx_module.CallAfter
    wx_module.CallAfter = lambda fn, *a, **kw: deferred.append(lambda: fn(*a, **kw))
    try:
        mw._refresh_open_conversation_after_sync("a@g.us", {"remoteJid": "a@g.us", "messages": {}})
        # User switches to a different conversation before the main thread
        # gets around to running the deferred callback.
        panel.conversation = {"remoteJid": "c@g.us"}
        for cb in deferred:
            cb()
    finally:
        wx_module.CallAfter = real_call_after

    assert panel.conversation == {"remoteJid": "c@g.us"}
    assert panel.refresh_calls == 0
