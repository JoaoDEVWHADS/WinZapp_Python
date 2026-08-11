"""Regression coverage for the message field's visibility while recording a
voice message. Reported live: starting a recording hid the record/send/
attach buttons and showed the voice-recording panel (discard/pause/send),
but left the plain text message_field visible and overlapping it — it
should hide along with those buttons and come back once the recording is
sent or discarded, exactly like the other controls _hide_voice_panel()
already restores.

ConversationsPanel is a wx.Panel and can't be instantiated without a
running wx.App, so _hide_voice_panel() is bound onto a plain stub carrying
only the widgets it touches, matching the pattern used throughout this
test suite (see test_sender_names.py).
"""

from ui.conversations import ConversationsPanel


class _FakeWidget:
    def __init__(self):
        self.shown = False

    def Show(self, show=True):
        self.shown = bool(show)

    def Hide(self):
        self.shown = False


class _FakeTextCtrl(_FakeWidget):
    def __init__(self, value=""):
        super().__init__()
        self._value = value

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = value


class _Stub:
    _hide_voice_panel = ConversationsPanel._hide_voice_panel

    def __init__(self, message_field_value=""):
        self._voice_panel           = _FakeWidget()
        self.message_field          = _FakeTextCtrl(message_field_value)
        self.send_message_btn       = _FakeWidget()
        self.record_voice_message_btn = _FakeWidget()
        self._add_attachment_btn    = _FakeWidget()
        self.conversation_panel     = _FakeWidget()
        self.conversation_panel.Layout = lambda: None


class TestHideVoicePanelRestoresMessageField:
    def test_message_field_is_shown_again(self):
        stub = _Stub()
        stub.message_field.Hide()

        stub._hide_voice_panel()

        assert stub.message_field.shown is True

    def test_voice_panel_itself_is_hidden(self):
        stub = _Stub()
        stub._voice_panel.Show()

        stub._hide_voice_panel()

        assert stub._voice_panel.shown is False

    def test_shows_send_button_when_field_has_leftover_text(self):
        stub = _Stub(message_field_value="oi")

        stub._hide_voice_panel()

        assert stub.send_message_btn.shown is True
        assert stub.record_voice_message_btn.shown is False

    def test_shows_record_button_when_field_is_empty(self):
        stub = _Stub(message_field_value="")

        stub._hide_voice_panel()

        assert stub.record_voice_message_btn.shown is True
        assert stub.send_message_btn.shown is False
