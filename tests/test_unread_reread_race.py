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
    _remote_read_confirmed = staticmethod(MainWindow._remote_read_confirmed)
    # Bridges the @lid / phone identities of the incoming event before the
    # handler looks the chat up — see tests/test_chats_update_lid_resolution.py.
    _resolve_chat_for_event = MainWindow._resolve_chat_for_event

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

class _CP:
    """Conversation panel stub.

    The open-conversation check moved from `_last_open_jid` to the panel's live
    `conversation` dict: the old field was never cleared on close, so a chat the
    user had already left kept counting as open forever and every chats-update
    for it was force-zeroed.
    """

    def __init__(self, jid=None):
        self.conversation = {"remoteJid": jid} if jid else None


class TestCurrentlyOpenConversation:
    def test_an_open_conversation_with_nothing_new_clears_to_zero(self):
        stub = _Stub(_chat(t=1000))
        stub.conversations_panel = _CP(JID)

        stub.on_chat_unread_update(JID, 5)

        assert stub.chats[JID]["unreadCount"] == 0

    def test_an_open_conversation_keeps_what_arrived_while_hidden(self):
        """Deliberately not "open always means zero" any more: messages that
        landed while the window was minimized are tracked in _new_since_read
        and stay counted, clamped down to that locally-known number."""
        stub = _Stub(_chat(t=1000))
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 2

        stub.on_chat_unread_update(JID, 5)

        assert stub.chats[JID]["unreadCount"] == 2

    def test_a_closed_panel_is_not_treated_as_the_open_chat(self):
        """The regression the move away from _last_open_jid fixed."""
        stub = _Stub(_chat(t=2000))
        stub.conversations_panel = _CP(None)
        stub._locally_read_at[JID] = 1000
        stub._new_since_read[JID] = 3

        stub.on_chat_unread_update(JID, 3)

        assert stub.chats[JID]["unreadCount"] == 3


class TestOpenConversationSurvivesSpuriousServerZeros:
    """Reported live: closing with Alt+F4 (which only hides to tray) and
    leaving the app minimized made every notification announce "✉️ 1 mensagem
    não lida" no matter how many had piled up — while reopening the window
    showed the conversation really did hold several.

    A conversation left open stays open with the window gone, so this is the
    _open_now branch, and WA-JS keeps firing chat.unread_count_changed with
    unreadCount=0 for 1:1 chats. Clamping with a plain min() against those
    zeros reset the count after every message, so the next arrival counted up
    from zero again and its toast always read "1".
    """

    def test_a_server_zero_does_not_wipe_what_arrived_while_hidden(self):
        chat = _chat(t=1000)
        # on_new_message() moves both of these together, once per arrival —
        # a chat at 0 with a nonzero _new_since_read is not a reachable state.
        chat["unreadCount"] = 4
        stub = _Stub(chat)
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 4

        stub.on_chat_unread_update(JID, 0)

        assert stub.chats[JID]["unreadCount"] == 4

    def test_the_count_keeps_climbing_across_a_burst(self):
        """The symptom itself: five messages with a spurious zero after each
        must leave five unread, not one. Mirrors what on_new_message() does
        (increment both the chat and _new_since_read) between the events."""
        stub = _Stub(_chat(t=1000))
        stub.conversations_panel = _CP(JID)
        seen_by_toasts = []

        for _ in range(5):
            chat = stub.chats[JID]
            chat["unreadCount"] = int(chat.get("unreadCount") or 0) + 1
            stub._new_since_read[JID] = stub._new_since_read.get(JID, 0) + 1
            # What the toast reads (NotificationManager._dispatch samples the
            # live chat right before showing the banner).
            seen_by_toasts.append(chat["unreadCount"])
            stub.on_chat_unread_update(JID, 0)

        assert seen_by_toasts == [1, 2, 3, 4, 5]
        assert stub.chats[JID]["unreadCount"] == 5

    def test_a_real_server_count_is_still_clamped_down(self):
        """The spurious-zero rescue must not become a licence to trust the
        server's absolute total, which can still be counting messages already
        read locally — that is the bug this whole function exists to prevent."""
        stub = _Stub(_chat(t=1000))
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 2

        stub.on_chat_unread_update(JID, 7)

        assert stub.chats[JID]["unreadCount"] == 2

    def test_a_read_on_the_phone_does_clear_the_open_chat(self):
        """The other side of the same coin: a zero that really fell from a
        positive count is somebody reading the chat elsewhere, and must clear
        the badge — including the messages counted while hidden, which is
        exactly what the user just read on their phone."""
        chat = _chat(t=1000)
        chat["unreadCount"] = 4
        stub = _Stub(chat)
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 4

        stub.on_chat_unread_update(JID, 0, previous_unread=4)

        assert stub.chats[JID]["unreadCount"] == 0
        # ...and the local counter goes with it, or the next arrival would be
        # clamped against a backlog that no longer exists.
        assert JID not in stub._new_since_read

    def test_a_read_on_the_phone_clears_a_chat_that_is_not_open(self):
        """Same for the closed-chat guard: it exists to reject uninformative
        zeros, not real reads. This used to leave the badge lit until some
        later full sync happened to correct it."""
        chat = _chat(t=1000)
        chat["unreadCount"] = 3
        stub = _Stub(chat)

        stub.on_chat_unread_update(JID, 0, previous_unread=3)

        assert stub.chats[JID]["unreadCount"] == 0

    def test_an_unknown_previous_count_stays_conservative(self):
        """The page could not tell us (None). Keeping the badge risks a stale
        badge until the next sync; dropping it risks silently losing unread
        messages — so the safe reading is 'not confirmed'."""
        chat = _chat(t=1000)
        chat["unreadCount"] = 4
        stub = _Stub(chat)
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 4

        stub.on_chat_unread_update(JID, 0, previous_unread=None)

        assert stub.chats[JID]["unreadCount"] == 4

    def test_a_previous_of_zero_is_the_store_load_not_a_read(self):
        """previousUnreadCount=0 means the count never fell: nothing was read,
        the chat was just loaded into WhatsApp Web's Store."""
        chat = _chat(t=1000)
        chat["unreadCount"] = 2
        stub = _Stub(chat)
        stub.conversations_panel = _CP(JID)
        stub._new_since_read[JID] = 2

        stub.on_chat_unread_update(JID, 0, previous_unread=0)

        assert stub.chats[JID]["unreadCount"] == 2

    def test_an_open_chat_with_no_local_arrivals_still_clears(self):
        """A zero with nothing counted locally means what it says: the open
        conversation is read. The badge here came from a sync, not from
        arrivals this session, so there is nothing local to defend."""
        chat = _chat(t=1000)
        chat["unreadCount"] = 3
        stub = _Stub(chat)
        stub.conversations_panel = _CP(JID)

        stub.on_chat_unread_update(JID, 0)

        assert stub.chats[JID]["unreadCount"] == 0
