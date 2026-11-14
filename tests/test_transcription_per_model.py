"""A stored transcription belongs to the model that made it.

Pure rules of core.transcription.stored: which result a message offers for the
selected model, how a new result keeps the other models', and how clearing one
model's results leaves the rest (or a tombstone) at a later decision.
"""

import pytest

from core.transcription import stored
from core.transcription.stored import TRANSCRIPTION_KEY


def _rec(model, text, at=10.0, backend="faster_whisper", **extra):
    return {"text": text, "model_id": model, "backend": backend, "at": at,
            "language": "pt", "vad_used": True, **extra}


def _msg(value):
    return {"messageType": "audioMessage", TRANSCRIPTION_KEY: value}


AUTO = ("auto", "auto")


class TestTheSelection:
    def test_no_settings_is_auto(self):
        assert stored.selection_from_settings({}) == AUTO
        assert stored.selection_from_settings(None) == AUTO
        assert stored.selection_from_settings({"transcription": "junk"}) == AUTO

    def test_the_two_settings_are_read(self):
        settings = {"transcription": {"backend": "whisper_cpp", "model": "small"}}
        assert stored.selection_from_settings(settings) == ("whisper_cpp", "small")

    def test_a_missing_or_blank_value_is_auto(self):
        settings = {"transcription": {"backend": "", "model": None}}
        assert stored.selection_from_settings(settings) == AUTO


class TestWhatAMessageOffers:
    def test_under_auto_the_newest_result_is_offered_as_always(self):
        msg = _msg(_rec("small", "olá"))
        assert stored.saved_transcription(msg) is msg[TRANSCRIPTION_KEY]
        assert stored.saved_transcription(msg, AUTO) is msg[TRANSCRIPTION_KEY]

    def test_the_selected_models_result_is_offered(self):
        msg = _msg(_rec("small", "olá"))
        assert stored.saved_transcription(msg, ("auto", "small"))["text"] == "olá"

    def test_another_models_result_is_not(self):
        msg = _msg(_rec("small", "olá"))
        assert stored.saved_transcription(msg, ("auto", "medium")) is None

    def test_the_backend_has_to_match_too(self):
        msg = _msg(_rec("small", "olá", backend="faster_whisper"))
        assert stored.saved_transcription(msg, ("whisper_cpp", "small")) is None
        assert stored.saved_transcription(msg, ("faster_whisper", "small")) is not None

    def test_a_model_chosen_with_automatic_backend_matches_any_backend(self):
        msg = _msg(_rec("small", "olá", backend="whisper_cpp"))
        assert stored.saved_transcription(msg, ("auto", "small")) is not None

    def test_an_older_models_result_is_found_among_the_others(self):
        value = stored.with_result(_rec("small", "olá", at=5.0), _rec("medium", "olá!", at=9.0))
        msg = _msg(value)
        assert stored.saved_transcription(msg, ("auto", "medium"))["text"] == "olá!"
        assert stored.saved_transcription(msg, ("auto", "small"))["text"] == "olá"

    def test_the_outer_record_comes_back_itself_so_the_others_are_not_lost(self):
        value = stored.with_result(_rec("small", "a", at=5.0), _rec("medium", "b", at=9.0))
        assert stored.saved_transcription(_msg(value), ("auto", "medium")) is value

    def test_a_tombstone_and_a_blank_text_offer_nothing(self):
        assert stored.saved_transcription(_msg(stored.tombstone(3.0)), ("auto", "small")) is None
        assert stored.saved_transcription(_msg(_rec("small", "  ")), ("auto", "small")) is None
        assert stored.saved_transcription({}, ("auto", "small")) is None
        assert stored.saved_transcription(None, ("auto", "small")) is None

    def test_a_record_without_a_model_matches_any_selection(self):
        """Stored before results were kept per model: nothing to tell it
        apart by (see TestARecordFromBeforePerModel)."""
        msg = _msg({"text": "x", "at": 1.0})
        assert stored.saved_transcription(msg, AUTO) is not None
        assert stored.saved_transcription(msg, ("auto", "small")) is not None


