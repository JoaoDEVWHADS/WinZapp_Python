"""Emoticons typed in the message field become emoji, like WhatsApp Web.

core/emoticons.py decides what converts and when, and is tested directly.
The composer side (ui/conversation_panel/emoticon_conversion.py) is a
ConversationsPanel mixin, which needs a wx.App to construct, so its methods
are bound onto a plain stub whose message field is a fake that counts caret
positions the way the native control does — including UTF-16 units, which is
what made the caret arithmetic worth testing at all.
"""

import pytest
import wx

from core.emoticons import (
    EMOTICONS,
    caret_value_index,
    convert_trailing_emoticon,
    emoticon_before_caret,
    emoticon_setting_enabled,
    emoticons_enabled,
    native_newline_width,
)
from core.utils import DEFAULT_SETTINGS
from ui.conversation_panel import emoticon_conversion
from ui.conversations import ConversationsPanel


class TestEmoticonBeforeCaret:
    @pytest.mark.parametrize("token", sorted(EMOTICONS))
    def test_every_token_converts_at_the_start_of_the_text(self, token):
        assert emoticon_before_caret(token) == (token, EMOTICONS[token])

    def test_converts_after_whitespace(self):
        assert emoticon_before_caret("ok :D") == (":D", "😃")
        assert emoticon_before_caret("line one\n:)") == (":)", "🙂")

    def test_the_longest_token_wins(self):
        assert emoticon_before_caret("hi :-)") == (":-)", "🙂")
        assert emoticon_before_caret("hi B-)") == ("B-)", "😎")

    @pytest.mark.parametrize("text", [
        "http:/",            # a URL being typed
        "see https://a.b/:/",
        "word:P",            # part of a longer word
        "10:D",
        "(:)",
        "a:-)",              # the longer token is not standalone, nor is ")"
        "hello",
        "",
    ])
    def test_does_not_convert_what_is_not_a_standalone_token(self, text):
        assert emoticon_before_caret(text) is None

    def test_list_labels_are_never_touched(self):
        # "B)" is deliberately not a token: "A) yes B) no" is a list, not a
        # pair of sunglasses. "B-)" still converts.
        assert "B)" not in EMOTICONS
        assert emoticon_before_caret("A) yes B)") is None
        assert convert_trailing_emoticon("A) yes B)") == "A) yes B)"
        assert emoticon_before_caret("cool B-)") == ("B-)", "😎")

    def test_does_not_convert_inside_code(self):
        assert emoticon_before_caret("`x :D") is None
        assert emoticon_before_caret("```\nprint :)") is None
        # Once the span is closed, conversion is back.
        assert emoticon_before_caret("`x` :D") == (":D", "😃")


class TestConvertTrailingEmoticon:
    def test_a_trailing_emoticon_converts_at_send(self):
        assert convert_trailing_emoticon("ok :D") == "ok 😃"
        assert convert_trailing_emoticon("<3") == "❤️"

    def test_text_without_one_is_unchanged(self):
        assert convert_trailing_emoticon("see http://x.com/:/") == "see http://x.com/:/"
        assert convert_trailing_emoticon("ok :D thanks") == "ok :D thanks"


class TestCaretValueIndex:
    def test_plain_ascii_is_one_to_one(self):
        assert caret_value_index("abc", 2) == 2

    def test_windows_line_breaks_count_twice(self):
        assert caret_value_index("a\nb", 3, newline_width=2) == 2

    def test_emoji_outside_the_bmp_count_twice_in_utf16(self):
        # "🙂 :D" — the caret after ":D" is native position 5, value index 4.
        assert caret_value_index("🙂 :D", 5, utf16=True) == 4
        assert caret_value_index("🙂 :D", 4, utf16=False) == 4

    def test_native_newline_width(self):
        assert native_newline_width("a\nb", os_name="nt") == 2
        assert native_newline_width("a\r\nb", os_name="nt") == 1
        assert native_newline_width("a\nb", os_name="posix") == 1


class TestSetting:
    def test_on_by_default(self):
        assert DEFAULT_SETTINGS["general"]["convert_emoticons"] is True
        assert emoticons_enabled({}) is True
        assert emoticons_enabled(None) is True

    def test_the_dialog_guard_reads_the_stored_value_like_the_composer(self):
        # Settings loads its checkbox through this; anything but an explicit
        # False is "on", exactly as emoticons_enabled() treats it.
        assert emoticon_setting_enabled(True) is True
        assert emoticon_setting_enabled(None) is True
        assert emoticon_setting_enabled("garbage") is True
        assert emoticon_setting_enabled(False) is False

    def test_explicitly_off(self):
        assert emoticons_enabled({"convert_emoticons": False}) is False


