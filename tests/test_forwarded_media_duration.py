"""Tests for issue #43 — forwarded media showing a duration of 0.

Reported and reproduced: forward a voice message, audio file or video to
another chat, open that chat, and the forwarded copy reads "0 segundos" —
while playing it works normally, and a full resync later replaces it with the
real length.

That last part is the diagnosis. WhatsApp's own forward happens server-side
(WPP.chat.forwardMessagesV2), so the copy in the destination chat reaches
WinZapp as a plain live message over the socket, and that live payload
carries no duration. The value on the server is right all along; only the
locally stored/rendered copy is wrong, until some later sync overwrites it.

Fixed from both ends:

* the length is taken from the source message (which is in memory, correct,
  at the moment of forwarding) and grafted onto the copy when its echo
  arrives, keyed by the id the forward API reports;
* "we were never told" stops being written down as 0. A voice note under a
  second really does report 0 — WhatsApp shows "0:00" for those — so the two
  answers are kept apart: the normalizer leaves the field absent when the
  payload stated nothing, and only an absent value omits the duration clause.
  That second half also covers any media whose echo the id matching misses.

MainWindow/ConversationsPanel are wx classes and cannot be instantiated
without a running wx.App, so the methods under test run against stubs — same
approach as tests/test_message_bookmarks.py.
"""

import pytest

from main import MainWindow
from ui.conversations import ConversationsPanel


def _audio(msg_id="ABC", seconds=67):
    return {
        "key": {"id": msg_id, "fromMe": True},
        "messageType": "audioMessage",
        "message": {"audioMessage": {"seconds": seconds, "ptt": True}},
    }


def _video(msg_id="VID", seconds=42):
    return {
        "key": {"id": msg_id, "fromMe": True},
        "messageType": "videoMessage",
        "message": {"videoMessage": {"seconds": seconds}},
    }


class TestReadingTheSourceDuration:
    def test_reads_an_audio_length(self):
        assert MainWindow.media_duration_of(_audio(seconds=67)) == 67

    def test_reads_a_video_length(self):
        assert MainWindow.media_duration_of(_video(seconds=42)) == 42

    @pytest.mark.parametrize("msg", [
        {},
        None,
        {"message": {}},
        {"message": {"conversation": "oi"}},
        {"message": {"audioMessage": {}}},
        {"message": {"audioMessage": {"seconds": None}}},
        {"message": {"audioMessage": {"seconds": ""}}},
        {"message": {"audioMessage": {"seconds": "abc"}}},
    ])
    def test_unknown_length_is_none(self, msg):
        assert MainWindow.media_duration_of(msg) is None

    def test_a_sub_second_voice_note_reports_a_real_zero(self):
        """Those very quick voice notes: 0 is the length, not a missing
        value, and it has to survive the forward like any other."""
        assert MainWindow.media_duration_of(_audio(seconds=0)) == 0


class TestReadingTheForwardResponse:
    """forwardMessagesV2 is typed Array<any>, so the id turns up in more than
    one shape — and anything unrecognised must simply teach us nothing."""

    def test_serialized_string_id(self):
        body = {"response": [{"id": "true_120363000000000001@g.us_3EB0ABC"}]}
        assert MainWindow.forwarded_message_ids(body) == ["3EB0ABC"]

    def test_nested_serialized_id(self):
        body = {"response": [{"id": {"_serialized": "true_5511999999999@c.us_3EB0XYZ"}}]}
        assert MainWindow.forwarded_message_ids(body) == ["3EB0XYZ"]

    def test_bare_string_items(self):
        body = {"response": ["true_5511999999999@c.us_AAA", "true_5511999999999@c.us_BBB"]}
        assert MainWindow.forwarded_message_ids(body) == ["AAA", "BBB"]

    def test_a_single_object_is_accepted(self):
        assert MainWindow.forwarded_message_ids({"id": "false_x@c.us_ZZZ"}) == ["ZZZ"]

    def test_a_bare_id_without_prefixes(self):
        assert MainWindow.forwarded_message_ids({"response": ["3EB0PLAIN"]}) == ["3EB0PLAIN"]

    @pytest.mark.parametrize("body", [None, "", 42, {}, {"response": None}, {"response": [{}]},
                                      {"response": [{"id": ""}]}])
    def test_unreadable_shapes_yield_nothing(self, body):
        assert MainWindow.forwarded_message_ids(body) == []


