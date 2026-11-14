"""Text emoticons -> emoji, the way WhatsApp Web/Desktop converts them.

WhatsApp's own clients turn ":)" into 🙂 as it is typed; WinZapp's composer
does the same (ui/conversation_panel/emoticon_conversion.py) so a message
written here arrives looking like one written there. Everything that decides
*whether* and *what* to convert lives here, as plain functions, because the
composer is a wx.TextCtrl on a wx.Panel and cannot be built in a test.

The one rule that keeps conversion from ever damaging text the user meant
literally: a token converts only when it stands alone — at the very start of
the text or right after whitespace. That is what leaves "http://", "a:b",
"10:30", "word:P" and "(:)" untouched without a list of exceptions.
"""

import os
import sys

# Token -> emoji. Dict order is irrelevant: emoticon_before_caret() tries the
# longest token first, so ":-)" never half-matches as ")".
EMOTICONS = {
    ":)": "🙂",
    ":-)": "🙂",
    ":(": "🙁",
    ":-(": "🙁",
    ":D": "😃",
    ":-D": "😃",
    ";)": "😉",
    ";-)": "😉",
    ":P": "😛",
    ":-P": "😛",
    ":p": "😛",
    ":-p": "😛",
    ":O": "😮",
    ":-O": "😮",
    ":o": "😮",
    ":-o": "😮",
    ":*": "😘",
    ":-*": "😘",
    ":'(": "😢",
    # The same with a typographic apostrophe, which macOS's smart quotes and
    # several phone keyboards substitute for the straight one.
    ":’(": "😢",
    ":|": "😐",
    ":-|": "😐",
    ":/": "😕",
    ":-/": "😕",
    "<3": "❤️",
    "XD": "😆",
    "xD": "😆",
    "B-)": "😎",
}

_TOKENS_LONGEST_FIRST = sorted(EMOTICONS, key=len, reverse=True)

# Typed right after a token, these end it and trigger the conversion.
# Deliberately not ":" or ";" — both start emoticons, and ":D:" or ";):"
# typed in a row should not flip the first one mid-sequence. Newline is
# handled by the composer itself (Shift+Enter inserts it with WriteText(),
# which raises no EVT_CHAR).
BOUNDARY_CHARS = frozenset(" \t\n.,!?")


def emoticon_setting_enabled(value) -> bool:
    """The stored ``convert_emoticons`` value -> whether conversion is on.

    On unless explicitly switched off: a settings.json from before the option
    existed gets the default through backfill_missing_defaults(), and a
    damaged value must not quietly turn the feature off either. The Settings
    dialog loads its checkbox through this too, so the box never shows a
    state the composer does not act on.
    """
    return value is not False


def emoticons_enabled(general) -> bool:
    """Settings > Geral > "Convert emoticons like :D to emoji while typing"."""
    if not isinstance(general, dict):
        return True
    return emoticon_setting_enabled(general.get("convert_emoticons", True))


def _inside_code(text_before: str) -> bool:
    """True when an unclosed `code` or ```block``` span is open at the end.

    WhatsApp's monospace markers are backticks; an odd count before the
    caret means one is still open, and text inside code is meant literally.
    """
    return text_before.count("`") % 2 == 1


def emoticon_before_caret(text_before: str):
    """(token, emoji) for the standalone emoticon that ends *text_before*,
    or None.

    *text_before* is everything from the start of the message up to the
    caret, as GetValue() reports it.
    """
    if not text_before or _inside_code(text_before):
        return None
    for token in _TOKENS_LONGEST_FIRST:
        if not text_before.endswith(token):
            continue
        start = len(text_before) - len(token)
        if start == 0 or text_before[start - 1].isspace():
            return token, EMOTICONS[token]
        # A longer token already failed the standalone test, so a shorter
        # suffix of it ("-)" inside ":-)") must not get a second chance.
        return None
    return None


def convert_trailing_emoticon(text: str) -> str:
    """*text* with a standalone emoticon at its very end converted.

    The send path: "ok :D" followed straight by Enter never typed a boundary
    character, yet WhatsApp sends it as "ok 😃".
    """
    found = emoticon_before_caret(text)
    if found is None:
        return text
    token, emoji = found
    return text[: len(text) - len(token)] + emoji


def native_units(char: str, newline_width: int, utf16: bool) -> int:
    """How many caret positions the native text control gives *char*."""
    if char == "\n":
        return newline_width
    if utf16 and ord(char) > 0xFFFF:
        return 2
    return 1


def native_newline_width(text: str, os_name: str = os.name) -> int:
    """Caret positions a line break takes in the message field's GetValue().

    A Windows multiline control counts "\\n" as two, unless the value
    already carries "\\r\\n" (then each character counts once).
    """
    return 2 if os_name == "nt" and "\r\n" not in text else 1


def caret_value_index(text: str, position: int, newline_width: int = 1, utf16: bool = False) -> int:
    """Convert a native caret position to an index into GetValue() text.

    Two ways the native count differs from Python's: a Windows multiline
    control counts a line break as two positions while GetValue() reports a
    bare "\\n", and both the Windows edit control and
    macOS's NSTextView count in UTF-16 units, so every emoji outside the BMP
    — 🙂 itself, once one has been converted — takes two. Ignoring the
    second would put the caret one character further left for every emoji
    already in the message.
    """
    native = 0
    for i, char in enumerate(text):
        if native >= position:
            return i
        native += native_units(char, newline_width, utf16)
    return len(text)


def native_position(text: str, index: int, newline_width: int = 1, utf16: bool = False) -> int:
    """Inverse of caret_value_index: the native position of GetValue() index *index*."""
    index = max(0, min(len(text), index))
    return sum(native_units(char, newline_width, utf16) for char in text[:index])


def platform_counts_utf16() -> bool:
    """Whether wx.TextCtrl positions are UTF-16 units on this platform."""
    return os.name == "nt" or sys.platform == "darwin"
