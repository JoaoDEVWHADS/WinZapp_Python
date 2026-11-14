"""Pure-logic tests for the small message-field spell-check adapter."""

import core.spell_checker as spell_checker
import pytest
from core.spell_checker import (
    WindowsSpellChecker,
    _word_ended,
    word_span_at,
)
from tests.locales import registered_locale_codes


def test_word_ended_only_on_transition_to_whitespace():
    assert _word_ended("ktury", "ktury ")
    assert not _word_ended("ktury ", "ktury  ")
    assert not _word_ended("ktury", "ktur")
    assert not _word_ended("ktury drugi", "ktury ")
    assert not _word_ended("ktury", "ktury  ")


def test_checker_tracks_text_and_returns_errors_after_word_boundary():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)] if text.startswith("ktury") else []
    assert checker.text_changed("ktury") == []
    assert checker.text_changed("ktury ") == [(0, 5)]
    assert played == [True]
    # A second space must not retrigger the same word.
    assert checker.text_changed("ktury  ") == []
    assert played == [True]


def test_deleting_a_misspelled_word_does_not_replay_the_sound():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5), (6, 11)]

    checker.text_changed("ktury drugi")
    assert checker.text_changed("ktury ") == []
    assert played == []


def test_language_candidates_prefer_winzapp_then_use_windows(monkeypatch):
    monkeypatch.setattr(
        spell_checker,
        "_windows_language_names",
        lambda: ["de-DE", "pl-PL"],
    )

    assert spell_checker._language_candidates("pl") == ["pl-PL", "de-DE"]


def test_changing_language_reopens_the_checker_lazily():
    checker = WindowsSpellChecker(language="pl")
    checker._initialized = True
    checker._checker = object()
    checker.language = "pl-PL"

    checker.set_language("en-US")

    assert checker.preferred_language == "en-US"
    assert checker.language == ""
    assert checker._checker is None
    assert checker._initialized is False


def test_reset_rebaselines_without_checking_or_cueing():
    """While the Settings > Geral switch is off the composer calls reset()
    instead of text_changed(), so re-enabling mid-message cannot mistake the
    text already in the field for a word just typed."""
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)]

    checker.reset("ktury")
    assert played == []

    # The very next keystroke is now a normal one-character append again.
    assert checker.text_changed("ktury ") == [(0, 5)]
    assert played == [True]


def test_reset_with_no_argument_clears_the_baseline():
    checker = WindowsSpellChecker()
    checker.text_changed("abc")
    checker.reset()
    assert checker._last_text == ""


def test_every_registered_locale_reaches_windows_with_a_region():
    # The Windows spelling API is given full BCP 47 tags (pl-PL, not the
    # "pl" language_map.json uses), so a bare code risks matching no
    # installed dictionary. A new region-less locale has to be mapped in
    # _WINZAPP_LANGUAGE_TAGS.
    for code in registered_locale_codes():
        tag = spell_checker._normalize_language_tag(code)
        assert "-" in tag, (code, tag)


@pytest.mark.parametrize("mark", [",", ".", "?", "!", ";", ":", ")"])
def test_punctuation_ends_a_word_like_a_space(mark):
    assert _word_ended("ktury", "ktury" + mark)


@pytest.mark.parametrize("text", ["ktury'", "ktury-", "ktury\u2019"])
def test_apostrophe_and_hyphen_stay_inside_the_word(text):
    assert not _word_ended(text[:-1], text)


def test_punctuation_after_a_boundary_does_not_cue_again():
    assert not _word_ended("ktury,", "ktury,,")
    assert not _word_ended("ktury ", "ktury ,")
    assert not _word_ended("", "")


def test_comma_cues_a_misspelled_word():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 5)]
    checker.text_changed("ktury")
    checker.text_changed("ktury,")
    assert played == [True]


def test_word_span_at():
    text = "ab cd, don't"
    assert word_span_at(text, 0) == (0, 2)
    assert word_span_at(text, 2) == (0, 2)
    assert word_span_at(text, 3) == (3, 5)
    assert word_span_at(text, 5) == (3, 5)
    assert word_span_at(text, 6) is None
    assert word_span_at(text, 9) == (7, 12)
    assert word_span_at("", 0) is None


