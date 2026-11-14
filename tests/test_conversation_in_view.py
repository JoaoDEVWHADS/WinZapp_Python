"""An open conversation behind another panel is not being read."""
from core.conversation_view import conversation_in_view
from main_window.shortcuts import ShortcutsMixin


class _Panel:
    def __init__(self, conversation, shown=True):
        self.conversation = conversation
        self._shown = shown

    def IsShown(self):
        return self._shown


def test_shown_panel_with_open_conversation_is_in_view():
    assert conversation_in_view(_Panel({"remoteJid": "1@s.whatsapp.net"}))


def test_panel_hidden_by_a_panel_switch_is_not_in_view():
    # Alt+4 Hide()s conversations_panel but leaves its conversation open.
    assert not conversation_in_view(_Panel({"remoteJid": "1@s.whatsapp.net"}, shown=False))


def test_no_conversation_or_no_panel_is_not_in_view():
    assert not conversation_in_view(_Panel(None))
    assert not conversation_in_view(None)


def test_stand_in_without_is_shown_keeps_old_behaviour():
    class Bare:
        conversation = {"remoteJid": "1@s.whatsapp.net"}
    assert conversation_in_view(Bare())


def test_destroyed_panel_is_not_in_view():
    class Dead(_Panel):
        def IsShown(self):
            raise RuntimeError("wrapped C/C++ object has been deleted")
    assert not conversation_in_view(Dead({"remoteJid": "1@s.whatsapp.net"}))


class _Stub:
    def __init__(self, conversation):
        self.calls = []
        self.conversations_panel = self
        self.conversation = conversation

    def _ensure_conversations_panel_visible(self):
        self.calls.append("show")

    def _on_accel_focus_list(self, event):
        self.calls.append("focus")


def test_alt_m_from_the_archived_panel_shows_the_conversation_and_focuses_messages():
    stub = _Stub({"remoteJid": "1@s.whatsapp.net"})
    ShortcutsMixin._on_global_focus_messages(stub, None)
    assert stub.calls == ["show", "focus"]


def test_alt_m_without_an_open_conversation_only_asks_the_panel_to_announce():
    stub = _Stub(None)
    ShortcutsMixin._on_global_focus_messages(stub, None)
    assert stub.calls == ["focus"]


def test_archived_chat_is_silent_unless_current_or_archived_list_visible():
    from core.conversation_view import archived_chat_stays_silent
    assert archived_chat_stays_silent(False, False)      # status/main panel
    assert not archived_chat_stays_silent(False, True)   # archived list shown
    assert not archived_chat_stays_silent(True, False)   # open and in view


def test_archived_panel_is_shown_reads_the_panel_flag():
    from core.conversation_view import archived_panel_is_shown

    class _MW:
        archived_conversations_panel = _Panel(None, shown=True)
    assert archived_panel_is_shown(_MW())
    _MW.archived_conversations_panel = _Panel(None, shown=False)
    assert not archived_panel_is_shown(_MW())
    assert not archived_panel_is_shown(object())


def test_conversation_with_its_detail_pane_hidden_is_not_in_view():
    # Another panel is showing: ConversationsPanel is shown but hides just the
    # detail pane of a conversation that belongs elsewhere.
    panel = _Panel({"remoteJid": "1@s.whatsapp.net"})
    panel.conversation_panel = _Panel(None, shown=False)
    assert not conversation_in_view(panel)
    panel.conversation_panel = _Panel(None, shown=True)
    assert conversation_in_view(panel)
