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


class _Stub:
    _MAX_FORWARDED_DURATIONS = MainWindow._MAX_FORWARDED_DURATIONS
    media_kind_of = staticmethod(MainWindow.media_kind_of)
    media_duration_of = staticmethod(MainWindow.media_duration_of)
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _expect_forwarded_duration = MainWindow._expect_forwarded_duration
    _forget_forwarded_duration = MainWindow._forget_forwarded_duration
    apply_forwarded_duration = MainWindow.apply_forwarded_duration


CHAT = "120363000000000001@g.us"


def _echo(kind="audioMessage", jid=CHAT, from_me=True, seconds=None):
    """The copy as it arrives over the socket: no duration on it at all."""
    body = {} if seconds is None else {"seconds": seconds}
    return {"key": {"id": "3EB0NEW", "remoteJid": jid, "fromMe": from_me},
            "messageType": kind, "message": {kind: body}}


class TestGraftingTheDurationOntoTheEcho:
    def test_the_reported_bug_end_to_end(self):
        """Forward a 67-second voice message; its copy arrives with no
        duration and must come out reading 67 again."""
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        echo = _echo()
        assert mw.apply_forwarded_duration(echo) is True
        assert echo["message"]["audioMessage"]["seconds"] == 67

    def test_it_works_for_video_too(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _video(seconds=42))

        echo = _echo(kind="videoMessage")
        assert mw.apply_forwarded_duration(echo) is True
        assert echo["message"]["videoMessage"]["seconds"] == 42

    def test_a_sub_second_note_carries_its_zero_across(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=0))

        echo = _echo()
        assert mw.apply_forwarded_duration(echo) is True
        assert echo["message"]["audioMessage"]["seconds"] == 0

    def test_the_expectation_is_recorded_before_any_response_exists(self):
        """The whole point of the rewrite: nothing about the HTTP answer is
        needed, because the echo routinely arrives first."""
        mw = _Stub()
        token = mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        assert token == (CHAT, "audioMessage")
        assert mw._forwarded_media_seconds[token] == [67]

    def test_a_duration_that_did_arrive_is_never_overwritten(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        echo = _echo(seconds=12)
        assert mw.apply_forwarded_duration(echo) is False
        assert echo["message"]["audioMessage"]["seconds"] == 12

    def test_another_chat_is_untouched(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        echo = _echo(jid="5511999999999@s.whatsapp.net")
        assert mw.apply_forwarded_duration(echo) is False

    def test_another_kind_of_media_is_untouched(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        assert mw.apply_forwarded_duration(_echo(kind="videoMessage")) is False

    def test_someone_elses_message_is_untouched(self):
        """Only our own forwards are being waited on; an incoming audio from
        the other side must never inherit a length we put aside."""
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))

        assert mw.apply_forwarded_duration(_echo(from_me=False)) is False

    def test_each_expectation_is_consumed_once(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))
        mw.apply_forwarded_duration(_echo())

        assert mw.apply_forwarded_duration(_echo()) is False

    def test_two_forwards_to_the_same_chat_keep_their_order(self):
        """Queued, not overwritten: forwarding a 67s then a 12s audio to the
        same chat must not swap their lengths."""
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))
        mw._expect_forwarded_duration(CHAT, _audio(seconds=12))

        first, second = _echo(), _echo()
        mw.apply_forwarded_duration(first)
        mw.apply_forwarded_duration(second)

        assert first["message"]["audioMessage"]["seconds"] == 67
        assert second["message"]["audioMessage"]["seconds"] == 12

    def test_forwarding_text_records_nothing(self):
        mw = _Stub()
        assert mw._expect_forwarded_duration(CHAT, {"message": {"conversation": "oi"}}) is None
        assert mw.apply_forwarded_duration(_echo()) is False

    def test_a_media_without_a_known_length_records_nothing(self):
        mw = _Stub()
        assert mw._expect_forwarded_duration(CHAT, _echo()) is None

    def test_a_failed_forward_drops_its_expectation(self):
        """Otherwise the next media message in that chat would inherit the
        length of something that was never delivered."""
        mw = _Stub()
        token = mw._expect_forwarded_duration(CHAT, _audio(seconds=67))
        mw._forget_forwarded_duration(token)

        assert mw.apply_forwarded_duration(_echo()) is False

    def test_forgetting_removes_only_the_last_expectation(self):
        mw = _Stub()
        mw._expect_forwarded_duration(CHAT, _audio(seconds=67))
        token = mw._expect_forwarded_duration(CHAT, _audio(seconds=12))
        mw._forget_forwarded_duration(token)

        echo = _echo()
        assert mw.apply_forwarded_duration(echo) is True
        assert echo["message"]["audioMessage"]["seconds"] == 67

    def test_forgetting_nothing_is_safe(self):
        mw = _Stub()
        mw._forget_forwarded_duration(None)          # forward of a text message
        assert mw.apply_forwarded_duration(_echo()) is False

    def test_applying_with_nothing_recorded_is_safe(self):
        assert _Stub().apply_forwarded_duration(_echo()) is False

    def test_the_store_stays_bounded(self):
        """An echo that never arrives must not pin memory for the session."""
        mw = _Stub()
        for i in range(MainWindow._MAX_FORWARDED_DURATIONS * 2):
            mw._expect_forwarded_duration(f"{i}@g.us", _audio(seconds=30))

        total = sum(len(q) for q in mw._forwarded_media_seconds.values())
        assert total <= MainWindow._MAX_FORWARDED_DURATIONS