class TestAddingAResult:
    def test_a_new_model_keeps_the_previous_result_alongside(self):
        value = stored.with_result(_rec("small", "a", at=5.0), _rec("medium", "b", at=9.0))
        assert value["model_id"] == "medium"
        assert set(value[stored.BY_MODEL_KEY]) == {"faster_whisper:small"}
        assert value[stored.BY_MODEL_KEY]["faster_whisper:small"]["text"] == "a"

    def test_three_models_keep_all_three(self):
        one = _rec("tiny", "t", at=1.0)
        two = stored.with_result(one, _rec("small", "s", at=2.0))
        three = stored.with_result(two, _rec("medium", "m", at=3.0))
        assert {r["model_id"] for r in stored.results_of(three)} == {"tiny", "small", "medium"}
        assert three["model_id"] == "medium"

    def test_the_same_model_again_replaces_its_own_result(self):
        first = stored.with_result(_rec("small", "a", at=1.0), _rec("medium", "b", at=2.0))
        again = stored.with_result(first, _rec("small", "a2", at=3.0))
        texts = {r["model_id"]: r["text"] for r in stored.results_of(again)}
        assert texts == {"small": "a2", "medium": "b"}

    def test_the_nested_results_are_flat(self):
        three = stored.with_result(
            stored.with_result(_rec("tiny", "t", at=1.0), _rec("small", "s", at=2.0)),
            _rec("medium", "m", at=3.0))
        assert all(stored.BY_MODEL_KEY not in rec for rec in three[stored.BY_MODEL_KEY].values())

    def test_after_a_tombstone_nothing_is_kept(self):
        value = stored.with_result(stored.tombstone(5.0), _rec("small", "a", at=6.0))
        assert stored.BY_MODEL_KEY not in value

    def test_without_a_previous_it_is_just_the_record(self):
        assert stored.with_result(None, _rec("small", "a")) == _rec("small", "a")

    def test_the_inputs_are_not_mutated(self):
        previous = _rec("small", "a", at=1.0)
        record = _rec("medium", "b", at=2.0)
        stored.with_result(previous, record)
        assert stored.BY_MODEL_KEY not in previous and stored.BY_MODEL_KEY not in record