# ── The composer side ─────────────────────────────────────────────────────


class _NativeField:
    """A message field whose positions are native units: UTF-16 code units
    when *utf16*, as on Windows and macOS. Newlines count as one."""

    def __init__(self, text="", utf16=True):
        self.text = text
        self.utf16 = utf16
        self.caret = self._units(text)
        self.sel = (self.caret, self.caret)

    def _units(self, s):
        if not self.utf16:
            return len(s)
        return len(s.encode("utf-16-le")) // 2

    def _index(self, position):
        return caret_value_index(self.text, position, 1, self.utf16)

    def GetValue(self):
        return self.text

    def GetInsertionPoint(self):
        return self.caret

    def GetSelection(self):
        return self.sel

    def SetSelection(self, start, end):
        self.sel = (start, end)
        self.caret = end

    def WriteText(self, s):
        a, b = (self._index(p) for p in self.sel)
        self.text = self.text[:a] + s + self.text[b:]
        self.caret = self._units(self.text[:a] + s)
        self.sel = (self.caret, self.caret)

    def type(self, s):
        """What the native control does with a keystroke the handler skipped."""
        self.sel = (self.caret, self.caret)
        self.WriteText(s)


class _Panel:
    _emoticon_conversion_enabled = ConversationsPanel._emoticon_conversion_enabled
    _convert_emoticon_before_caret = ConversationsPanel._convert_emoticon_before_caret
    _arm_emoticon_undo = ConversationsPanel._arm_emoticon_undo
    _undo_emoticon_conversion = ConversationsPanel._undo_emoticon_conversion
    _text_with_trailing_emoticon = ConversationsPanel._text_with_trailing_emoticon
    _emoticon_conversation_jid = ConversationsPanel._emoticon_conversation_jid
    _editing_message_id = None

    def __init__(self, text, utf16=True, general=None):
        self.message_field = _NativeField(text, utf16)
        self.main_window = type("W", (), {"settings": {"general": general or {}}})()


@pytest.fixture
def after(monkeypatch):
    """Run wx.CallAfter callbacks when the test says the event loop would."""
    pending = []
    monkeypatch.setattr(emoticon_conversion.wx, "CallAfter",
                        lambda fn, *args: pending.append((fn, args)))
    monkeypatch.setattr(emoticon_conversion, "platform_counts_utf16", lambda: True)

    def flush():
        while pending:
            fn, args = pending.pop(0)
            fn(*args)
    return flush


def _type(panel, char, flush):
    """One keystroke through the EVT_CHAR order: handler, native insert, idle."""
    panel._convert_emoticon_before_caret(char)
    panel.message_field.type(char)
    flush()


class TestComposerConversion:
    def test_space_after_an_emoticon_converts_it(self, after):
        panel = _Panel("ok :D")
        _type(panel, " ", after)
        assert panel.message_field.GetValue() == "ok 😃 "
        assert panel.message_field.GetInsertionPoint() == len("ok ".encode("utf-16-le")) // 2 + 2 + 1

    def test_caret_stays_right_with_emoji_already_in_the_text(self, after):
        panel = _Panel("🎉 hi :)")
        _type(panel, "!", after)
        assert panel.message_field.GetValue() == "🎉 hi 🙂!"
        panel.message_field.type("x")
        assert panel.message_field.GetValue() == "🎉 hi 🙂!x"

    def test_a_letter_is_not_a_boundary(self, after):
        panel = _Panel("ok :D")
        _type(panel, "x", after)
        assert panel.message_field.GetValue() == "ok :Dx"

    def test_a_url_is_left_alone(self, after):
        panel = _Panel("http:/")
        _type(panel, " ", after)
        assert panel.message_field.GetValue() == "http:/ "

    def test_a_tab_typed_with_ctrl_tab_is_a_boundary(self, after):
        # The multiline field inserts a tab on Ctrl+Tab.
        panel = _Panel("ok :D")
        _type(panel, "\t", after)
        assert panel.message_field.GetValue() == "ok 😃\t"

    def test_editing_a_message_never_converts_while_typing(self, after):
        # The edit pre-fills the old text; appending a word must not
        # rewrite the ":/" already in it.
        panel = _Panel("see you :/")
        panel._editing_message_id = "MSGID"
        _type(panel, " ", after)
        assert panel.message_field.GetValue() == "see you :/ "

    def test_switched_off_in_settings(self, after):
        panel = _Panel("ok :D", general={"convert_emoticons": False})
        _type(panel, " ", after)
        assert panel.message_field.GetValue() == "ok :D "

    def test_typing_over_a_selection_does_not_convert(self, after):
        panel = _Panel("ok :D more")
        panel.message_field.sel = (6, 10)
        panel.message_field.caret = 10
        assert panel._convert_emoticon_before_caret(" ") is False
        assert panel.message_field.GetValue() == "ok :D more"


