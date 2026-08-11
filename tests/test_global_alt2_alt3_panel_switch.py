"""Regression coverage for Alt+2/Alt+3 not bringing conversations_panel to
the front when invoked from some other top-level panel (Status, archived,
...).

Reported live: with a conversation open in the background,
switching to the Status tab and pressing Alt+2/Alt+3 jumped focus inside
the still-hidden conversations_panel — nothing visibly happened, since the
handlers only ever acted on the panel without ever showing it.
_ensure_conversations_panel_visible() (called from both handlers before
the actual jump) is what's being verified here.

MainWindow is a wx.Frame and can't be instantiated without a running
wx.App, so the methods under test are bound onto a plain stub carrying
only the attributes they touch, matching the pattern used throughout this
test suite (see test_sender_names.py).
"""

from main import MainWindow


class _FakeWidget:
    def __init__(self, shown=False):
        self._shown = shown

    def Show(self, show=True):
        self._shown = bool(show)

    def Hide(self):
        self._shown = False

    def IsShown(self):
        return self._shown

    def Layout(self):
        pass


class _FakeConversationsPanel(_FakeWidget):
    def __init__(self, conversation=None, shown=False):
        super().__init__(shown=shown)
        self.conversation = conversation
        self.jump_last_calls   = 0
        self.jump_unread_calls = 0

    def _on_accel_jump_last(self, event):
        self.jump_last_calls += 1

    def _on_accel_jump_unread(self, event):
        self.jump_unread_calls += 1


class _Stub:
    _ensure_conversations_panel_visible = MainWindow._ensure_conversations_panel_visible
    _on_global_alt2 = MainWindow._on_global_alt2
    _on_global_alt3 = MainWindow._on_global_alt3

    def __init__(self, conversation=None, conversations_panel_shown=False):
        self.conversations_panel = _FakeConversationsPanel(
            conversation=conversation, shown=conversations_panel_shown
        )
        self.archived_conversations_panel = _FakeWidget(shown=False)
        self.status_panel = _FakeWidget(shown=True)
        self.content_panel = _FakeWidget()


class TestAlt2BringsConversationsPanelToFront:
    def test_shows_conversations_panel_and_hides_status_panel(self):
        stub = _Stub(conversation={"remoteJid": "j@s.whatsapp.net"}, conversations_panel_shown=False)
        stub.status_panel.Show()

        stub._on_global_alt2(None)

        assert stub.conversations_panel.IsShown() is True
        assert stub.status_panel.IsShown() is False
        assert stub.conversations_panel.jump_last_calls == 1

    def test_no_op_when_no_conversation_is_open(self):
        stub = _Stub(conversation=None, conversations_panel_shown=False)
        stub.status_panel.Show()

        stub._on_global_alt2(None)

        assert stub.conversations_panel.IsShown() is False
        assert stub.conversations_panel.jump_last_calls == 0

    def test_does_nothing_extra_when_already_visible(self):
        stub = _Stub(conversation={"remoteJid": "j@s.whatsapp.net"}, conversations_panel_shown=True)

        stub._on_global_alt2(None)

        assert stub.conversations_panel.IsShown() is True
        assert stub.conversations_panel.jump_last_calls == 1


class TestAlt3BringsConversationsPanelToFront:
    def test_shows_conversations_panel_and_hides_archived_panel(self):
        stub = _Stub(conversation={"remoteJid": "j@s.whatsapp.net"}, conversations_panel_shown=False)
        stub.archived_conversations_panel.Show()
        stub.status_panel.Hide()

        stub._on_global_alt3(None)

        assert stub.conversations_panel.IsShown() is True
        assert stub.archived_conversations_panel.IsShown() is False
        assert stub.conversations_panel.jump_unread_calls == 1