class TestReadingTheMediaKind:
    def test_audio(self):
        assert MainWindow.media_kind_of(_audio()) == "audioMessage"

    def test_video(self):
        assert MainWindow.media_kind_of(_video()) == "videoMessage"

    @pytest.mark.parametrize("msg", [None, {}, {"message": {}}, {"message": {"conversation": "oi"}}])
    def test_anything_else_has_no_kind(self, msg):
        assert MainWindow.media_kind_of(msg) is None


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


class TestTheWiringInsideForwardMessage:
    """The half that failed in real use.

    The first attempt registered the duration from the forward's HTTP
    response — and the socket echo arrived first, so the copy was already
    stored without a duration by the time the answer came back. Nothing in
    the tests noticed, because they exercised the helpers directly. These
    read the source of forward_message() itself: driving it whole would need
    a live WhatsApp session.
    """

    @staticmethod
    def _source():
        import inspect
        return inspect.getsource(MainWindow.forward_message)

    def test_the_expectation_is_registered_at_all(self):
        assert "_expect_forwarded_duration(" in self._source()

    def test_it_is_registered_before_the_request_goes_out(self):
        src = self._source()
        registered = src.index("_expect_forwarded_duration(")
        # api_post() since the call sites moved behind core/api_client.py —
        # same call, one door, with correlation id and a redacted log line.
        requested = src.index("api_post(")
        assert registered < requested, (
            "the duration is put aside only after the forward request — the "
            "socket echo beats the HTTP answer back, so the copy gets stored "
            "before the length is known (this is exactly how issue #43's "
            "first fix failed)"
        )

    def test_a_failed_forward_gives_the_expectation_back(self):
        """A non-2xx answer and a raised exception both fall through to the
        same forget-call once the retry loop gives up on both attempts — the
        next media message in that chat must not inherit a length from
        something that never arrived."""
        src = self._source()
        assert "_forget_forwarded_duration(" in src
        # Must fire only after retries are exhausted, not on every attempt —
        # forgetting mid-retry would drop the expectation before the retry
        # even had a chance to succeed.
        assert src.rindex("_forget_forwarded_duration(") > src.rindex("time.sleep(")

    def test_the_echo_path_applies_it(self):
        import inspect

        assert "self.apply_forwarded_duration(msg)" in inspect.getsource(MainWindow.on_new_message)
