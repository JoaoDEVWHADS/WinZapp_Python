"""Tests for ConversationsPanel.on_incoming_message() not reusing a stale
unread separator.

Reported live: once the user had read past the unread separator (focus
already passed it, mark-as-read fired), a subsequent new message in the same
open conversation just bumped that SAME separator's count instead of
replacing it — so the separator kept sitting above messages the user had
already read, with a count that kept accumulating (e.g. showing "3 unread"
after the user had genuinely only left 1 message unread). The fix flips
``_sep_from_open`` to True the moment the separator is marked read
(_on_message_focused()), so the next live message takes the
"replace-with-a-fresh-separator-reset-to-1" branch instead of the
"just-increment" branch — same as the already-correct behaviour for a
separator placed at conversation-open time.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so on_incoming_message() is exercised against a small stub carrying
fake list-widget methods — same approach as tests/test_message_bookmarks.py.
"""

from ui.conversations import ConversationsPanel


class _FakeMessagesList:
    def __init__(self):
        self.items = []  # list of rendered strings, index-aligned with _sorted_messages

    def Freeze(self):
        pass

    def Thaw(self):
        pass

    def InsertItem(self, pos, text):
        self.items.insert(pos, text)

    def DeleteItem(self, pos):
        del self.items[pos]

    def Append(self, row):
        self.items.append(row[0])

    def SetItemText(self, pos, text):
        self.items[pos] = text


class _FakeMainWindow:
    def _allow_ui_focus_changes(self):
        return False


def _msg(mid):
    return {"key": {"id": mid, "fromMe": False}, "messageType": "conversation",
            "message": {"conversation": "hi"}}


class _Stub:
    on_incoming_message = ConversationsPanel.on_incoming_message
    _is_separator = ConversationsPanel._is_separator

    def __init__(self):
        self.main_window = _FakeMainWindow()
        self.messages_list = _FakeMessagesList()
        self._sorted_messages = []
        self._unread_sep_idx = -1
        self._sep_from_open = False
        self._unread_sep_marked_read = False
        self.conversation = {"remoteJid": "5511999999999@s.whatsapp.net"}
        self._current_audio_id = None
        self._reaction_map = {}
        self._render_separator = lambda count: f"__sep__{count}"
        self._render_message_line = lambda msg, *a, **kw: msg["key"]["id"]


def _sep(stub):
    assert stub._unread_sep_idx >= 0
    return stub._sorted_messages[stub._unread_sep_idx]


class TestSeparatorNotReusedAfterBeingRead:
    def test_a_fresh_separator_still_just_increments_normally(self):
        """Baseline: no read has happened yet — a second live message should
        still accumulate onto the same live separator, as before."""
        stub = _Stub()
        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m1"))
        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m2"))

        assert _sep(stub)["count"] == 2

    def test_separator_is_replaced_once_the_user_has_read_past_it(self):
        """User reads past the separator (simulated: mark-as-read fired, the
        flags _on_message_focused() sets). A new message arrives — it must
        get its OWN fresh separator (count=1), not bump the old one to 2."""
        stub = _Stub()
        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m1"))
        assert _sep(stub)["count"] == 1

        # Simulate _on_message_focused() having marked the separator read.
        stub._unread_sep_marked_read = True
        stub._sep_from_open = True

        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m2"))

        sep = _sep(stub)
        assert sep["count"] == 1, "must reset to 1, not accumulate to 2"
        # The old separator row is gone; only the new one remains in the list.
        assert sum(1 for m in stub._sorted_messages if stub._is_separator(m)) == 1

    def test_marking_read_re_arms_for_the_very_next_message_too(self):
        """The re-arm (_unread_sep_marked_read reset to False) happens inside
        on_incoming_message() itself for EVERY new message, so a second
        message right after the read-past one still increments normally
        (it hasn't been read yet)."""
        stub = _Stub()
        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m1"))
        stub._unread_sep_marked_read = True
        stub._sep_from_open = True
        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m2"))
        assert stub._unread_sep_marked_read is False

        stub.on_incoming_message(stub.conversation["remoteJid"], _msg("m3"))
        assert _sep(stub)["count"] == 2
