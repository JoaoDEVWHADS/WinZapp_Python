"""Tests for the Space-toggled selection and the mass actions built on it.

Space on a row in either list toggles that row's membership in a selection set
(self.selected_chats / self.selected_messages) instead of activating it, and
the two context menus grow a "mass actions" submenu whose handlers act on
whatever is in those sets.

What is worth pinning here is that the selection is keyed by identity — chat
JID and message key.id — not by list index. Both lists are rebuilt constantly
(a new message arriving, pagination, a re-sort), so an index-keyed selection
would silently start pointing at different rows between selecting and acting,
and these handlers delete/clear/forward what they are pointed at.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are bound to a small stub carrying only the
attributes they touch — same approach as tests/test_message_bookmarks.py.
"""

import threading

import pytest
import wx

from ui.conversations import ConversationsPanel


class _FakeI18n:
    def t(self, key):
        return key  # the announcement keys are asserted by name


class _FakeSound:
    def __init__(self):
        self.plays = 0

    def play(self):
        self.plays += 1


class _FakeList:
    def __init__(self, focused=-1, count=0):
        self._focused = focused
        self._count = count
        self.focus_calls = []
        self.select_calls = []
        self.ensure_visible_calls = []

    def GetFocusedItem(self):
        return self._focused

    def GetItemCount(self):
        return self._count

    def Focus(self, idx):
        self.focus_calls.append(idx)
        self._focused = idx

    def Select(self, idx, on=True):
        self.select_calls.append((idx, on))

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.settings = {"user_interface": {}}
        self.announced = []
        self.cleared = []
        self.deleted = []
        self.archived = []
        self.marked_read = []
        self.marked_unread = []
        self.deleted_messages = []

    def output(self, text, interrupt=False):
        self.announced.append(text)

    def clear_chat(self, jid):
        self.cleared.append(jid)

    def delete_chat(self, jid):
        self.deleted.append(jid)

    def archive_chat(self, jid, archived):
        self.archived.append((jid, archived))

    def mark_conversation_as_read(self, jid, read):
        self.marked_read.append((jid, read))

    def mark_conversation_as_unread(self, jid):
        self.marked_unread.append(jid)

    def delete_message_for_me(self, jid, key):
        self.deleted_messages.append((jid, key))


class _FakeEvent:
    def __init__(self, key, ctrl=False, shift=False):
        self._key = key
        self._ctrl = ctrl
        self._shift = shift
        self.skipped = False

    def GetKeyCode(self):
        return self._key

    def ControlDown(self):
        return self._ctrl

    def ShiftDown(self):
        return self._shift

    def Skip(self):
        self.skipped = True


class _Panel:
    """Stub carrying exactly what the handlers under test touch."""

    _is_separator = ConversationsPanel._is_separator
    _on_messages_list_key_down = ConversationsPanel._on_messages_list_key_down
    _on_conv_list_key_down = ConversationsPanel._on_conv_list_key_down
    _on_mass_clear_chats = ConversationsPanel._on_mass_clear_chats
    _on_mass_delete_chats = ConversationsPanel._on_mass_delete_chats
    _on_mass_archive_chats = ConversationsPanel._on_mass_archive_chats
    _on_mass_mark_read_chats = ConversationsPanel._on_mass_mark_read_chats
    _on_mass_mark_unread_chats = ConversationsPanel._on_mass_mark_unread_chats
    _on_mass_forward_messages = ConversationsPanel._on_mass_forward_messages
    _on_mass_save_messages = ConversationsPanel._on_mass_save_messages
    _on_mass_delete_messages = ConversationsPanel._on_mass_delete_messages

    def __init__(self, chats=(), messages=(), focused=-1):
        self.main_window = _FakeMainWindow()
        self.selection_sound = _FakeSound()
        self.selected_chats = set()
        self.selected_messages = set()
        self.chats_list = list(chats)
        self._sorted_messages = list(messages)
        self.conversation = {"remoteJid": "grupo@g.us"}
        self.conversations_list = _FakeList(focused=focused, count=len(chats))
        self.messages_list = _FakeList(focused=focused, count=len(messages))
        self._is_loading_more = False
        self._messages_offset = 0
        # Recorders for the collaborators the mass handlers delegate to.
        self.forwarded = []
        self.saved = []
        self.removed_locally = []

    def _on_menu_forward(self, msg, msgs_list=None):
        self.forwarded.append((msg, msgs_list))

    def _on_menu_save(self, msg):
        self.saved.append(msg)

    def remove_messages_by_id(self, ids, focus_previous=False):
        self.removed_locally.append((set(ids), focus_previous))


