"""Tests for MainWindow.navigate_to_conversation_jid()'s panel-visibility fix.

Opening a conversation from a toast click (or the participant-list dialog)
can happen while Status or the Archived list is the panel actually shown.
navigate_to_jid()/navigate_to_conversation() both SetFocus()/Select() controls
inside conversations_panel regardless of whether it's visible, which used to
strand NVDA focus on an invisible control — the same class of bug on_alt_1()
already fixed for its own hotkey. This test pins the panel-prep dance that
now runs before the actual navigation.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so
the method under test is bound onto a plain stub carrying only the attributes
it touches.
"""

from unittest.mock import Mock

from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for navigate_to_conversation_jid()."""

    def __init__(self, **kwargs):
        self._window_hidden = False
        self.restore_window = Mock()
        self.conversations_panel = Mock()
        self.conversations_panel.chats_list = []
        self.archived_conversations_panel = Mock()
        self.archived_conversations_panel.chats_list = []
        self.status_panel = Mock()
        self.content_panel = Mock()
        self.is_chat_archived = Mock(return_value=False)
        for key, value in kwargs.items():
            setattr(self, key, value)

    navigate_to_conversation_jid = MainWindow.navigate_to_conversation_jid


def test_non_archived_jid_shows_conversations_panel():
    stub = _Stub()
    stub.is_chat_archived = Mock(return_value=False)

    stub.navigate_to_conversation_jid("5511999999999@s.whatsapp.net")

    stub.archived_conversations_panel.Hide.assert_called_once()
    stub.status_panel.Hide.assert_called_once()
    stub.conversations_panel.conversations_label.Show.assert_called_once()
    stub.conversations_panel.conversations_list.Show.assert_called_once()
    stub.conversations_panel.Show.assert_called_once()
    stub.content_panel.Layout.assert_called_once()
    stub.conversations_panel.navigate_to_jid.assert_called_once_with(
        "5511999999999@s.whatsapp.net"
    )
    stub.conversations_panel.navigate_to_conversation.assert_not_called()


def test_archived_jid_found_opens_via_archived_panel_dance():
    jid = "5511888888888@s.whatsapp.net"
    chat = {"remoteJid": jid, "name": "Someone"}
    stub = _Stub()
    stub.is_chat_archived = Mock(return_value=True)
    stub.archived_conversations_panel.chats_list = [chat]

    stub.navigate_to_conversation_jid(jid)

    stub.conversations_panel.navigate_to_conversation.assert_called_once_with(chat)
    stub.conversations_panel.conversations_label.Hide.assert_called_once()
    stub.conversations_panel.conversations_list.Hide.assert_called_once()
    stub.archived_conversations_panel.Hide.assert_called_once()
    stub.status_panel.Hide.assert_called_once()
    stub.conversations_panel.navigate_to_jid.assert_not_called()


def test_archived_jid_not_found_falls_back_to_non_archived_path():
    jid = "5511777777777@s.whatsapp.net"
    stub = _Stub()
    stub.is_chat_archived = Mock(return_value=True)
    stub.archived_conversations_panel.chats_list = []  # stale/empty

    stub.navigate_to_conversation_jid(jid)

    stub.conversations_panel.navigate_to_jid.assert_called_once_with(jid)
    stub.conversations_panel.navigate_to_conversation.assert_not_called()


def test_window_hidden_restores_before_anything_else():
    stub = _Stub()
    stub._window_hidden = True
    stub.is_chat_archived = Mock(return_value=False)

    stub.navigate_to_conversation_jid("5511666666666@s.whatsapp.net")

    stub.restore_window.assert_called_once()
    stub.conversations_panel.navigate_to_jid.assert_called_once()
