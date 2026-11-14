"""Issue #469, the pure part: which selected messages a bulk transcription runs,
skips or reuses, and the combined text of the window. No wx."""

from core.transcription import bulk
from core.transcription import stored as stored_transcription

KEY = stored_transcription.TRANSCRIPTION_KEY


def _voice(mid, **extra):
    msg = {"key": {"id": mid}, "messageType": "audioMessage",
           "message": {"audioMessage": {"seconds": 5}}, "messageTimestamp": 1_700_000_000}
    msg.update(extra)
    return msg


def _text(mid):
    return {"key": {"id": mid}, "messageType": "conversation", "message": {"conversation": "oi"}}


def _video(mid, gif=False):
    return {"key": {"id": mid}, "messageType": "videoMessage",
            "message": {"videoMessage": {"seconds": 9, **({"gifPlayback": True} if gif else {})}}}


SEP = {"_type": "unread_separator"}


def _is_sep(msg):
    return msg.get("_type") == "unread_separator"


class TestThePlan:
    def test_only_the_selected_ones_in_conversation_order(self):
        messages = [_voice("a"), _text("b"), SEP, _video("c"), _voice("d"), _video("e", gif=True)]
        plan = bulk.plan(messages, {"d", "a", "b", "c", "e"}, None, _is_sep)
        assert [m["key"]["id"] for m in plan.to_run] == ["a", "c", "d"]
        assert plan.skipped == 2  # the text and the GIF
        assert plan.already == () and plan.total == 3

    def test_unselected_messages_are_not_touched(self):
        plan = bulk.plan([_voice("a"), _voice("b")], {"b"}, None, _is_sep)
        assert [m["key"]["id"] for m in plan.to_run] == ["b"]

    def test_a_transcription_of_the_selected_model_is_reused(self):
        saved = {"text": "oi", "model_id": "small", "backend": "faster_whisper", "at": 1.0}
        other = {"text": "olá", "model_id": "base", "backend": "faster_whisper", "at": 1.0}
        messages = [_voice("a", **{KEY: saved}), _voice("b", **{KEY: other})]
        plan = bulk.plan(messages, {"a", "b"}, ("faster_whisper", "small"), _is_sep)
        assert [m["key"]["id"] for m in plan.already] == ["a"]
        assert [m["key"]["id"] for m in plan.to_run] == ["b"]

    def test_a_deleted_one_is_run_again(self):
        messages = [_voice("a", **{KEY: stored_transcription.tombstone(5.0)})]
        plan = bulk.plan(messages, {"a"}, None, _is_sep)
        assert len(plan.to_run) == 1

    def test_nothing_selected_or_junk_is_an_empty_plan(self):
        assert bulk.plan([_voice("a")], set(), None, _is_sep).total == 0
        assert bulk.plan([None, "x", _voice("a")], {"a"}, None).total == 1
        assert bulk.plan(None, {"a"}).total == 0


class TestTheCombinedText:
    def test_each_one_with_sender_date_and_time_oldest_first(self):
        a, b = _voice("a"), _voice("b")
        text = bulk.combined_text(
            [(a, "primeira"), (b, ""), (b, "segunda")],
            lambda m: "Ana" if m is a else "Bia",
            lambda m: 1_700_000_000,
            "%d/%m/%Y %H:%M",
        )
        blocks = text.split("\n\n")
        assert len(blocks) == 2
        assert blocks[0].endswith(" - Ana: primeira")
        assert blocks[1].endswith(" - Bia: segunda")

    def test_without_a_timestamp_only_the_sender(self):
        assert bulk.combined_text([({}, "x")], lambda m: "Ana", lambda m: None, "%H") == "Ana: x"