def test_caret_arriving_at_a_misspelled_word_cues_once():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(3, 8)]
    text = "ab ktury cd"
    assert not checker.caret_moved(text, 0)
    assert checker.caret_moved(text, 3)
    # Moving inside the same word does not repeat it.
    assert not checker.caret_moved(text, 5)
    assert not checker.caret_moved(text, 8)
    # Leaving and coming back does.
    assert not checker.caret_moved(text, 10)
    assert checker.caret_moved(text, 4)
    assert played == [True, True]


def test_caret_between_words_resets_and_does_not_cue():
    checker = WindowsSpellChecker(on_error=lambda: None)
    checker.errors_for_text = lambda text: [(0, 2)]
    assert checker.caret_moved("ab  cd", 0)
    assert not checker.caret_moved("ab  cd", 3)
    assert checker.caret_moved("ab  cd", 1)


def test_typing_and_reset_forget_the_caret_word():
    played = []
    checker = WindowsSpellChecker(on_error=lambda: played.append(True))
    checker.errors_for_text = lambda text: [(0, 2)]
    checker.caret_moved("ab", 0)
    checker.text_changed("ab")
    assert checker.caret_moved("ab", 0)
    checker.reset("ab")
    assert checker.caret_moved("ab", 0)
    assert len(played) == 3


class _SuggestionEnumerator:
    """Mimics comtypes' IEnumString.Next(1): ``(value, fetched)``, then ``(None, 0)``."""

    def __init__(self, values):
        self.values = iter(values)

    def Next(self, count=1):
        try:
            return next(self.values), 1
        except StopIteration:
            return None, 0


def _checker_suggesting(values):
    checker = WindowsSpellChecker()
    checker._get_checker = lambda: type(
        "FakeChecker", (), {
            "Suggest": lambda _self, _word: _SuggestionEnumerator(values)
        }
    )()
    return checker


def test_suggestions_for_word_reads_windows_replacements_and_deduplicates():
    checker = _checker_suggesting(["correct", "correct", "correction"])

    assert checker.suggestions_for_word("corect") == ["correct", "correction"]


def test_suggestions_for_word_honours_the_limit_and_skips_the_word_itself():
    checker = _checker_suggesting(["corect", "a", "b", "c"])

    assert checker.suggestions_for_word("corect", limit=2) == ["a", "b"]


def test_suggestions_for_word_survives_a_failing_enumerator(monkeypatch):
    # COMError only exists where comtypes imports; any exception type will do.
    monkeypatch.setattr(spell_checker, "COMError", OSError, raising=False)
    checker = WindowsSpellChecker()

    def broken_next(*_args):
        raise OSError("boom")

    checker._get_checker = lambda: type(
        "FakeChecker", (), {
            "Suggest": lambda _self, _word: type("E", (), {"Next": broken_next})()
        }
    )()

    assert checker.suggestions_for_word("corect") == []


def test_suggestions_for_word_with_a_null_enumerator_is_empty():
    checker = WindowsSpellChecker()
    checker._get_checker = lambda: type(
        "FakeChecker", (), {"Suggest": lambda _self, _word: None}
    )()

    assert checker.suggestions_for_word("corect") == []


def test_suggestions_at_requires_the_caret_to_touch_a_spelling_error():
    checker = WindowsSpellChecker()
    checker.errors_for_text = lambda _text: [(3, 9)]
    checker.suggestions_for_word = lambda word, limit=5: ["correct"]

    assert checker.suggestions_at("ab corect", 4) == (3, 9, ["correct"])
    assert checker.suggestions_at("ab corect", 0) is None


def test_errors_for_text_converts_utf16_offsets_to_python_indices():
    """The COM API counts the emoji as two UTF-16 units; Python counts one."""
    text = "\U0001F642 wrng"  # emoji, space, misspelled word
    error = type("Err", (), {
        "get_StartIndex": lambda _self: 3,
        "get_Length": lambda _self: 4,
        "get_CorrectiveAction": lambda _self: 1,
    })()
    items = iter([error, None])
    enumeration = type("Enum", (), {"Next": lambda _self: next(items)})()
    checker = WindowsSpellChecker()
    checker._get_checker = lambda: type(
        "FakeChecker", (), {"Check": lambda _self, _text: enumeration}
    )()

    assert checker.errors_for_text(text) == [(2, 6)]
