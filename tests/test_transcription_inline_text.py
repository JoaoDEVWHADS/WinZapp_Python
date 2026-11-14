"""The stored form of a transcription that goes in the message's own line.

Pure: the record flag and the row text it makes (core.transcription.stored).
The key, the menu and the flow are in tests/test_transcription_inline.py.
"""

from core.transcription import stored
from core.transcription.backend import TranscriptionResult


def _result(text="olá mundo"):
    return TranscriptionResult(
        text=text, language="pt", language_probability=0.9, duration_seconds=3.0,
        backend="faster_whisper", model_id="small", vad_used=True,
    )


def _message(**value):
    record = {"text": "olá mundo", "at": 10.0}
    record.update(value)
    return {"messageType": "audioMessage", stored.TRANSCRIPTION_KEY: record}


class TestTheRecord:
    def test_a_record_made_for_the_window_is_what_it_always_was(self):
        record = stored.record_from_result(_result(), 5.0)
        assert "inline" not in record

    def test_an_inline_record_says_so(self):
        record = stored.record_from_result(_result(), 5.0, inline=True)
        assert record["inline"] is True
        assert stored.is_inline(record)

    def test_only_an_explicit_true_counts(self):
        assert not stored.is_inline({"inline": "yes"})
        assert not stored.is_inline({"inline": 1})
        assert not stored.is_inline(None)
        assert not stored.is_inline({})


class TestTheRowText:
    def test_an_inline_transcription_shows_in_the_row(self):
        assert stored.inline_row_text(_message(inline=True)) == "olá mundo"

    def test_one_made_for_the_window_leaves_the_row_short(self):
        assert stored.inline_row_text(_message()) == ""

    def test_line_breaks_become_spaces_because_a_row_is_one_line(self):
        message = _message(inline=True, text="primeira\n\nsegunda   parte\r\nfim")
        assert stored.inline_row_text(message) == "primeira segunda parte fim"

    def test_a_deleted_one_shows_nothing(self):
        message = {"messageType": "audioMessage",
                   stored.TRANSCRIPTION_KEY: stored.tombstone(20.0)}
        assert stored.inline_row_text(message) == ""

    def test_nothing_stored_shows_nothing(self):
        assert stored.inline_row_text({"messageType": "audioMessage"}) == ""
        assert stored.inline_row_text(None) == ""

    def test_a_blank_text_shows_nothing(self):
        assert stored.inline_row_text(_message(inline=True, text="  \n ")) == ""


class TestTheFlagSurvivesTheRules:
    def test_a_copy_without_the_key_inherits_the_flag_with_the_rest(self):
        old = _message(inline=True)
        new = {"messageType": "audioMessage", "key": {"id": "x"}}
        merged = stored.with_known_transcription(new, old)
        assert stored.is_inline(merged.get(stored.TRANSCRIPTION_KEY))