class TestClearingAModel:
    def _two(self):
        return stored.with_result(_rec("small", "a", at=5.0), _rec("medium", "b", at=9.0))

    def test_nothing_of_that_model_changes_nothing(self):
        value = self._two()
        new, count = stored.drop_model(value, "large", None, 20.0)
        assert new is value and count == 0

    def test_dropping_the_other_model_keeps_the_current_one_untouched_in_content(self):
        new, count = stored.drop_model(self._two(), "small", None, 20.0)
        assert count == 1
        assert new["model_id"] == "medium" and new["text"] == "b"
        assert stored.BY_MODEL_KEY not in new

    def test_dropping_the_current_one_promotes_the_next_newest(self):
        new, count = stored.drop_model(self._two(), "medium", None, 20.0)
        assert count == 1
        assert new["model_id"] == "small" and new["text"] == "a"

    def test_the_new_outer_record_is_a_later_decision_so_it_beats_a_stale_copy(self):
        value = self._two()
        new, _ = stored.drop_model(value, "medium", None, 20.0)
        assert stored.newer_decision(new, value) is new

    def test_the_date_the_text_was_made_survives(self):
        new, _ = stored.drop_model(self._two(), "medium", None, 20.0)
        assert new["at"] == 20.0
        assert stored.made_time(new) == 5.0

    def test_the_made_date_does_not_drift_on_a_second_clear(self):
        three = stored.with_result(self._two(), _rec("large", "c", at=12.0))
        once, _ = stored.drop_model(three, "large", None, 20.0)
        twice, _ = stored.drop_model(once, "medium", None, 30.0)
        assert twice["model_id"] == "small"
        assert stored.made_time(twice) == 5.0

    def test_dropping_the_only_model_leaves_a_tombstone_at_the_decision(self):
        only = _rec("small", "a", at=5.0)
        new, count = stored.drop_model(only, "small", None, 20.0)
        assert count == 1
        assert new == stored.tombstone(20.0)
        assert stored.saved_transcription(_msg(new)) is None

    def test_a_backend_scopes_the_drop(self):
        both = stored.with_result(
            _rec("small", "x", at=1.0, backend="faster_whisper"),
            _rec("small", "y", at=2.0, backend="whisper_cpp"))
        new, count = stored.drop_model(both, "small", "whisper_cpp", 20.0)
        assert count == 1
        assert new["backend"] == "faster_whisper" and new["text"] == "x"

    def test_no_backend_drops_the_model_under_every_one(self):
        both = stored.with_result(
            _rec("small", "x", at=1.0, backend="faster_whisper"),
            _rec("small", "y", at=2.0, backend="whisper_cpp"))
        new, count = stored.drop_model(both, "small", None, 20.0)
        assert count == 2 and new == stored.tombstone(20.0)

    def test_the_inline_choice_of_what_is_left_is_kept(self):
        value = stored.with_result(_rec("small", "a", at=1.0, inline=True), _rec("medium", "b", at=2.0))
        new, _ = stored.drop_model(value, "medium", None, 9.0)
        assert stored.is_inline(new)

    def test_a_tombstone_has_nothing_to_drop(self):
        tomb = stored.tombstone(3.0)
        assert stored.drop_model(tomb, "small", None, 9.0) == (tomb, 0)


class TestTheRowFollowsTheSelection:
    def test_the_row_shows_the_selected_models_text(self):
        value = stored.with_result(
            _rec("small", "pequeno", at=1.0, inline=True),
            _rec("medium", "médio", at=2.0, inline=True))
        msg = _msg(value)
        assert stored.inline_row_text(msg, ("auto", "small")) == "pequeno"
        assert stored.inline_row_text(msg, ("auto", "medium")) == "médio"
        assert stored.inline_row_text(msg, AUTO) == "médio"

    def test_a_model_with_no_result_shows_nothing(self):
        msg = _msg(_rec("small", "pequeno", inline=True))
        assert stored.inline_row_text(msg, ("auto", "large")) == ""


class TestWhatTheDatabaseRuleStillSees:
    """The whole thing is one value with one decision time, so the rules that
    pick between copies need nothing new."""

    def test_the_later_decision_wins_with_its_models_inside(self):
        older = _rec("small", "a", at=1.0)
        newer = stored.with_result(older, _rec("medium", "b", at=2.0))
        assert stored.newer_decision(newer, older) is newer
        assert stored.newer_decision(older, newer) is newer

    def test_a_copy_without_the_key_inherits_every_models_result(self):
        value = stored.with_result(_rec("small", "a", at=1.0), _rec("medium", "b", at=2.0))
        merged = stored.with_known_transcription(
            {"messageType": "audioMessage", "key": {"id": "x"}}, _msg(value))
        assert {r["model_id"] for r in stored.results_of(merged[TRANSCRIPTION_KEY])} == {
            "small", "medium"}


