"""Tests for a video whose message never stated its duration.

Reported live: a video that plays for minutes was announced as
"vídeo, duração: 0 segundos". Checked against the running WPPConnect server
(GET /get-messages for that chat): WhatsApp Web itself hands the message over
with `duration` set to the string "0", and neither the payload nor its
mediaData carries the real length anywhere else — the sending client simply
left the field out. Two other videos in the same chat came through with
duration "29" and rendered fine, so this is per-message, not a broken parse.

Nothing can invent the length from the message alone, so:

* video_seconds() treats a stated 0 as "not stated" and the row renders as a
  bare "vídeo" — no video lasts no time, and saying so was the actual
  complaint. Audio deliberately keeps the opposite rule: a voice note under a
  second really does report 0 and WhatsApp shows "0:00" for it.
* _learn_video_duration() fills the gap from the decoded file the moment the
  video is played (BASS opens the .mp4 directly, so _probe_audio_duration()
  covers it), persists it, and repaints just that row.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the methods under test are bound to a small stub — same approach as
tests/test_get_message_content_caption.py.
"""

import pytest

import ui.conversations as conversations
from core.utils import MEASURED_SECONDS_KEY
from ui.conversations import ConversationsPanel, video_seconds


@pytest.fixture(autouse=True)
def _immediate_callafter(monkeypatch):
    """_learn_video_duration() runs on the playback worker and bounces the
    repaint to the UI thread; there is no wx.App here to bounce it to."""
    monkeypatch.setattr(conversations.wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


class _FakeI18n:
    _STRINGS = {
        "video": "Vídeo",
        "sticker": "Figurinha",
        "duration": "duração",
        "second": "segundo", "seconds": "segundos",
        "minute": "minuto", "minutes": "minutos",
        "hour": "hora", "hours": "horas",
        "and": "e",
        "decimal_separator": ".",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.saves = []

    def _schedule_save(self, dirty_jid=None):
        self.saves.append(dirty_jid)


class _Stub:
    _get_message_content = ConversationsPanel._get_message_content
    _format_duration = ConversationsPanel._format_duration
    _format_filesize = ConversationsPanel._format_filesize
    _learn_video_duration = ConversationsPanel._learn_video_duration

    def __init__(self, probed=None):
        self.main_window = _FakeMainWindow()
        self._download_progress = {}
        self.conversation = {"remoteJid": "grupo@g.us"}
        self._probed = probed
        self.persisted = []
        self.repainted = []

    def _probe_audio_duration(self, path):
        return self._probed

    def _persist_message_local_flag(self, jid, msg):
        self.persisted.append((jid, msg.get("key", {}).get("id", "")))

    def _repaint_message_rows(self, msg_ids):
        self.repainted.append(sorted(i for i in msg_ids if i))
        return True


def _video(**inner):
    body = {"caption": "", "gifPlayback": False, "mimetype": "video/mp4"}
    body.update(inner)
    return {
        "messageType": "videoMessage",
        "message": {"videoMessage": body},
        "key": {"id": "VID1"},
    }


class TestVideoSeconds:
    @pytest.mark.parametrize("raw", [0, "0", 0.0, "0.0"])
    def test_a_stated_zero_means_not_stated(self, raw):
        assert video_seconds({"seconds": raw}) is None

    @pytest.mark.parametrize("raw", [None, "", "abc", {}, []])
    def test_missing_or_unparseable_is_not_stated(self, raw):
        assert video_seconds({"seconds": raw}) is None

    def test_an_absent_field_is_not_stated(self):
        assert video_seconds({}) is None

    def test_a_negative_length_is_not_stated(self):
        assert video_seconds({"seconds": -3}) is None

    @pytest.mark.parametrize("raw,expected", [(29, 29), ("29", 29), (29.7, 29)])
    def test_a_real_length_survives_either_type(self, raw, expected):
        """WebSocketClient._media_seconds() casts to int, but a record
        restored straight from a REST sync can still carry the string."""
        assert video_seconds({"seconds": raw}) == expected

    def test_a_non_dict_is_tolerated(self):
        assert video_seconds(None) is None
        assert video_seconds("videoMessage") is None


class TestRendering:
    def test_a_video_with_no_stated_duration_omits_the_clause(self):
        text = _Stub()._get_message_content(_video(seconds=0))
        assert text == "Vídeo"
        assert "0 segundos" not in text

    def test_a_video_with_a_real_duration_still_states_it(self):
        text = _Stub()._get_message_content(_video(seconds=29))
        assert text == "Vídeo, duração: 29 segundos"

    def test_the_caption_survives_a_missing_duration(self):
        text = _Stub()._get_message_content(_video(seconds=0, caption="olha isso"))
        assert text == "Vídeo, olha isso"


class TestLearningTheDurationFromTheFile:
    def test_a_probed_length_is_written_back_persisted_and_repainted(self):
        stub = _Stub(probed=137)
        msg = _video(seconds=0)

        stub._learn_video_duration(msg, "algum.mp4")

        assert msg["message"]["videoMessage"][MEASURED_SECONDS_KEY] == 137
        assert msg["message"]["videoMessage"]["seconds"] == 0, (
            "the message's own field is the server's; the measurement gets its own key"
        )
        assert stub.persisted == [("grupo@g.us", "VID1")]
        assert stub.main_window.saves == ["grupo@g.us"]
        assert stub.repainted == [["VID1"]]
        assert stub._get_message_content(msg) == "Vídeo, duração: 2 minutos e 17 segundos"

    def test_a_video_that_already_states_its_length_is_left_alone(self):
        """Probing would cost a BASS stream open per playback, and the
        message's own answer is the authoritative one when it has one."""
        stub = _Stub(probed=999)
        msg = _video(seconds=29)

        stub._learn_video_duration(msg, "algum.mp4")

        assert msg["message"]["videoMessage"]["seconds"] == 29
        assert MEASURED_SECONDS_KEY not in msg["message"]["videoMessage"]
        assert stub.persisted == []
        assert stub.repainted == []

    @pytest.mark.parametrize("probed", [None, -1])
    def test_a_probe_that_answers_nothing_changes_nothing(self, probed):
        stub = _Stub(probed=probed)
        msg = _video(seconds=0)

        stub._learn_video_duration(msg, "algum.mp4")

        assert MEASURED_SECONDS_KEY not in msg["message"]["videoMessage"]
        assert stub.persisted == []
        assert stub.repainted == []

    def test_a_file_measured_at_zero_is_recorded_as_a_real_zero(self):
        """The distinction the message alone cannot make: a stated 0 means the
        sender omitted the field, a MEASURED 0 means the clip really is under
        a second — and only the second one is worth announcing."""
        stub = _Stub(probed=0)
        msg = _video(seconds=0)

        stub._learn_video_duration(msg, "algum.mp4")

        assert msg["message"]["videoMessage"][MEASURED_SECONDS_KEY] == 0
        assert stub.persisted == [("grupo@g.us", "VID1")]
        assert stub._get_message_content(msg) == "Vídeo, duração: 0 segundos"

    def test_a_non_video_message_is_ignored(self):
        stub = _Stub(probed=42)
        msg = {"messageType": "audioMessage",
               "message": {"audioMessage": {"seconds": 0}},
               "key": {"id": "AUD1"}}

        stub._learn_video_duration(msg, "algum.mp4")

        assert msg["message"]["audioMessage"]["seconds"] == 0
        assert stub.persisted == []

    def test_no_open_conversation_still_repaints_without_persisting(self):
        stub = _Stub(probed=50)
        stub.conversation = None
        msg = _video(seconds=0)

        stub._learn_video_duration(msg, "algum.mp4")

        assert msg["message"]["videoMessage"][MEASURED_SECONDS_KEY] == 50
        assert stub.persisted == []
        assert stub.repainted == [["VID1"]]


class TestAudioKeepsTheOppositeRule:
    def test_a_zero_second_voice_note_still_states_its_length(self):
        """WhatsApp shows "0:00" for a sub-second voice note — that 0 is a
        real answer, unlike a video's."""
        stub = _Stub()
        msg = {"messageType": "audioMessage",
               "message": {"audioMessage": {"seconds": 0}},
               "key": {"id": "AUD1"}}

        assert "0 segundos" in stub._get_message_content(msg)


class TestStatedZeroVersusMeasuredZero:
    """The guard the audio path always had, now available to video.

    Audio never needed it: a voice note under a second reports its own 0 and
    that is the truth. A video's 0 is ambiguous — WhatsApp Web writes it both
    for "the clip is that short" and for "the sender's client omitted the
    field" — so the two are separated by WHERE the number came from. The
    message's own field is only believed above zero; the value WinZapp read
    off the file is believed at any value, including 0.
    """

    def test_a_stated_zero_is_still_no_answer(self):
        assert video_seconds({"seconds": 0}) is None

    def test_a_measured_zero_is_an_answer(self):
        assert video_seconds({"seconds": 0, MEASURED_SECONDS_KEY: 0}) == 0

    def test_the_measurement_outranks_a_stated_length(self):
        """Both are about the same immutable file, and the measurement read
        it directly — a mismatch means the sender's metadata was wrong."""
        assert video_seconds({"seconds": 30, MEASURED_SECONDS_KEY: 422}) == 422

    @pytest.mark.parametrize("raw,expected", [(0, 0), ("0", 0), (7, 7), ("7", 7), (7.9, 7)])
    def test_a_measurement_is_read_in_any_shape_it_is_stored(self, raw, expected):
        assert video_seconds({"seconds": 0, MEASURED_SECONDS_KEY: raw}) == expected

    @pytest.mark.parametrize("junk", [None, "", "abc", -1])
    def test_junk_in_the_measurement_falls_back_to_the_stated_value(self, junk):
        assert video_seconds({"seconds": 30, MEASURED_SECONDS_KEY: junk}) == 30
        assert video_seconds({"seconds": 0, MEASURED_SECONDS_KEY: junk}) is None

    def test_a_measured_zero_renders_as_zero_seconds(self):
        stub = _Stub()
        msg = _video(seconds=0)
        msg["message"]["videoMessage"][MEASURED_SECONDS_KEY] = 0

        assert stub._get_message_content(msg) == "Vídeo, duração: 0 segundos"


class TestOwnVideoAttachmentGetsAMeasuredDuration:
    """Reported live: a video sent as a WinZapp attachment (not received)
    showed no duration in the message list at all, until the sender opened
    it themselves at least once. _on_send_attachment() already probed audio
    attachments and stored the result under "seconds" (video_seconds()
    trusts that key above zero only), but had no equivalent branch for
    video, which needs _measured_seconds instead — a stated 0 there is
    trusted, matching what _learn_video_duration() already does for a
    received video the moment it's played.

    ConversationsPanel._on_send_attachment() has too many UI/threading side
    effects to instantiate here (message_queue, messages_list, background
    caching thread, ...) — this pins the source-level contract instead, same
    approach ui/test_media_viewer_wiring.py already uses for this class of
    regression.
    """

    def _send_attachment_source(self):
        import ast
        tree = ast.parse(_source_conversations())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_on_send_attachment":
                return ast.get_source_segment(_source_conversations(), node)
        raise AssertionError("_on_send_attachment not found")

    def test_video_attachments_are_probed_into_measured_seconds(self):
        src = self._send_attachment_source()
        assert 'media_type == "video"' in src
        assert "MEASURED_SECONDS_KEY" in src
        assert "_probe_audio_duration(path)" in src


def _source_conversations():
    import pathlib
    return (pathlib.Path(__file__).resolve().parents[1] / "client" / "ui" / "conversations.py").read_text(encoding="utf-8")


class TestProbeTellsShortFromUnreadable:
    """probe_media_duration() is what makes the distinction possible, so it
    has to answer 0 for a real sub-second file and None when it cannot read
    one — proven against files written here, not mocks."""

    def _wav(self, tmp_path, seconds, rate=8000):
        import wave
        path = tmp_path / f"clip_{seconds}.wav"
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(b"\x00\x00" * int(rate * seconds))
        return str(path)

    def test_a_sub_second_clip_measures_zero(self, tmp_path):
        assert conversations.probe_media_duration(self._wav(tmp_path, 0.4)) == 0

    def test_a_normal_clip_measures_its_length(self, tmp_path):
        assert conversations.probe_media_duration(self._wav(tmp_path, 2)) == 2

    def test_an_empty_file_cannot_be_measured(self, tmp_path):
        path = tmp_path / "vazio.wav"
        path.write_bytes(b"")
        assert conversations.probe_media_duration(str(path)) is None

    def test_a_missing_file_cannot_be_measured(self, tmp_path):
        assert conversations.probe_media_duration(str(tmp_path / "nao_existe.wav")) is None

    def test_probes_with_the_same_stream_mode_playback_uses(self):
        """Reported live: a video's duration in the message list drifted a
        second or two from what the player itself showed for the exact same
        file. Both VideoPlayer._start_audio() and ConversationsPanel.
        _play_audio()'s _open_stream() already open the file with
        decode=True (needed for Tempo/speed control) — probe_media_duration()
        used to open a plain (decode=False) stream just to read its length,
        which BASS can report a slightly different get_length() for on the
        same AAC/MP4 file. Opening the probe the same way playback does is
        what makes the two numbers agree."""
        assert "stream.FileStream(file=path, decode=True)" in _source_conversations()