class TestBackspaceUndo:
    def test_backspace_right_after_restores_what_was_typed(self, after):
        panel = _Panel("ok :D")
        _type(panel, " ", after)
        assert panel._undo_emoticon_conversion() is True
        assert panel.message_field.GetValue() == "ok :D "
        assert panel.message_field.GetInsertionPoint() == len("ok :D ")

    def test_undo_is_for_the_next_keystroke_only(self, after):
        panel = _Panel("ok :D")
        _type(panel, " ", after)
        assert panel._undo_emoticon_conversion() is True
        # A second Backspace is an ordinary Backspace again.
        assert panel._undo_emoticon_conversion() is False

    def test_no_undo_once_something_else_was_typed(self, after):
        panel = _Panel("ok :D")
        _type(panel, " ", after)
        panel.message_field.type("a")
        assert panel._undo_emoticon_conversion() is False
        assert panel.message_field.GetValue() == "ok 😃 a"

    def test_not_armed_when_typing_outran_the_event_loop(self, after):
        panel = _Panel("ok :D")
        panel._convert_emoticon_before_caret(" ")
        panel.message_field.type(" ")
        panel.message_field.type("a")  # before the CallAfter ran
        after()
        assert panel._undo_emoticon_conversion() is False
        assert panel.message_field.GetValue() == "ok 😃 a"


class TestSendTime:
    def test_trailing_emoticon_is_converted_when_sent(self):
        assert _Panel("")._text_with_trailing_emoticon("ok :D") == "ok 😃"

    def test_not_when_switched_off(self):
        panel = _Panel("", general={"convert_emoticons": False})
        assert panel._text_with_trailing_emoticon("ok :D") == "ok :D"


class _KeyEvent:
    def __init__(self, key_code):
        self._key_code = key_code
        self.skipped = False

    def GetKeyCode(self):
        return self._key_code

    def ShiftDown(self):
        return False

    def Skip(self):
        self.skipped = True


class TestComposerKeyHandling:
    """The composer's own key handler routes Backspace to the undo."""

    def _panel(self):
        panel = _Panel("ok :D")
        panel._on_message_field_key_down = ConversationsPanel._on_message_field_key_down.__get__(panel)
        panel._mention_panel = type("P", (), {"IsShown": lambda self: False})()
        return panel

    def test_backspace_after_a_conversion_is_consumed_by_the_undo(self, after):
        panel = self._panel()
        _type(panel, " ", after)
        event = _KeyEvent(wx.WXK_BACK)
        panel._on_message_field_key_down(event)
        assert event.skipped is False
        assert panel.message_field.GetValue() == "ok :D "

    def test_any_other_key_cancels_the_undo(self, after):
        panel = self._panel()
        _type(panel, " ", after)
        panel._on_message_field_key_down(_KeyEvent(wx.WXK_DELETE))
        event = _KeyEvent(wx.WXK_BACK)
        panel._on_message_field_key_down(event)
        assert event.skipped is True  # an ordinary Backspace for the control
        assert panel.message_field.GetValue() == "ok 😃 "

    def test_numpad_insert_alone_keeps_the_undo(self, after):
        # NVDA's modifier on a laptop layout is Caps Lock, on a desktop one
        # Insert — either the main or the numpad one.
        panel = self._panel()
        _type(panel, " ", after)
        panel._on_message_field_key_down(_KeyEvent(wx.WXK_NUMPAD_INSERT))
        panel._on_message_field_key_down(_KeyEvent(wx.WXK_BACK))
        assert panel.message_field.GetValue() == "ok :D "

    def test_shift_alone_keeps_the_undo(self, after):
        panel = self._panel()
        _type(panel, " ", after)
        panel._on_message_field_key_down(_KeyEvent(wx.WXK_SHIFT))
        panel._on_message_field_key_down(_KeyEvent(wx.WXK_BACK))
        assert panel.message_field.GetValue() == "ok :D "