class _Stub:
    _MAX_FORWARDED_DURATIONS = MainWindow._MAX_FORWARDED_DURATIONS
    media_duration_of = staticmethod(MainWindow.media_duration_of)
    forwarded_message_ids = staticmethod(MainWindow.forwarded_message_ids)
    _remember_forwarded_duration = MainWindow._remember_forwarded_duration
    apply_forwarded_duration = MainWindow.apply_forwarded_duration


def _response(msg_id):
    return {"status": "success", "response": [{"id": f"true_120363000000000001@g.us_{msg_id}"}]}


class TestGraftingTheDurationOntoTheEcho:
    def test_the_reported_bug_end_to_end(self):
        """Forward a 67-second voice message; its echo arrives with no
        duration and must come out reading 67 again."""
        mw = _Stub()
        mw._remember_forwarded_duration(_response("3EB0NEW"), mw.media_duration_of(_audio(seconds=67)))

        echo = {"key": {"id": "3EB0NEW", "fromMe": True},
                "messageType": "audioMessage",
                "message": {"audioMessage": {"seconds": 0, "ptt": True}}}
        applied = mw.apply_forwarded_duration(echo)

        assert applied is True
        assert echo["message"]["audioMessage"]["seconds"] == 67

    def test_it_works_for_video_too(self):
        mw = _Stub()
        mw._remember_forwarded_duration(_response("VID1"), mw.media_duration_of(_video(seconds=42)))

        echo = {"key": {"id": "VID1"}, "message": {"videoMessage": {"seconds": 0}}}

        assert mw.apply_forwarded_duration(echo) is True
        assert echo["message"]["videoMessage"]["seconds"] == 42

    def test_a_duration_that_did_arrive_is_never_overwritten(self):
        """If the echo does carry a length, it is the authoritative one."""
        mw = _Stub()
        mw._remember_forwarded_duration(_response("X1"), 67)

        echo = {"key": {"id": "X1"}, "message": {"audioMessage": {"seconds": 12}}}

        assert mw.apply_forwarded_duration(echo) is False
        assert echo["message"]["audioMessage"]["seconds"] == 12

    def test_an_unrelated_message_is_untouched(self):
        mw = _Stub()
        mw._remember_forwarded_duration(_response("X1"), 67)

        other = {"key": {"id": "SOMETHING_ELSE"}, "message": {"audioMessage": {"seconds": 0}}}

        assert mw.apply_forwarded_duration(other) is False
        assert other["message"]["audioMessage"]["seconds"] == 0

    def test_each_forward_is_consumed_once(self):
        """The echo arrives once; keeping the entry would let a later message
        that happens to reuse the id inherit a stale length."""
        mw = _Stub()
        mw._remember_forwarded_duration(_response("X1"), 67)
        echo = {"key": {"id": "X1"}, "message": {"audioMessage": {"seconds": 0}}}
        mw.apply_forwarded_duration(echo)

        again = {"key": {"id": "X1"}, "message": {"audioMessage": {"seconds": 0}}}
        assert mw.apply_forwarded_duration(again) is False

    def test_forwarding_text_records_nothing(self):
        mw = _Stub()
        mw._remember_forwarded_duration(_response("T1"), mw.media_duration_of(
            {"message": {"conversation": "oi"}}))

        echo = {"key": {"id": "T1"}, "message": {"audioMessage": {"seconds": 0}}}
        assert mw.apply_forwarded_duration(echo) is False

    def test_applying_with_nothing_recorded_is_safe(self):
        mw = _Stub()
        assert mw.apply_forwarded_duration({"key": {"id": "X"}, "message": {}}) is False

    def test_the_store_stays_bounded(self):
        """An echo that never arrives must not pin memory for the session."""
        mw = _Stub()
        for i in range(MainWindow._MAX_FORWARDED_DURATIONS * 2):
            mw._remember_forwarded_duration(_response(f"ID{i}"), 30)

        assert len(mw._forwarded_media_seconds) <= MainWindow._MAX_FORWARDED_DURATIONS