def _chat(jid):
    return {"remoteJid": jid}


def _msg(msg_id, jid="grupo@g.us"):
    return {"key": {"id": msg_id, "remoteJid": jid}, "message": {"conversation": "x"}}


SEPARATOR = {"_type": "unread_separator", "count": 3}
PLACEHOLDER = {"_type": "empty_placeholder"}


def _space():
    return _FakeEvent(wx.WXK_SPACE)


class TestSpaceInTheConversationsList:
    def test_space_selects_the_focused_chat(self):
        panel = _Panel(chats=[_chat("a@s.whatsapp.net"), _chat("b@s.whatsapp.net")], focused=1)
        panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == {"b@s.whatsapp.net"}
        assert panel.main_window.announced == ["selected"]
        assert panel.selection_sound.plays == 1

    def test_space_again_deselects_it(self):
        panel = _Panel(chats=[_chat("a@s.whatsapp.net")], focused=0)
        panel._on_conv_list_key_down(_space())
        panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == set()
        assert panel.main_window.announced == ["selected", "unselected"]

    def test_deselecting_is_silent(self):
        """The tone marks "now selected"; replaying it on removal would make
        the two states indistinguishable by ear."""
        panel = _Panel(chats=[_chat("a@s.whatsapp.net")], focused=0)
        panel._on_conv_list_key_down(_space())
        panel._on_conv_list_key_down(_space())
        assert panel.selection_sound.plays == 1

    def test_several_chats_accumulate(self):
        chats = [_chat(f"{i}@s.whatsapp.net") for i in range(4)]
        panel = _Panel(chats=chats)
        for i in (0, 2, 3):
            panel.conversations_list._focused = i
            panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == {"0@s.whatsapp.net", "2@s.whatsapp.net", "3@s.whatsapp.net"}

    def test_space_with_nothing_focused_is_a_no_op(self):
        panel = _Panel(chats=[_chat("a@s.whatsapp.net")], focused=-1)
        panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == set()
        assert panel.main_window.announced == []

    def test_a_focus_index_past_the_list_is_a_no_op(self):
        """The list can shrink under a stale focus index (a chat archived or
        deleted while the list was focused)."""
        panel = _Panel(chats=[_chat("a@s.whatsapp.net")], focused=7)
        panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == set()

    def test_a_chat_with_no_jid_is_skipped(self):
        panel = _Panel(chats=[{"name": "sem jid"}], focused=0)
        panel._on_conv_list_key_down(_space())
        assert panel.selected_chats == set()

    def test_the_selection_survives_the_list_being_reordered(self):
        """Keyed by JID, not by row: this is the whole reason it is a set of
        JIDs and not a set of indices."""
        chats = [_chat("a@s.whatsapp.net"), _chat("b@s.whatsapp.net")]
        panel = _Panel(chats=chats, focused=0)
        panel._on_conv_list_key_down(_space())
        panel.chats_list = list(reversed(chats))  # a new message re-sorts the list
        assert panel.selected_chats == {"a@s.whatsapp.net"}


