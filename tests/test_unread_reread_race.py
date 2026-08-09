"""Tests for MainWindow.on_chat_unread_update() not resurrecting already-read
messages as unread.

Reported live: after reading some messages in a conversation, a single new
incoming message could push the unread badge to 3 or 4 instead of 1. Root
cause: WPPConnect's chats.update event reports an ABSOLUTE unread total, and
on_chat_unread_update() unconditionally overwrote the local unreadCount with
it. The one existing guard (_locally_read_at) only protects against a
chats.update whose chat["t"] is not newer than the local read-ack — once a
genuinely new message arrives after the read-ack, that guard is bypassed
entirely and the server's (possibly stale, still counting messages we already
read locally) total was accepted as-is.

The fix tracks _new_since_read[jid] — incremented once per real local
increment in on_new_message() — and clamps the server-reported count to that
local counter whenever the timestamp guard is bypassed, instead of trusting
the raw server value.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so on_chat_unread_update() is exercised as a plain function against a small
stub — same approach as tests/test_failed_send_preview.py.
"""

from main import MainWindow


class _Stub:
    on_chat_unread_update = MainWindow.on_chat_unread_update
    _normalize_jid = staticmethod(MainWindow._normalize_jid)

    def __init__(self, chat):
        self.chats = {"5511999999999@s.whatsapp.net": chat}
        self._initial_sync_running = False
        self._sync_completed = True
        self.conversations_panel = None
        self._locally_read_at = {}
        self._new_since_read = {}
        self.saved = []
        self.set_chats_calls = 0

    def _schedule_save(self, dirty_jid=None):
        self.saved.append(dirty_jid)

    def _schedule_set_chats(self):
        self.set_chats_calls += 1


JID = "5511999999999@s.whatsapp.net"


def _chat(t=1000):
    return {"unreadCount": 0, "t": t, "messages": {"messages": {"records": []}}}


class TestStaleServerCountAfterLocalRead:
    def test_one_new_message_does_not_resurrect_previously_read_ones(self):
        """User read the chat (unreadCount=0, read-ack at t=1000). One new
        message arrives; on_new_message() would have already bumped the
        local count to 1 and recorded it in _new_since_read. The server's
        chats.update for the same event still (staleness) reports 4 — it
        must be clamped down to the locally known 1, not accepted as-is."""
        stub = _Stub(_chat(t=2000))
        stub._locally_read_at[JID] = 1000
        stub._new_since_read[JID] = 1  # on_new_message() already counted this

        stub.on_chat_unread_update(JID, 4)

        assert stub.chats[JID]["unreadCount"] == 1

    def test_server_count_at_or_below_local_is_trusted_unchanged(self):
        stub = _Stub(_chat(t=2000))
        stub._locally_read_at[JID] = 1000
        stub._new_since_read[JID] = 3

        stub.on_chat_unread_update(JID, 2)

        assert stub.chats[JID]["unreadCount"] == 2

    def test_update_not_newer_than_the_read_ack_still_clears_to_zero(self):
        """Unrelated / stale chats.update whose own chat t is not after the
        read-ack must still be fully suppressed, same as before this fix."""
        stub = _Stub(_chat(t=1000))
        stub._locally_read_at[JID] = 1000

        stub.on_chat_unread_update(JID, 5)

        assert stub.chats[JID]["unreadCount"] == 0

    def test_no_local_tracking_falls_back_to_trusting_the_server(self):
        """If _new_since_read has no entry (e.g. the increment path wasn't
        hit for some other reason), there's no better local information —
        keep accepting the server's number rather than zeroing it out."""
        chat = _chat(t=2000)
        stub = _Stub(chat)
        stub._locally_read_at[JID] = 1000

        stub.on_chat_unread_update(JID, 3)

        assert stub.chats[JID]["unreadCount"] == 3

    def test_currently_open_conversation_always_clears_to_zero(self):
        class _CP:
            _last_open_jid = JID

        stub = _Stub(_chat(t=1000))
        stub.conversations_panel = _CP()
        stub._new_since_read[JID] = 5

        stub.on_chat_unread_update(JID, 5)

        assert stub.chats[JID]["unreadCount"] == 0
