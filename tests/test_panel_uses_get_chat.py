"""Tests for the panel looking chats up through MainWindow.get_chat().

`self.chats` is keyed by whichever JID variant the chat was stored under —
@lid for accounts WhatsApp moved to LID addressing, the phone JID otherwise.
A plain `chats.get(jid)` therefore misses whenever the caller holds the other
variant, and the panel's callers all treat a miss as "no such chat yet" and
fabricate a fresh one: `{"remoteJid": jid, "pushName": name}`.

The user-visible result of that miss is not an error — it is worse. Opening a
participant's chat from a group ("Conversar com") lands in a blank, nameless
conversation with none of the history that already exists, sitting beside the
real one in the list.

get_chat() exists precisely to fall back to the mapped variant. These tests
bind the real method (not a re-implementation) so they check the lookup the
app actually performs.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test run against a stub — same approach as
tests/test_message_bookmarks.py.
"""

import inspect

import pytest

from main import MainWindow
from ui.conversations import ConversationsPanel


PHONE = "5511900000002@s.whatsapp.net"
LID = "222222222222222@lid"


class _FakeMainWindow:
    get_chat = MainWindow.get_chat        # the real lookup, with its fallback

    def __init__(self, chats=None, lid_to_phone=None, phone_to_lid=None):
        self.chats = dict(chats or {})
        self._lid_to_phone = dict(lid_to_phone or {})
        self._phone_to_lid = dict(phone_to_lid or {})


class _Stub:
    _on_menu_converse_private = ConversationsPanel._on_menu_converse_private

    def __init__(self, main_window):
        self.main_window = main_window
        self.navigated = []

    def navigate_to_conversation(self, chat):
        self.navigated.append(chat)


def _existing_chat(jid):
    return {"remoteJid": jid, "name": "Fulano", "messages": {"messages": {"records": [1, 2, 3]}}}


class TestOpeningAParticipantsChat:
    def test_finds_the_chat_stored_under_the_lid_variant(self):
        """Holding the phone JID, the chat stored under @lid must still be
        found — otherwise a second, empty conversation is opened."""
        mw = _FakeMainWindow(
            chats={LID: _existing_chat(LID)},
            phone_to_lid={PHONE: LID},
        )
        panel = _Stub(mw)

        panel._on_menu_converse_private(PHONE, "Fulano")

        assert panel.navigated == [_existing_chat(LID)]

    def test_finds_the_chat_stored_under_the_phone_variant(self):
        mw = _FakeMainWindow(
            chats={PHONE: _existing_chat(PHONE)},
            lid_to_phone={LID: PHONE},
        )
        panel = _Stub(mw)

        panel._on_menu_converse_private(LID, "Fulano")

        assert panel.navigated == [_existing_chat(PHONE)]

    def test_an_exact_hit_is_used_as_is(self):
        mw = _FakeMainWindow(chats={PHONE: _existing_chat(PHONE)})
        panel = _Stub(mw)

        panel._on_menu_converse_private(PHONE, "Fulano")

        assert panel.navigated == [_existing_chat(PHONE)]

    def test_a_genuinely_unknown_contact_still_gets_a_fresh_chat(self):
        """The fallback exists for real first contacts — it must keep working,
        just not fire for chats that already exist under the other variant."""
        mw = _FakeMainWindow()
        panel = _Stub(mw)

        panel._on_menu_converse_private(PHONE, "Fulano")

        assert panel.navigated == [{"remoteJid": PHONE, "pushName": "Fulano"}]


class TestNoPanelPathStillUsesTheRawDictLookup:
    @pytest.mark.parametrize("method_name", [
        "_on_menu_converse_private",
        "_on_menu_reply_private",
    ])
    def test_participant_chat_lookups_go_through_get_chat(self, method_name):
        src = inspect.getsource(getattr(ConversationsPanel, method_name))
        assert "chats.get(" not in src, (
            f"{method_name} looks the chat up with a raw dict get, which misses "
            f"the @lid/phone variant and opens a duplicate empty conversation"
        )
        assert "get_chat(" in src