class TestSpaceInTheMessagesList:
    def test_space_selects_the_focused_message(self):
        panel = _Panel(messages=[_msg("m1"), _msg("m2")], focused=1)
        panel._on_messages_list_key_down(_space())
        assert panel.selected_messages == {"m2"}
        assert panel.main_window.announced == ["selected"]
        assert panel.selection_sound.plays == 1

    def test_space_again_deselects_it(self):
        panel = _Panel(messages=[_msg("m1")], focused=0)
        panel._on_messages_list_key_down(_space())
        panel._on_messages_list_key_down(_space())
        assert panel.selected_messages == set()
        assert panel.main_window.announced == ["selected", "unselected"]

    @pytest.mark.parametrize("row", [SEPARATOR, PLACEHOLDER])
    def test_a_sentinel_row_cannot_be_selected(self, row):
        """The unread separator and the "no messages" placeholder have no
        key.id; every other handler guards on _is_separator for the same
        reason."""
        panel = _Panel(messages=[row], focused=0)
        panel._on_messages_list_key_down(_space())
        assert panel.selected_messages == set()
        assert panel.main_window.announced == []

    def test_a_message_with_no_id_is_skipped(self):
        panel = _Panel(messages=[{"key": {}, "message": {}}], focused=0)
        panel._on_messages_list_key_down(_space())
        assert panel.selected_messages == set()

    def test_space_with_nothing_focused_is_a_no_op(self):
        panel = _Panel(messages=[_msg("m1")], focused=-1)
        panel._on_messages_list_key_down(_space())
        assert panel.selected_messages == set()

    def test_shift_space_still_selects(self):
        """Shift+<key> is intercepted first for playback seeking, but only for
        the arrow/Home/End/PageUp/PageDown set. Space is not one of them, so a
        Shift held over from seeking must not swallow the toggle."""
        panel = _Panel(messages=[_msg("m1")], focused=0)
        panel._on_messages_list_key_down(_FakeEvent(wx.WXK_SPACE, shift=True))
        assert panel.selected_messages == {"m1"}

    def test_the_selection_survives_pagination_prepending_older_messages(self):
        panel = _Panel(messages=[_msg("m5"), _msg("m6")], focused=1)
        panel._on_messages_list_key_down(_space())
        panel._sorted_messages = [_msg("m1"), _msg("m2"), _msg("m5"), _msg("m6")]
        assert panel.selected_messages == {"m6"}


@pytest.fixture
def confirm_yes(monkeypatch):
    """Every destructive mass action asks first; answer yes."""
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)


@pytest.fixture
def confirm_no(monkeypatch):
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.NO)


@pytest.fixture
def run_threads_inline(monkeypatch):
    """_on_mass_delete_messages hands the server calls to a background thread;
    run it inline so the test observes the result deterministically."""
    class _Inline:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(threading, "Thread", _Inline)


class TestMassChatActions:
    def test_clearing_applies_to_every_selected_chat(self, confirm_yes):
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net", "b@s.whatsapp.net"}
        panel._on_mass_clear_chats(None)
        assert sorted(panel.main_window.cleared) == ["a@s.whatsapp.net", "b@s.whatsapp.net"]
        assert panel.selected_chats == set()
        assert panel.main_window.announced == ["success_clear"]

    def test_declining_the_confirmation_clears_nothing(self, confirm_no):
        """And leaves the selection intact, so the user does not have to
        rebuild it after an accidental cancel."""
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net"}
        panel._on_mass_clear_chats(None)
        assert panel.main_window.cleared == []
        assert panel.selected_chats == {"a@s.whatsapp.net"}

    def test_deleting_applies_to_every_selected_chat(self, confirm_yes):
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net", "b@s.whatsapp.net"}
        panel._on_mass_delete_chats(None)
        assert sorted(panel.main_window.deleted) == ["a@s.whatsapp.net", "b@s.whatsapp.net"]
        assert panel.selected_chats == set()

    def test_declining_deletes_nothing(self, confirm_no):
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net"}
        panel._on_mass_delete_chats(None)
        assert panel.main_window.deleted == []
        assert panel.selected_chats == {"a@s.whatsapp.net"}

    def test_archiving_does_not_ask_first(self, monkeypatch):
        """Archiving is reversible from the archived panel, unlike clear and
        delete — so it must not be gated on a confirmation that is not there."""
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: pytest.fail("asked"))
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net"}
        panel._on_mass_archive_chats(None)
        assert panel.main_window.archived == [("a@s.whatsapp.net", True)]
        assert panel.main_window.announced == ["success_archive"]

    def test_marking_read_applies_to_every_selected_chat(self):
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net", "b@s.whatsapp.net"}
        panel._on_mass_mark_read_chats(None)
        assert sorted(panel.main_window.marked_read) == [
            ("a@s.whatsapp.net", True), ("b@s.whatsapp.net", True)
        ]
        assert panel.selected_chats == set()

    def test_marking_unread_applies_to_every_selected_chat(self):
        panel = _Panel()
        panel.selected_chats = {"a@s.whatsapp.net", "b@s.whatsapp.net"}
        panel._on_mass_mark_unread_chats(None)
        assert sorted(panel.main_window.marked_unread) == ["a@s.whatsapp.net", "b@s.whatsapp.net"]
        assert panel.selected_chats == set()

    @pytest.mark.parametrize("handler", [
        "_on_mass_clear_chats", "_on_mass_delete_chats", "_on_mass_archive_chats",
        "_on_mass_mark_read_chats", "_on_mass_mark_unread_chats",
    ])
    def test_an_empty_selection_does_nothing_at_all(self, handler, monkeypatch):
        """Not even a confirmation dialog — the submenu is only built while a
        selection exists, but the handlers are reachable after it is cleared."""
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: pytest.fail("asked"))
        panel = _Panel()
        getattr(panel, handler)(None)
        assert panel.main_window.cleared == []
        assert panel.main_window.deleted == []
        assert panel.main_window.archived == []
        assert panel.main_window.announced == []


