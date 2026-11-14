"""EmoticonConversionMixin — part of ConversationsPanel (see ui/conversation_panel/__init__.py).

Turns ":)" into 🙂 in the message field as it is typed, like WhatsApp
Web/Desktop. What converts, and when, is core/emoticons.py (pure, tested
directly); this only reads the field, swaps the token for the emoji and
offers the one-keystroke undo.

No speech of its own: the replacement goes through the field like any other
edit, and the screen reader's own echo of the typed character is enough.
"""

import wx

from core.emoticons import (
    BOUNDARY_CHARS,
    caret_value_index,
    convert_trailing_emoticon,
    emoticon_before_caret,
    emoticons_enabled,
    native_newline_width,
    native_units,
    platform_counts_utf16,
)


class EmoticonConversionMixin:
    """Emoticon -> emoji conversion in the message field, and its undo."""

    def _emoticon_conversion_enabled(self) -> bool:
        """Settings > Geral, read on every boundary keystroke so a change in
        Settings applies at once, like _spell_check_enabled()."""
        try:
            general = self.main_window.settings.get("general", {})
        except Exception:
            return True
        return emoticons_enabled(general)

    def _convert_emoticon_before_caret(self, boundary: str) -> bool:
        """Replace a standalone emoticon just before the caret with its emoji.

        Called while *boundary* (a space, punctuation or a newline) is about
        to be inserted at the caret, before the control inserts it, so the
        boundary lands after the emoji. Returns True when something was
        converted.
        """
        if boundary not in BOUNDARY_CHARS or not self._emoticon_conversion_enabled():
            return False
        if getattr(self, "_editing_message_id", None) is not None:
            # An edit keeps the person's text as typed (text_sending.py):
            # appending a word must not rewrite an old ":/" in the message.
            return False
        field = self.message_field
        sel_from, sel_to = field.GetSelection()
        if sel_from != sel_to:
            # Typing over a selection replaces it; what precedes the caret
            # is not what will precede the boundary.
            return False
        text = field.GetValue()
        position = field.GetInsertionPoint()
        newline_width = native_newline_width(text)
        index = caret_value_index(text, position, newline_width, platform_counts_utf16())
        found = emoticon_before_caret(text[:index])
        if found is None:
            return False
        token, emoji = found
        # Every token is ASCII on one line, so its native width is its length.
        start = position - len(token)
        # SetSelection + WriteText rather than Replace(): WriteText() leaves
        # the caret after the inserted text on every platform, which is
        # exactly where the boundary character has to go next — the same
        # reason the Shift+Enter newline uses it (composer.py).
        field.SetSelection(start, position)
        field.WriteText(emoji)
        # Armed once the boundary is actually in the field: the control
        # inserts it only after this handler returns.
        wx.CallAfter(self._arm_emoticon_undo, start, emoji, token, boundary)
        return True

    def _arm_emoticon_undo(self, start: int, emoji: str, token: str, boundary: str):
        """Remember a conversion so an immediate Backspace can restore it.

        Armed only if the caret sits right after emoji + boundary, i.e.
        nothing else was typed before this ran — otherwise a Backspace would
        undo the wrong range.
        """
        field = self.message_field
        utf16 = platform_counts_utf16()
        text = field.GetValue()
        newline_width = native_newline_width(text)
        end = start + sum(native_units(c, newline_width, utf16) for c in emoji + boundary)
        if field.GetInsertionPoint() != end:
            self._emoticon_undo = None
            return
        self._emoticon_undo = (start, end, token + boundary, text)

    def _undo_emoticon_conversion(self) -> bool:
        """Backspace right after a conversion: put the typed text back.

        Restores the emoticon and keeps the boundary character, so ":) "
        reads exactly as typed. Returns True when it handled the key.
        """
        undo = getattr(self, "_emoticon_undo", None)
        self._emoticon_undo = None
        if undo is None:
            return False
        start, end, original, value = undo
        field = self.message_field
        sel_from, sel_to = field.GetSelection()
        if (sel_from != sel_to or field.GetInsertionPoint() != end
                or field.GetValue() != value):
            return False
        field.SetSelection(start, end)
        field.WriteText(original)
        # Remember the text up to and including the restored token, so the
        # send path does not convert the very emoticon just undone: "ok :/ "
        # + Backspace + Enter has to send ":/". The boundary is a single
        # character in GetValue() even when it is a Windows line break.
        text = field.GetValue()
        newline_width = native_newline_width(text)
        caret = caret_value_index(text, field.GetInsertionPoint(), newline_width,
                                  platform_counts_utf16())
        # Tied to the open conversation: the same text typed in another chat
        # was never undone there.
        self._emoticon_undone = (self._emoticon_conversation_jid(), text[:caret - 1])
        return True

    def _emoticon_conversation_jid(self) -> str:
        conversation = getattr(self, "conversation", None) or {}
        return conversation.get("remoteJid", "")

    def _text_with_trailing_emoticon(self, text: str) -> str:
        """The text to send: "ok :D" + Enter goes out as "ok 😃".

        Except when that trailing emoticon is one the person undid with
        Backspace: the message is then exactly the text left by the undo
        (anything typed since would have changed it), and converting it
        here would redo what they explicitly took back.
        """
        undone = getattr(self, "_emoticon_undone", None)
        self._emoticon_undone = None
        if not self._emoticon_conversion_enabled():
            return text
        if undone is not None:
            undone_jid, undone_text = undone
            if undone_jid == self._emoticon_conversation_jid() and undone_text.strip() == text:
                return text
        return convert_trailing_emoticon(text)