class TestRealTextCtrl:
    """The same conversion against a real wx.TextCtrl, so the native position
    arithmetic (UTF-16 units, Windows' two-position line breaks) is checked
    by the platform's own control rather than by the fake above. Hidden
    frame, never shown — see tests/conftest.py's hidden_frame()."""

    def _panel(self, frame, text):
        panel = _Panel("")
        panel.message_field = wx.TextCtrl(frame, style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        panel.message_field.SetValue(text)
        panel.message_field.SetInsertionPointEnd()
        return panel

    @pytest.mark.parametrize("text,boundary,expected", [
        ("ok :D", " ", "ok 😃 "),
        ("🎉 hi :)", "!", "🎉 hi 🙂!"),
        ("first line\n🎉 <3", ".", "first line\n🎉 ❤️."),
    ])
    def test_converts_in_place(self, wx_app, monkeypatch, text, boundary, expected):
        from tests.conftest import hidden_frame
        monkeypatch.setattr(emoticon_conversion.wx, "CallAfter", lambda fn, *args: None)
        frame = hidden_frame()
        try:
            panel = self._panel(frame, text)
            assert panel._convert_emoticon_before_caret(boundary) is True
            # What the native control does with the skipped keystroke.
            panel.message_field.WriteText(boundary)
            assert panel.message_field.GetValue() == expected
        finally:
            frame.Destroy()

    def test_backspace_undo_restores_the_typed_text(self, wx_app, monkeypatch):
        from tests.conftest import hidden_frame
        pending = []
        monkeypatch.setattr(emoticon_conversion.wx, "CallAfter",
                            lambda fn, *args: pending.append((fn, args)))
        frame = hidden_frame()
        try:
            panel = self._panel(frame, "🎉 ok :D")
            panel._convert_emoticon_before_caret(" ")
            panel.message_field.WriteText(" ")
            for fn, args in pending:
                fn(*args)
            assert panel._undo_emoticon_conversion() is True
            assert panel.message_field.GetValue() == "🎉 ok :D "
            assert panel.message_field.GetInsertionPoint() == panel.message_field.GetLastPosition()
        finally:
            frame.Destroy()


class _SendPanel(_Panel):
    """on_send_message() on the stub, recording what would go out."""
    on_send_message = ConversationsPanel.on_send_message

    def __init__(self, text, editing=None):
        super().__init__(text)
        self.conversation = {"remoteJid": "5511999999999@s.whatsapp.net"}
        self._editing_message_id = editing
        self.main_window.ensure_meta_ai_terms = lambda jid: True
        self.sent = []
        self.edited = []

    def _send_new_text_message(self, text, remote_jid):
        self.sent.append(text)

    def _apply_message_edit(self, text, remote_jid):
        self.edited.append(text)


class TestSendPath:
    def test_enter_right_after_an_emoticon_sends_the_emoji(self):
        panel = _SendPanel("ok :D")
        panel.on_send_message(None)
        assert panel.sent == ["ok 😃"]

    def test_an_emoticon_undone_with_backspace_is_sent_as_typed(self, after):
        panel = _SendPanel("ok :/")
        _type(panel, " ", after)
        assert panel.message_field.GetValue() == "ok 😕 "
        assert panel._undo_emoticon_conversion() is True
        panel.on_send_message(None)
        assert panel.sent == ["ok :/"]

    def test_the_undo_only_spares_the_text_it_left(self, after):
        # Typing on after the undo makes a different message; a new trailing
        # emoticon there converts as usual.
        panel = _SendPanel("ok :/")
        _type(panel, " ", after)
        panel._undo_emoticon_conversion()
        panel.message_field.type("then :D")
        panel.on_send_message(None)
        assert panel.sent == ["ok :/ then 😃"]

    def test_an_undo_in_one_chat_does_not_spare_the_same_text_in_another(self, after):
        panel = _SendPanel("ok :/")
        _type(panel, " ", after)
        assert panel._undo_emoticon_conversion() is True
        panel.conversation = {"remoteJid": "5511888888888@s.whatsapp.net"}
        panel.message_field = _NativeField("ok :/")
        panel.on_send_message(None)
        assert panel.sent == ["ok 😕"]

    def test_an_edit_is_saved_exactly_as_typed(self):
        panel = _SendPanel("fixed it :D", editing="MSGID")
        panel.on_send_message(None)
        assert panel.edited == ["fixed it :D"]
        assert panel.sent == []


class TestSpellCueWithEmoji:
    def test_the_caret_counts_an_emoji_as_two_native_units(self, monkeypatch):
        from ui.conversation_panel import composer
        monkeypatch.setattr(composer, "platform_counts_utf16", lambda: True)
        seen = []

        class _SpellChecker:
            def caret_moved(self, text, index):
                seen.append(index)

        class _CuePanel:
            _cue_spelling_at_caret = ConversationsPanel._cue_spelling_at_caret

            def _spell_check_enabled(self):
                return True

        panel = _CuePanel()
        panel._spell_checker = _SpellChecker()
        panel.message_field = _NativeField("🙂 helo")
        panel.message_field.caret = 3  # 🙂 is two native units, then the space
        panel._cue_spelling_at_caret()
        assert seen == [2]  # the "h" of "helo", not the "e"