class TestClearingOnCopies:
    def test_only_the_models_results_go_and_the_ids_come_back(self):
        value = stored.with_result(_rec("base", "a", at=10.0), _rec("small", "b", at=20.0))
        one = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: value}
        same = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: dict(value)}
        untouched = {"key": {"id": "M2"}, TRANSCRIPTION_KEY: _rec("base", "c")}
        plain = {"key": {"id": "M3"}}

        changed = stored.drop_model_on_copies(
            [one, same, one, untouched, plain, None, "junk"], "small", None, 30.0)

        assert changed == ["M1"]
        assert one[TRANSCRIPTION_KEY]["model_id"] == "base"
        assert same[TRANSCRIPTION_KEY]["model_id"] == "base"
        assert untouched[TRANSCRIPTION_KEY]["text"] == "c"
        assert TRANSCRIPTION_KEY not in plain

    def test_the_last_result_leaves_a_tombstone_dated_after_the_copy(self):
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "a", at=100.0)}
        stored.drop_model_on_copies([record], "base", "faster_whisper", 50.0)
        value = record[TRANSCRIPTION_KEY]
        assert value.get("deleted") is True and value["at"] > 100.0

    def test_the_other_backend_is_left_alone(self):
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "a", backend="whisper_cpp")}
        assert stored.drop_model_on_copies([record], "base", "faster_whisper", 50.0) == []
        assert record[TRANSCRIPTION_KEY]["text"] == "a"


class TestAResultStoredWhileTheClearWaits:
    """A save queued behind the clear reaches the disk after it; memory must
    keep it too, or the next sync carries a tombstone over it to the disk."""

    def test_a_new_value_dated_after_the_request_is_kept(self):
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "old", at=10.0)}
        present = stored.values_on([record])
        record[TRANSCRIPTION_KEY] = _rec("base", "new", at=60.0)
        assert stored.drop_model_on_copies([record], "base", None, 50.0, present) == []
        assert record[TRANSCRIPTION_KEY]["text"] == "new"
        assert stored.drop_all_on_copies([record], 50.0, present) == []
        assert record[TRANSCRIPTION_KEY]["text"] == "new"

    def test_a_value_that_was_there_goes_even_if_dated_ahead(self):
        # The clock ran behind: the database clears it, so memory does too.
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "a", at=100.0)}
        present = stored.values_on([record])
        assert stored.drop_model_on_copies([record], "base", None, 50.0, present) == ["M1"]
        assert record[TRANSCRIPTION_KEY].get("deleted") is True

    def test_a_new_copy_of_an_older_value_still_goes(self):
        # A sync that read the disk before the clear brings an older value in
        # a new dict: it is what the disk no longer holds.
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "a", at=10.0)}
        present = stored.values_on([record])
        record[TRANSCRIPTION_KEY] = dict(record[TRANSCRIPTION_KEY])
        assert stored.drop_all_on_copies([record], 50.0, present) == ["M1"]

    def test_values_on_skips_what_holds_nothing(self):
        holder = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: _rec("base", "a")}
        assert stored.values_on([holder, {"key": {}}, None, "junk"]) == [holder[TRANSCRIPTION_KEY]]


class TestTheWriteKeepsTheRowsOtherModels:
    def test_a_model_the_value_lacks_is_kept_from_the_row(self):
        row = stored.with_result(_rec("base", "a", at=1.0), _rec("small", "b", at=2.0))
        value = _rec("medium", "c", at=3.0)
        merged = stored.with_missing_results(value, row)
        assert {r["model_id"]: r["text"] for r in stored.results_of(merged)} == {
            "medium": "c", "small": "b", "base": "a"}
        assert merged["text"] == "c"

    def test_the_values_own_result_for_a_model_wins(self):
        row = _rec("base", "old", at=1.0)
        value = _rec("base", "new", at=3.0)
        assert stored.with_missing_results(value, row) is value

    def test_a_tombstone_on_either_side_adds_nothing(self):
        tomb = stored.tombstone(9.0)
        assert stored.with_missing_results(tomb, _rec("base", "a")) is tomb
        value = _rec("base", "a", at=10.0)
        assert stored.with_missing_results(value, tomb) is value
        assert stored.with_missing_results(value, None) is value


