"""Spelling feedback is sound-only and must not interrupt native speech."""

from types import SimpleNamespace
import pytest
from core.spell_checker import WindowsSpellChecker
from ui.conversation_panel.composer import ComposerMixin


@pytest.mark.parametrize("obsolete_modes", [None, [], ["speech"], ["sound", "speech"]])
def test_sound_only_even_with_obsolete_feedback_settings(obsolete_modes):
    played = []

    def no_speech(*args, **kwargs):
        pytest.fail("Spelling feedback must not speak or cancel speech")

    host = SimpleNamespace(
        settings={"general": {"spell_check_feedback": obsolete_modes}},
        spelling_error_sound=SimpleNamespace(play=lambda: played.append(True)),
        speak_output=SimpleNamespace(output=no_speech, silence=no_speech),
    )
    panel = SimpleNamespace(main_window=host)
    checker = WindowsSpellChecker(on_error=lambda: ComposerMixin._play_spelling_error_sound(panel))
    checker.errors_for_text = lambda text: [(3, 7)]
    text = "ok caza ok"
    for index in (0, 3, 4, 5, 6, 7, 9):
        checker.caret_moved(text, index)
    assert played == [True]  # No exit announcement or repeated character.
    checker.caret_moved(text, 3)
    assert played == [True, True]

