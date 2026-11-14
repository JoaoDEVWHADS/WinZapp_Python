"""F3 / Shift+F3 step through in-conversation search results from anywhere.

Enter and Shift+Enter already mean something in the messages list, so the
result navigation also answers to F3 (next) and Shift+F3 (previous) through the
conversation panel's accelerator table — the search field does not need focus.
Enter / Shift+Enter keep working inside the search field.

ConversationsPanel needs a running wx.App, so the accelerator wiring is checked
against the source text (same approach as tests/test_call_button_shortcuts.py)
and the locale files are read directly.
"""

from tests.locales import load_strings, registered_locale_codes

import wx

from tests.god_modules import conversations_source
from ui.accessible import AccessibleSearchNextResult, AccessibleSearchPrevResult

_SRC = conversations_source()
_KEYS = (
    "shortcut_search_f3_label",
    "shortcut_search_shift_f3_label",
    "shortcut_search_enter_label",
    "shortcut_search_shift_enter_label",
)


def test_buttons_announce_f3_and_shift_f3():
    assert AccessibleSearchNextResult().GetKeyboardShortcut(0) == (wx.ACC_OK, "F3")
    assert AccessibleSearchPrevResult().GetKeyboardShortcut(0) == (wx.ACC_OK, "Shift+F3")


def test_f3_accelerators_are_bound_to_next_and_previous():
    assert "(wx.ACCEL_NORMAL,  wx.WXK_F3,         self.ID_F3)," in _SRC
    assert "(wx.ACCEL_SHIFT,   wx.WXK_F3,         self.ID_SHIFT_F3)," in _SRC
    assert "self._on_search_next,               id=self.ID_F3)" in _SRC
    assert "self._on_search_prev,               id=self.ID_SHIFT_F3)" in _SRC


def test_enter_still_works_in_the_search_field():
    assert "wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER" in _SRC
    assert "self._on_search_prev(None)" in _SRC and "self._on_search_next(None)" in _SRC


def test_every_locale_documents_f3_and_enter_scope():
    for locale in registered_locale_codes():
        data = load_strings(locale)
        for key in _KEYS:
            assert data.get(key), f"{locale} lacks {key}"
        assert data["shortcut_search_f3_label"].startswith("F3:")
        assert data["shortcut_search_shift_f3_label"].startswith("Shift+F3:")