class TestMarkingAnOldTextInline:
    def test_it_keeps_the_date_the_text_was_made(self):
        value = _rec("base", "a", at=1000.0)
        marked = stored.marked_inline(value, value, 5000.0)
        assert stored.is_inline(marked)
        assert marked["at"] == 5000.0
        assert stored.made_time(marked) == 1000.0

    def test_a_text_already_carrying_its_date_keeps_that_one(self):
        value = _rec("base", "a", at=3000.0, made_at=1000.0)
        assert stored.made_time(stored.marked_inline(value, value, 5000.0)) == 1000.0

    def test_it_is_dated_after_the_previous_decision_whatever_the_clock(self):
        value = _rec("base", "a", at=9000.0)
        assert stored.marked_inline(value, value, 5000.0)["at"] > 9000.0

    def test_the_other_models_results_stay(self):
        previous = stored.with_result(_rec("small", "b", at=1.0), _rec("base", "a", at=2.0))
        small = next(r for r in stored.results_of(previous) if r["model_id"] == "small")
        marked = stored.marked_inline(small, previous, 10.0)
        assert marked["model_id"] == "small" and stored.is_inline(marked)
        assert {r["model_id"] for r in stored.results_of(marked)} == {"small", "base"}


class TestASyncKeepsTheRowsOtherModelsOnATie:
    """The write kept the row's other models; the next sync rewrites the
    message from the memory copy with the same decision and must keep them."""

    def test_the_same_decision_keeps_what_either_side_knows(self):
        row = stored.with_result(_rec("medium", "m", at=1.0), _rec("small", "s", at=5.0))
        memory = _rec("small", "s", at=5.0)
        written = stored.with_known_transcription(_msg(memory), _msg(row))
        assert {r["model_id"] for r in stored.results_of(written[TRANSCRIPTION_KEY])} == {
            "small", "medium"}

    def test_a_later_decision_still_wins_alone(self):
        # A clear dates its result after the one it replaced: what it dropped
        # stays dropped.
        row = stored.with_result(_rec("medium", "m", at=1.0), _rec("small", "s", at=5.0))
        newer = _rec("small", "s", at=6.0)
        written = stored.with_known_transcription(_msg(newer), _msg(row))
        assert written[TRANSCRIPTION_KEY] is newer

    def test_nothing_new_returns_the_message_itself(self):
        value = _rec("small", "s", at=5.0)
        msg = _msg(value)
        assert stored.with_known_transcription(msg, _msg(dict(value))) is msg


class TestWhatClearingSays:
    def test_each_outcome_has_its_own_sentence(self):
        assert stored.clear_cache_message_key(None) == "transcription_clear_cache_failed"
        assert stored.clear_cache_message_key(0) == "transcription_clear_cache_none"
        assert stored.clear_cache_message_key(3) == "transcription_clear_cache_done"


class TestTheCachePolicy:
    def _settings(self, **section):
        return {"transcription": section}

    def test_it_is_on_by_default_everywhere(self):
        assert stored.cache_enabled_for({}, "base") is True
        assert stored.cache_enabled_for(None, "base") is True
        assert stored.cache_enabled_for({"transcription": "junk"}, "base") is True
        assert stored.cache_enabled_for(self._settings(), "base") is True

    def test_the_general_switch_applies_to_every_model(self):
        off = self._settings(cache_enabled=False)
        assert stored.cache_enabled_for(off, "base") is False
        assert stored.cache_enabled_for(off, "small") is False

    @pytest.mark.parametrize("junk", [None, 0, "no", []])
    def test_only_a_real_false_turns_the_general_switch_off(self, junk):
        assert stored.cache_enabled_for(self._settings(cache_enabled=junk), "base") is True

    def test_a_models_own_choice_beats_the_general_switch_both_ways(self):
        off_for_one = self._settings(cache_enabled=True, cache_by_model={"base": False})
        assert stored.cache_enabled_for(off_for_one, "base") is False
        assert stored.cache_enabled_for(off_for_one, "small") is True
        on_for_one = self._settings(cache_enabled=False, cache_by_model={"base": True})
        assert stored.cache_enabled_for(on_for_one, "base") is True
        assert stored.cache_enabled_for(on_for_one, "small") is False

    def test_a_choice_that_is_not_a_bool_is_ignored(self):
        settings = self._settings(cache_enabled=False, cache_by_model={"base": "yes"})
        assert stored.cache_enabled_for(settings, "base") is False
        assert stored.cache_enabled_for(self._settings(cache_by_model="junk"), "base") is True

    def test_a_value_is_judged_by_the_model_that_made_it(self):
        settings = self._settings(cache_by_model={"base": False})
        assert stored.may_cache(settings, _rec("base", "x")) is False
        assert stored.may_cache(settings, _rec("small", "x")) is True

    def test_a_tombstone_or_junk_is_always_allowed(self):
        off = self._settings(cache_enabled=False)
        assert stored.may_cache(off, stored.tombstone(5.0)) is True
        assert stored.may_cache(off, None) is True

    def test_the_defaults_are_not_shared_with_a_caller(self):
        from core.transcription import preferences
        section = preferences.read_section({})
        section["cache_by_model"]["base"] = False
        assert preferences.DEFAULTS["cache_by_model"] == {}
        assert preferences.read_section({})["cache_by_model"] == {}