class TestMassMessageActions:
    def test_forwarding_passes_every_selected_message(self):
        msgs = [_msg("m1"), _msg("m2"), _msg("m3")]
        panel = _Panel(messages=msgs)
        panel.selected_messages = {"m1", "m3"}
        panel._on_mass_forward_messages(None)
        (first, batch), = panel.forwarded
        assert [m["key"]["id"] for m in batch] == ["m1", "m3"]
        assert first is batch[0]
        assert panel.selected_messages == set()

    def test_forwarding_keeps_the_list_order_not_the_set_order(self):
        """The batch is built by walking _sorted_messages, so the recipient
        receives them oldest-first however the set happens to iterate."""
        msgs = [_msg(f"m{i}") for i in range(6)]
        panel = _Panel(messages=msgs)
        panel.selected_messages = {"m4", "m0", "m2"}
        panel._on_mass_forward_messages(None)
        (_first, batch), = panel.forwarded
        assert [m["key"]["id"] for m in batch] == ["m0", "m2", "m4"]

    def test_forwarding_skips_sentinel_rows(self):
        panel = _Panel(messages=[SEPARATOR, _msg("m1")])
        panel.selected_messages = {"m1"}
        panel._on_mass_forward_messages(None)
        (_first, batch), = panel.forwarded
        assert [m["key"]["id"] for m in batch] == ["m1"]

    def test_a_selection_of_messages_no_longer_in_the_list_forwards_nothing(self):
        """They were paginated away or deleted between selecting and acting."""
        panel = _Panel(messages=[_msg("m9")])
        panel.selected_messages = {"gone"}
        panel._on_mass_forward_messages(None)
        assert panel.forwarded == []
        assert panel.selected_messages == set()

    def test_saving_asks_for_each_selected_message(self):
        msgs = [_msg("m1"), _msg("m2")]
        panel = _Panel(messages=msgs)
        panel.selected_messages = {"m1", "m2"}
        panel._on_mass_save_messages(None)
        assert sorted(m["key"]["id"] for m in panel.saved) == ["m1", "m2"]
        assert panel.selected_messages == set()

    def test_deleting_messages_removes_them_locally_and_on_the_server(
        self, confirm_yes, run_threads_inline
    ):
        msgs = [_msg("m1"), _msg("m2"), _msg("m3")]
        panel = _Panel(messages=msgs)
        panel.selected_messages = {"m1", "m3"}
        panel._on_mass_delete_messages(None)
        assert sorted(k["id"] for _jid, k in panel.main_window.deleted_messages) == ["m1", "m3"]
        (removed, focus_previous), = panel.removed_locally
        assert removed == {"m1", "m3"}
        assert focus_previous is True
        assert panel.selected_messages == set()
        assert panel.main_window.announced == ["success_delete"]

    def test_the_server_call_uses_each_message_own_chat(self, confirm_yes, run_threads_inline):
        panel = _Panel(messages=[_msg("m1", jid="outro@g.us")])
        panel.selected_messages = {"m1"}
        panel._on_mass_delete_messages(None)
        assert panel.main_window.deleted_messages[0][0] == "outro@g.us"

    def test_declining_deletes_nothing(self, confirm_no, run_threads_inline):
        panel = _Panel(messages=[_msg("m1")])
        panel.selected_messages = {"m1"}
        panel._on_mass_delete_messages(None)
        assert panel.main_window.deleted_messages == []
        assert panel.removed_locally == []
        assert panel.selected_messages == {"m1"}

    @pytest.mark.parametrize("handler", [
        "_on_mass_forward_messages", "_on_mass_save_messages", "_on_mass_delete_messages",
    ])
    def test_an_empty_selection_does_nothing_at_all(self, handler, monkeypatch):
        monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: pytest.fail("asked"))
        panel = _Panel(messages=[_msg("m1")])
        getattr(panel, handler)(None)
        assert panel.forwarded == []
        assert panel.saved == []
        assert panel.removed_locally == []
