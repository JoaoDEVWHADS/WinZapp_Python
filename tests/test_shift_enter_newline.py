"""Tests for Shift+Enter inserting a newline in the message composer
instead of sending (issue #16).

message_field is TE_MULTILINE | TE_PROCESS_ENTER, so plain Enter fires
EVT_TEXT_ENTER (send) rather than inserting a newline, and wx's native
multiline control only special-cases Ctrl+Enter for a literal newline — no
Shift+Enter equivalent existed before this fix.

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App, so the method under test is bound onto a plain stub carrying a real
wx.TextCtrl (needed for GetInsertionPoint()/ChangeValue() to behave
correctly) — same approach as tests/test_conversation_video_playback.py.
"""

import wx

from ui.conversations import ConversationsPanel


class _FakeKeyEvent:
    def __init__(self, key_code, shift_down=False):
        self._key_code = key_code
        self._shift_down = shift_down
        self.skipped = False

    def GetKeyCode(self):
        return self._key_code

    def ShiftDown(self):
        return self._shift_down

    def Skip(self):
        self.skipped = True


class _FakeMentionPanel:
    def IsShown(self):
        return False


class _Stub:
    _on_message_field_key_down = ConversationsPanel._on_message_field_key_down
    on_change_message_field = ConversationsPanel.on_change_message_field

    def __init__(self, frame):
        self.message_field = wx.TextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self._mention_panel = _FakeMentionPanel()
        self._is_recording = False
        self._attachment_panel = _FakeMentionPanel()  # IsShown() -> False is enough
        self.conversation = None
        self.send_message_btn = wx.Panel(frame)
        self.record_voice_message_btn = wx.Panel(frame)
        self._on_text_changed_mention_check_calls = 0

    def _on_text_changed_mention_check(self):
        self._on_text_changed_mention_check_calls += 1


class TestShiftEnterInsertsNewline:
    def test_shift_enter_inserts_newline_at_cursor(self, wx_app):
        frame = wx.Frame(None)
        try:
            stub = _Stub(frame)
            stub.message_field.SetValue("hello world")
            stub.message_field.SetInsertionPoint(5)  # after "hello"

            event = _FakeKeyEvent(wx.WXK_RETURN, shift_down=True)
            stub._on_message_field_key_down(event)

            assert stub.message_field.GetValue() == "hello\n world"
            assert stub.message_field.GetInsertionPoint() == 6
            assert not event.skipped
            assert stub._on_text_changed_mention_check_calls == 1
        finally:
            frame.Destroy()

    def test_plain_enter_is_left_alone_to_send(self, wx_app):
        """Plain Enter must not be consumed here — EVT_TEXT_ENTER (send)
        depends on the event propagating normally."""
        frame = wx.Frame(None)
        try:
            stub = _Stub(frame)
            stub.message_field.SetValue("hello")

            event = _FakeKeyEvent(wx.WXK_RETURN, shift_down=False)
            stub._on_message_field_key_down(event)

            assert stub.message_field.GetValue() == "hello"
            assert event.skipped
        finally:
            frame.Destroy()

    def test_shift_enter_also_works_with_numpad_enter(self, wx_app):
        frame = wx.Frame(None)
        try:
            stub = _Stub(frame)
            stub.message_field.SetValue("ab")
            stub.message_field.SetInsertionPoint(1)

            event = _FakeKeyEvent(wx.WXK_NUMPAD_ENTER, shift_down=True)
            stub._on_message_field_key_down(event)

            assert stub.message_field.GetValue() == "a\nb"
            assert not event.skipped
        finally:
            frame.Destroy()
