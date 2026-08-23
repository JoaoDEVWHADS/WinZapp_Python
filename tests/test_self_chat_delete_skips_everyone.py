"""Issue #73: "Delete for everyone" in the self-chat ("Me — messages to
yourself") only ever removed the message locally — WhatsApp's revoke is a
no-op there (there's no one else to delete it for), so the message stayed
on every other linked device and reappeared in WinZapp itself after the
next resync, while the app had told the user it was gone for everyone.

_on_menu_delete_message() now detects the self-chat up front and skips the
whole "delete for me / for everyone" dialog entirely, going straight to a
plain local delete (delete_message_for_me) — matching the reporter's own
suggested fix.

ConversationsPanel is a wx.Panel and can't be instantiated without a
running wx.App. The self-chat path returns before touching anything
wx-specific (no dialog, no wx.Dialog(...) construction), so it's safe to
exercise directly against a plain stub without a wx.App fixture at all —
unlike the non-self-chat path, which is left untested here since it builds
a real modal dialog.
"""

import threading

from ui.conversations import ConversationsPanel


class _FakeMainWindow:
    def __init__(self, is_self_chat):
        self._is_self_chat = is_self_chat
        self.delete_for_me_calls = []
        self.delete_for_everyone_calls = []
        self.i18n = None  # unused on the self-chat path (returns before it's read)

    def _is_self_jid(self, jid):
        return self._is_self_chat

    def delete_message_for_me(self, jid, key):
        self.delete_for_me_calls.append((jid, key))
        return True

    def delete_message_for_everyone(self, jid, key):
        self.delete_for_everyone_calls.append((jid, key))
        return True


class _Stub:
    _on_menu_delete_message     = ConversationsPanel._on_menu_delete_message
    _delete_message_for_me_only = ConversationsPanel._delete_message_for_me_only
    _is_separator                = ConversationsPanel._is_separator
    _is_system_event              = lambda self, msg: False

    def __init__(self, jid, is_self_chat):
        self.main_window = _FakeMainWindow(is_self_chat)
        msg = {"key": {"id": "m1", "fromMe": True, "remoteJid": jid}}
        self._sorted_messages = [msg]
        self.conversation = {"remoteJid": jid}
        self.removed_ids = []

    def remove_messages_by_id(self, ids, focus_previous=False):
        self.removed_ids.append(set(ids))


SELF_JID = "5511999999999@s.whatsapp.net"


def _run_and_join_threads(fn):
    """_delete_message_for_me_only()/the "everyone" path fire a background
    daemon thread — join whatever's alive afterward so assertions don't race
    it."""
    before = set(threading.enumerate())
    fn()
    for t in set(threading.enumerate()) - before:
        t.join(timeout=2)


class TestSelfChatSkipsTheDialog:
    def test_self_chat_deletes_locally_only_without_any_dialog(self):
        stub = _Stub(SELF_JID, is_self_chat=True)

        _run_and_join_threads(lambda: stub._on_menu_delete_message(0))

        assert stub.removed_ids == [{"m1"}]
        assert len(stub.main_window.delete_for_me_calls) == 1
        assert stub.main_window.delete_for_everyone_calls == []