class _FakeI18n:
    _STRINGS = {
        "message_type_audio": "áudio", "duration": "duração", "video": "vídeo",
        "second": "segundo", "seconds": "segundos", "minute": "minuto",
        "minutes": "minutos", "hour": "hora", "hours": "horas", "and": "e",
        "sticker": "figurinha",
    }

    def t(self, key):
        return self._STRINGS[key]


class _Panel:
    _format_duration = ConversationsPanel._format_duration

    def __init__(self):
        self.main_window = type("MW", (), {"i18n": _FakeI18n()})()


class TestUnknownAndZeroAreDifferentAnswers:
    def test_zero_is_a_real_length(self):
        """A voice note shorter than a second — WhatsApp shows "0:00"; the
        duration must be stated, not swallowed."""
        assert _Panel()._format_duration(0) == "0 segundos"

    def test_none_is_unknown_and_omits_the_clause(self):
        assert _Panel()._format_duration(None) == ""

    def test_negative_formats_as_unknown(self):
        assert _Panel()._format_duration(-5) == ""

    def test_a_real_length_still_formats(self):
        assert _Panel()._format_duration(67) == "1 minuto e 7 segundos"

    def test_one_second_is_not_swallowed(self):
        """The boundary the change must not cross: 1 is a real length."""
        assert _Panel()._format_duration(1) == "1 segundo"

    @pytest.mark.parametrize("value", [None, "", "abc", [], {}])
    def test_unusable_values_stay_unknown(self, value):
        assert _Panel()._format_duration(value) == ""


class TestTheNormalizerKeepsTheTwoAnswersApart:
    """core.websocket_client._media_seconds — where the distinction is made.

    It used to write 0 whenever it could not find a duration, which is what
    turned "nobody told us" into a stated length of zero. Now an absent value
    stays absent, and a stated 0 stays 0.
    """

    reads = staticmethod(__import__("core.websocket_client", fromlist=["_media_seconds"])._media_seconds)

    @pytest.mark.parametrize("payload,expected", [
        ({"duration": 67}, 67),
        ({"duration": "67"}, 67),
        ({"duration": 67.9}, 67),
        ({"seconds": 42}, 42),
        ({"mediaData": {"duration": 15}}, 15),
    ])
    def test_a_stated_length_is_read(self, payload, expected):
        assert self.reads(payload) == expected

    @pytest.mark.parametrize("payload", [
        {"duration": 0},
        {"seconds": 0},
        {"mediaData": {"duration": 0}},
    ])
    def test_a_stated_zero_survives_as_zero(self, payload):
        """The sub-second voice note. Before, `or` treated this exactly like
        a missing field and it came out as 0-meaning-unknown."""
        assert self.reads(payload) == 0

    @pytest.mark.parametrize("payload", [
        {},
        {"duration": None},
        {"duration": ""},
        {"duration": "abc"},
        {"mediaData": "not a dict"},
    ])
    def test_a_missing_or_unusable_length_is_none(self, payload):
        assert self.reads(payload) is None

    def test_the_forwarded_echo_shape_yields_none(self):
        """Issue #43's payload: a media message with no duration anywhere."""
        assert self.reads({"clientUrl": "https://x", "mimetype": "audio/ogg"}) is None
