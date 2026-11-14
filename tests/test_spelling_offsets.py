"""Spelling suggestions and sound resolve the right word, emoji and all."""

from types import SimpleNamespace

import pytest

from core.emoticons import caret_value_index, native_position


@pytest.mark.parametrize("text", ["hello", "😀 wrong\nword", "olá\n\n😀fim", ""])
@pytest.mark.parametrize("newline_width", [1, 2])
@pytest.mark.parametrize("utf16", [False, True])
def test_native_position_round_trips_through_caret_value_index(text, newline_width, utf16):
    for index in range(len(text) + 1):
        native = native_position(text, index, newline_width, utf16)
        assert caret_value_index(text, native, newline_width, utf16) == index


def test_native_position_counts_an_emoji_as_two_utf16_units():
    assert native_position("😀 ab", 2, utf16=True) == 3
    assert native_position("😀 ab", 2, utf16=False) == 2


def test_native_position_clamps_out_of_range_indices():
    assert native_position("ab", 99) == 2
    assert native_position("ab", -3) == 0


def _field(**overrides):
    field = SimpleNamespace(
        GetInsertionPoint=lambda: 7,
        ScreenToClient=lambda point: point,
        HitTestPos=lambda point: (0, 3),
    )
    for name, value in overrides.items():
        setattr(field, name, value)
    return field


def test_context_menu_targets_the_clicked_word_not_the_caret():
    import wx
    from ui.conversation_panel.composer import ComposerMixin

    panel = SimpleNamespace(message_field=_field())
    event = SimpleNamespace(GetPosition=lambda: wx.Point(10, 20))

    assert ComposerMixin._spelling_menu_position(panel, event) == 3


def test_context_menu_from_the_applications_key_targets_the_caret():
    import wx
    from ui.conversation_panel.composer import ComposerMixin

    panel = SimpleNamespace(message_field=_field())
    event = SimpleNamespace(GetPosition=lambda: wx.DefaultPosition)

    assert ComposerMixin._spelling_menu_position(panel, event) == 7


def test_context_menu_falls_back_to_the_caret_when_hit_testing_is_unavailable():
    import wx
    from ui.conversation_panel.composer import ComposerMixin

    unknown = _field(HitTestPos=lambda point: (wx.TE_HT_UNKNOWN, -1))
    broken = _field(HitTestPos=lambda point: (_ for _ in ()).throw(RuntimeError()))
    event = SimpleNamespace(GetPosition=lambda: wx.Point(10, 20))

    for field in (unknown, broken):
        panel = SimpleNamespace(message_field=field)
        assert ComposerMixin._spelling_menu_position(panel, event) == 7


def test_replacing_a_word_selects_native_positions_after_an_emoji(monkeypatch):
    from ui.conversation_panel import composer
    from ui.conversation_panel.composer import ComposerMixin

    monkeypatch.setattr(composer, "platform_counts_utf16", lambda: True)
    events = []
    field = SimpleNamespace(
        GetValue=lambda: "😀 wrng ok",
        SetSelection=lambda start, end: events.append(("select", start, end)),
        WriteText=lambda text: events.append(("write", text)),
        SetFocus=lambda: events.append(("focus",)),
    )

    ComposerMixin._replace_spelling_word(SimpleNamespace(message_field=field), 2, 6, "wrong")

    assert events == [("select", 3, 7), ("write", "wrong"), ("focus",)]
