"""Tests for format_toast_unread_suffix() (core/notification_manager.py).

Regression: a count of 0 used to fall into the same "count <= 1" branch as
a real single unread message, so the toast's "✉️ N não lidas" line showed
"1 não lida" for every notification whose chat had a synced (but zero)
unread count — reported live as a reaction to your own already-read
message still announcing an unread envelope with nothing behind it.
"""

from core.notification_manager import format_toast_unread_suffix


class _FakeI18n:
    _STRINGS = {
        "unread_sep_singular": "1 mensagem não lida",
        "unread_sep_plural": "{count} mensagens não lidas",
    }

    def t(self, key):
        return self._STRINGS[key]


class TestFormatToastUnreadSuffix:
    def test_zero_returns_empty_string(self):
        assert format_toast_unread_suffix(0, _FakeI18n()) == ""

    def test_none_returns_empty_string(self):
        assert format_toast_unread_suffix(None, _FakeI18n()) == ""

    def test_negative_returns_empty_string(self):
        assert format_toast_unread_suffix(-1, _FakeI18n()) == ""

    def test_one_uses_singular(self):
        assert format_toast_unread_suffix(1, _FakeI18n()) == "✉️ 1 mensagem não lida"

    def test_multiple_uses_plural_with_count(self):
        assert format_toast_unread_suffix(3, _FakeI18n()) == "✉️ 3 mensagens não lidas"
