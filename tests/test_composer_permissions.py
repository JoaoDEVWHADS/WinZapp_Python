"""Tests for ConversationsPanel._apply_composer_permissions().

Opening a channel, or a group with "only admins can send messages" on while
the user is not an admin, disables the composer's send/record/attach buttons.
The emoji button was left out of that switch: it stayed clickable in a group
the user cannot post in, opening the picker and inserting text into a field
that had just been made read-only.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the method under test is bound to a small stub carrying only the
widgets it touches — same approach as tests/test_conversation_name_update.py.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeButton:
    def __init__(self):
        self.enabled = None

    def Enable(self):
        self.enabled = True

    def Disable(self):
        self.enabled = False


class _FakeTextField(_FakeButton):
    def __init__(self):
        super().__init__()
        self.editable = None

    def SetEditable(self, value):
        self.editable = value


class _FakeMainWindow:
    def __init__(self, restricted=()):
        self._restricted = set(restricted)

    def _is_group_send_restricted(self, chat):
        return chat.get("remoteJid", "") in self._restricted


class _Panel:
    _apply_composer_permissions = ConversationsPanel._apply_composer_permissions

    def __init__(self, restricted=()):
        self.main_window = _FakeMainWindow(restricted)
        self.message_field = _FakeTextField()
        self.send_message_btn = _FakeButton()
        self.record_voice_message_btn = _FakeButton()
        self._add_attachment_btn = _FakeButton()
        self._emoji_btn = _FakeButton()


_GROUP = "123456-group@g.us"


class TestRestrictedGroup:
    def test_emoji_button_is_disabled_with_the_other_send_controls(self):
        panel = _Panel(restricted=[_GROUP])
        panel._apply_composer_permissions(_GROUP, {"remoteJid": _GROUP})
        assert panel._emoji_btn.enabled is False
        assert panel.send_message_btn.enabled is False
        assert panel.record_voice_message_btn.enabled is False
        assert panel._add_attachment_btn.enabled is False

    def test_message_field_stays_focusable_but_read_only(self):
        panel = _Panel(restricted=[_GROUP])
        panel._apply_composer_permissions(_GROUP, {"remoteJid": _GROUP})
        assert panel.message_field.enabled is True
        assert panel.message_field.editable is False


class TestChannel:
    def test_emoji_button_is_disabled(self):
        panel = _Panel()
        jid = "123456@newsletter"
        panel._apply_composer_permissions(jid, {"remoteJid": jid})
        assert panel._emoji_btn.enabled is False
        assert panel.message_field.enabled is False


class TestWritableConversations:
    def test_unrestricted_group_keeps_every_control_enabled(self):
        panel = _Panel()
        panel._apply_composer_permissions(_GROUP, {"remoteJid": _GROUP})
        assert panel._emoji_btn.enabled is True
        assert panel.send_message_btn.enabled is True
        assert panel.message_field.editable is True

    def test_private_chat_keeps_every_control_enabled(self):
        panel = _Panel(restricted=[_GROUP])
        jid = "5511988888888@s.whatsapp.net"
        panel._apply_composer_permissions(jid, {"remoteJid": jid})
        assert panel._emoji_btn.enabled is True
        assert panel.send_message_btn.enabled is True
        assert panel.message_field.editable is True

    def test_reopening_a_writable_chat_reenables_after_a_restricted_one(self):
        # The switch has to re-enable, not just skip disabling: the panel is
        # reused across conversations, so a disabled emoji button would stick.
        panel = _Panel(restricted=[_GROUP])
        panel._apply_composer_permissions(_GROUP, {"remoteJid": _GROUP})
        jid = "5511988888888@s.whatsapp.net"
        panel._apply_composer_permissions(jid, {"remoteJid": jid})
        assert panel._emoji_btn.enabled is True
