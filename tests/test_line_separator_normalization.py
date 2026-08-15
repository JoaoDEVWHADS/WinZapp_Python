"""Tests for Unicode line/paragraph separator normalization.

The "artificial line breaks" report: pasting text from rich sources — Google
Docs, Word, websites, Apple apps — copies U+2028 LINE SEPARATOR / U+2029
PARAGRAPH SEPARATOR into the clipboard where a plain editor stores \n. The
native wx TextCtrl keeps them verbatim: it neither renders them as breaks
(a paste looks like a single long line) nor counts them in
GetNumberOfLines(), yet WhatsApp renders U+2029 as a paragraph break for the
recipient. So the same text looks fine (or collapses to one line) in the
field and arrives on the other side full of weird breaks.

The fix normalizes these to plain \n in two places: when pasting into the
message field (_on_message_field_paste) and again at send time
(on_send_message) as a safety net for text that reaches the field by any
other route. normalize_line_separators() in core/utils.py does the actual
mapping; the paste handler is exercised with a real wx.TextCtrl (WriteText
is what inserts the normalized text), same approach as
tests/test_shift_enter_newline.py.
"""

import pytest
import wx

from core.utils import normalize_line_separators
from ui.conversations import ConversationsPanel


class TestNormalizeLineSeparators:
    @pytest.mark.parametrize("sep", ["\u2028", "\u2029", "\u0085", "\x0b", "\x0c"])
    def test_every_unicode_separator_becomes_a_newline(self, sep):
        assert normalize_line_separators(f"A{sep}B") == "A\nB"

    def test_paragraph_separator_map_is_the_reported_bug(self):
        # The actual reproduction from the report: a multi-paragraph paste.
        text = "Primeiro par\u00e1grafo.\u2029Segundo par\u00e1grafo."
        assert normalize_line_separators(text) == (
            "Primeiro par\u00e1grafo.\nSegundo par\u00e1grafo."
        )

    def test_plain_newlines_are_left_alone(self):
        assert normalize_line_separators("a\nb\nc") == "a\nb\nc"

    def test_crlf_and_lone_cr_are_normalized(self):
        assert normalize_line_separators("a\r\nb") == "a\nb"
        assert normalize_line_separators("a\rb") == "a\nb"

    def test_mixed_separators_collapse_to_newlines(self):
        assert normalize_line_separators("a\u2028b\r\nc\u2029d") == "a\nb\nc\nd"

    def test_empty_and_none_are_safe(self):
        assert normalize_line_separators("") == ""
        assert normalize_line_separators(None) == ""

    def test_normal_text_is_unchanged(self):
        text = "Ol\u00e1, como vai? Tudo bem."
        assert normalize_line_separators(text) == text


class TestSendPathCallsNormalization:
    def test_on_send_message_normalizes_before_sending(self):
        """The paste handler fixes the common entry point, but text can also
        reach the field by other routes (drag-and-drop, scripts). The send
        path is the final gate and must normalize whatever it reads. Checked
        at source level because driving on_send_message whole needs a live
        wx.App and a WhatsApp session."""
        import inspect

        src = inspect.getsource(ConversationsPanel.on_send_message)
        assert "normalize_line_separators(self.message_field.GetValue())" in src, (
            "on_send_message reads the field without normalizing Unicode "
            "line/paragraph separators first"
        )


class _FakeKeyEvent:
    def __init__(self):
        self.skipped = False

    def Skip(self):
        self.skipped = True


class _FakeMentionPanel:
    def IsShown(self):
        return False


class _Stub:
    _on_message_field_paste = ConversationsPanel._on_message_field_paste

    def __init__(self, frame):
        self.message_field = wx.TextCtrl(
            frame, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER | wx.TE_DONTWRAP
        )


class TestPasteNormalization:
    def test_paste_of_paragraph_separator_text_is_normalized(self, wx_app):
        frame = wx.Frame(None)
        try:
            stub = _Stub(frame)
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject("A\u2029B\u2029C"))
                wx.TheClipboard.Close()
            else:
                pytest.skip("clipboard unavailable")

            stub._on_message_field_paste(_FakeKeyEvent())

            assert stub.message_field.GetValue() == "A\nB\nC"
            assert stub.message_field.GetNumberOfLines() == 3
        finally:
            frame.Destroy()

    def test_paste_of_plain_text_is_left_alone(self, wx_app):
        frame = wx.Frame(None)
        try:
            stub = _Stub(frame)
            if wx.TheClipboard.Open():
                wx.TheClipboard.SetData(wx.TextDataObject("hello\nworld"))
                wx.TheClipboard.Close()
            else:
                pytest.skip("clipboard unavailable")

            event = _FakeKeyEvent()
            stub._on_message_field_paste(event)

            # Plain text is delegated to the native paste (Skip), which the
            # handler must not itself touch — the assertion is the delegation
            # itself, since no real paste event is being processed here.
            assert event.skipped
            assert stub.message_field.GetValue() == ""
        finally:
            frame.Destroy()