class TestClearingEverything:
    def test_every_result_goes_and_a_tombstone_is_dated_after_the_copy(self):
        value = stored.with_result(_rec("base", "a", at=100.0), _rec("small", "b", at=120.0))
        record = {"key": {"id": "M1"}, TRANSCRIPTION_KEY: value}
        other = {"key": {"id": "M2"}, TRANSCRIPTION_KEY: _rec("base", "c", at=5.0)}
        none = {"key": {"id": "M3"}}
        tomb = {"key": {"id": "M4"}, TRANSCRIPTION_KEY: stored.tombstone(7.0)}

        changed = stored.drop_all_on_copies([record, other, none, tomb, record], 50.0)

        assert changed == ["M1", "M2"]
        assert record[TRANSCRIPTION_KEY].get("deleted") is True
        assert record[TRANSCRIPTION_KEY]["at"] > 120.0
        assert other[TRANSCRIPTION_KEY].get("deleted") is True
        assert tomb[TRANSCRIPTION_KEY] == stored.tombstone(7.0)

    def test_drop_all_counts_what_went(self):
        value = stored.with_result(_rec("base", "a"), _rec("small", "b", at=20.0))
        new, count = stored.drop_all(value, 99.0)
        assert count == 2 and new == stored.tombstone(99.0)
        assert stored.drop_all(stored.tombstone(1.0), 99.0) == (stored.tombstone(1.0), 0)


class TestAVideoCarriesItsTranscription:
    def test_the_database_rule_keeps_a_videos_transcription(self):
        stored_value = _rec("base", "olá", at=50.0)
        video = {"key": {"id": "V"}, "messageType": "videoMessage",
                 "message": {"videoMessage": {"seconds": 9}}}
        assert stored.can_carry_transcription(video)
        assert stored.may_hold_transcription(video)
        merged = stored.with_known_transcription(video, dict(video, **{TRANSCRIPTION_KEY: stored_value}))
        assert merged[TRANSCRIPTION_KEY] == stored_value

    def test_a_video_shows_its_inline_text(self):
        video = {"messageType": "videoMessage",
                 TRANSCRIPTION_KEY: _rec("base", "olá", inline=True)}
        assert stored.inline_row_text(video) == "olá"


class TestARecordFromBeforePerModel:
    def test_one_that_names_no_model_is_offered_under_any_selection(self):
        legacy = {"text": "antigo", "at": 5.0, "language": "pt"}
        msg = _msg(legacy)
        assert stored.saved_transcription(msg, ("faster_whisper", "small"))["text"] == "antigo"
        assert stored.saved_transcription(msg, AUTO)["text"] == "antigo"
