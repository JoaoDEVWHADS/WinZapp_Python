"""Getting at a message's audio without inventing anything about it.

Everything this file pins is a failure the user cannot see happening:

* **A refusal in the wrong words, and a refusal that should not happen at
  all.** Both halves of the sniffer are pinned here because both fail quietly.
  Raw PCM — what a voice note recorded in WinZapp leaves in its `.msv` when the
  OGG encode fails — has to stay refused: measured against the bundled ffmpeg
  with `audio_prep`'s own arguments it is refused whatever extension it is
  given, but in words that vary with the samples as much as with the
  extension — a damaged recording for one, the generic FFMPEG_FAILED for
  another. Sniffing first is what makes it UNSUPPORTED_AUDIO_FORMAT, the one
  sentence of the three they can act on. That includes PCM whose first sample
  happens to spell an MP3 or ADTS frame header, which is why a bare frame
  stream has to show a second header where the first says it will be. And
  the other way round: every signature the table gained was confirmed to convert
  through that same command, because a format ffmpeg opens being refused here
  means "this format was not recognised" spoken over a file that plays fine in
  the conversation.

* **The wrong id rule, silently missing every file.** Two id rules coexist in
  this repository, and a transcription follows the media downloader's, not
  `local_media_cache_paths()`'s. A regression there does not raise — it simply
  reports "not downloaded yet" for a message whose audio is on disk.

* **A decrypted private recording left in %TEMP%.** The temporary holds the
  audio in clear, so every path out of `decrypt_to_temp()` is counted, not just
  the failing ones.

* **The log naming the message.** The file on disk is named after the message
  id, so a log line carrying the path identifies the conversation. The scan
  here is the one `tests/test_transcription_backend.py` runs over part 3 —
  and, because this module logs nothing itself, what actually reaches the log
  from here is the `detail` of the errors it raises, which is pinned too.
"""

import ast
import errno
import math
import os
import random
import re
import struct
import traceback

from tests.locales import load_strings, registered_locale_codes
import pytest

from core.transcription import errors, message_audio


_LANGUAGE_MAP = registered_locale_codes()


# ── Fixtures and helpers ─────────────────────────────────────────────────────


@pytest.fixture
def own_temp_dir(tmp_path, monkeypatch):
    """Every temporary this module makes, in a directory the test can count."""
    import tempfile

    private = tmp_path / "temp"
    private.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(private))
    return private


def _leftovers(temp_dir):
    return sorted(p.name for p in temp_dir.glob("winzapp-audio-*"))


def _msg(msg_type, msg_id="ABCDEF0123456789", mimetype=None, where="inner"):
    """One record in WinZapp's canonical shape, with the mimetype where asked.

    `where` exists because WPPConnect puts the mimetype in three different
    places depending on which event produced the record, and a document that
    arrived through the one place the code did not look reads as "no mimetype".
    """
    record = {"key": {"id": msg_id, "remoteJid": "1@s.whatsapp.net"},
              "messageType": msg_type, "message": {msg_type: {}}}
    if mimetype is None:
        return record
    if where == "inner":
        record["message"][msg_type]["mimetype"] = mimetype
    elif where == "record":
        record["mimetype"] = mimetype
    else:
        record["mediaData"] = {"mimetype": mimetype}
    return record


# Real leading bytes for the containers WinZapp recognises. An MP4's `ftyp`
# box does not start the file — its size field does — which is why the sniffer
# searches a window rather than testing a prefix.
WAV = b"RIFF\x24\x08\x00\x00WAVEfmt "
MP3_ID3 = b"ID3\x03\x00\x00\x00\x00\x00\x00"
MP3_SYNC = b"\xff\xfb\x90\x64\x00\x00\x00\x00"
M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x02\x00"
OGG = b"OggS\x00\x02\x00\x00\x00\x00\x00\x00"

# The first 32 bytes of files the bundled `client/lib/ffmpeg.exe` was actually
# handed, encoded by that same binary from a two-second tone and then converted
# with `audio_prep._run_ffmpeg()`'s exact command (`-i <file>`, no `-f`, no
# `-ar`). Every one of them produced a WAV, which is the whole reason they are
# in the table: see TestFormatsFfmpegOpens below.
FLAC = b'fLaC\x00\x00\x00"\x04\x80\x04\x80\x00\x01\xa5\x00\x01\xfe\x03\xe8\x00\xf0\x00\x00}\x00\x07\x1f\xf2\xad\xdd\xd4'
AAC_MPEG4 = b"\xff\xf1`@D\x9f\xfc\xde\x02\x00Lavc58.42.102\x00\x02\x08\xab]i,T("
AAC_MPEG2 = b"\xff\xf9`@D\x9f\xfc\xde\x02\x00Lavc58.42.102\x00\x02\x08\xab]i,T("
WEBM = b"\x1aE\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84w"
MATROSKA = b"\x1aE\xdf\xa3\x01\x00\x00\x00\x00\x00\x00#B\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x88m"
AMR_NB = b"#!AMR\n<$\x03\xb7P\x10K\xc7\xe8\xcc\x01\xea\xf7\x04Uu\xc0\x00\r\x04\x19\x1fd`\x00\x00"
AMR_WB = b"#!AMR-WB\n\x14\xf7\xce`\x9a6\t\x00\xb6\x88\xc2O\xb1N\xf7\x83h\x80\x00\x18\x08\x88\x00"
AIFF = b"FORM\x00\x00\xfa.AIFFCOMM\x00\x00\x00\x12\x00\x01\x00\x00}\x00\x00\x10@\x0c\xfa\x00"
AIFC = b"FORM\x00\x00B\xa8AIFCFVER\x00\x00\x00\x04\xa2\x80Q@COMM\x00\x00\x00\x18"
WMA = b"0&\xb2u\x8ef\xcf\x11\xa6\xd9\x00\xaa\x00b\xcel\xee\x01\x00\x00\x00\x00\x00\x00\x05\x00\x00\x00\x01\x02\xa1\xdc"

# What a failed OGG encode leaves in a `.msv`: signed 16-bit samples and not
# one byte saying at what rate they were taken.
RAW_PCM = bytes(range(64))


def _cached(tmp_path, fernet, payload, name="ABCDEF0123456789.msv"):
    path = tmp_path / name
    path.write_bytes(fernet.encrypt(payload))
    return str(path)


# ── The id rule ──────────────────────────────────────────────────────────────


class TestCleanMessageId:
    """The name on disk is not always the id on the record.

    `_save_message_media()` strips WPPConnect's `false_<jid>_<id>` prefix and
    the media downloader writes the file under what is left. Following the
    other rule in the repository — `local_media_cache_paths()`'s raw id — is a
    silent miss, not an error: every such message would report "not downloaded
    yet" with its audio sitting on disk.
    """

    def test_a_bare_id_is_left_alone(self):
        assert message_audio.clean_message_id("ABCDEF0123456789") == "ABCDEF0123456789"

    def test_a_compound_id_keeps_its_third_part(self):
        assert message_audio.clean_message_id(
            "false_1234@c.us_ABCDEF0123456789"
        ) == "ABCDEF0123456789"

    def test_our_own_echo_is_stripped_the_same_way(self):
        assert message_audio.clean_message_id(
            "true_1234@c.us_ABCDEF0123456789"
        ) == "ABCDEF0123456789"

    def test_a_two_part_id_keeps_its_last(self):
        """The `parts[-1]` half of the rule, which the house code also has."""
        assert message_audio.clean_message_id("false_ABCDEF") == "ABCDEF"

    def test_extra_parts_do_not_shift_the_answer(self):
        """A participant suffix appears after the id, never before it."""
        assert message_audio.clean_message_id(
            "false_1234@g.us_ABCDEF_5678@c.us"
        ) == "ABCDEF"

    @pytest.mark.parametrize("value", ["", None])
    def test_no_id_is_an_empty_answer_rather_than_a_crash(self, value):
        assert message_audio.clean_message_id(value) == ""


# ── Which messages are offered at all ────────────────────────────────────────


class TestIsTranscribable:
    """Voice notes, audio files and videos (their sound track), plus documents
    that are audio or video. Never a GIF: it is a silent loop."""

    def test_a_voice_note_is(self):
        assert message_audio.is_transcribable(_msg("audioMessage")) is True

    def test_an_audio_file_is_too(self):
        """Same type as a voice note — the ptt flag separates them only for
        the UI, and both are speech worth transcribing."""
        assert message_audio.is_transcribable(
            _msg("audioMessage", mimetype="audio/mpeg")
        ) is True

    @pytest.mark.parametrize("where", ["inner", "record", "media_data"])
    def test_an_audio_document_is_wherever_its_mimetype_sits(self, where):
        assert message_audio.is_transcribable(
            _msg("documentMessage", mimetype="audio/mpeg", where=where)
        ) is True

    def test_a_mimetype_with_parameters_still_counts(self):
        assert message_audio.is_transcribable(
            _msg("documentMessage", mimetype="AUDIO/OGG; codecs=opus")
        ) is True

    def test_a_document_that_is_not_audio_is_not(self):
        assert message_audio.is_transcribable(
            _msg("documentMessage", mimetype="application/pdf")
        ) is False

    def test_a_document_with_no_mimetype_is_not(self):
        assert message_audio.is_transcribable(_msg("documentMessage")) is False

    def test_a_video_is(self):
        assert message_audio.is_transcribable(_msg("videoMessage", mimetype="video/mp4")) is True
        assert message_audio.is_video(_msg("videoMessage")) is True

    def test_a_gif_is_not(self):
        gif = _msg("videoMessage", mimetype="video/mp4")
        gif["message"]["videoMessage"]["gifPlayback"] = True
        assert message_audio.is_transcribable(gif) is False

    def test_a_video_document_is(self):
        doc = _msg("documentMessage", mimetype="video/quicktime")
        assert message_audio.is_transcribable(doc) is True
        assert message_audio.is_video(doc) is True
        assert message_audio.is_video(_msg("documentMessage", mimetype="audio/ogg")) is False
        assert message_audio.is_video(_msg("audioMessage")) is False

    def test_the_stated_length_is_read_for_audio_and_video(self):
        audio = _msg("audioMessage")
        audio["message"]["audioMessage"]["seconds"] = 12
        video = _msg("videoMessage")
        video["message"]["videoMessage"]["seconds"] = "40"
        assert message_audio.media_seconds(audio) == 12
        assert message_audio.media_seconds(video) == 40
        assert message_audio.media_seconds(_msg("videoMessage")) == 0
        assert message_audio.media_seconds(None) == 0

    @pytest.mark.parametrize(
        "msg_type", ["imageMessage", "stickerMessage", "conversation"]
    )
    def test_nothing_else_is(self, msg_type):
        assert message_audio.is_transcribable(
            _msg(msg_type, mimetype="video/mp4")
        ) is False

    @pytest.mark.parametrize("value", [None, "", 7, []])
    def test_anything_that_is_not_a_record_is_not(self, value):
        assert message_audio.is_transcribable(value) is False


class TestVideoContainers:
    def test_a_quicktime_file_without_ftyp_is_recognised(self):
        for atom in (b"moov", b"mdat", b"wide", b"free"):
            assert message_audio.sniff_extension(b"\x00\x00\x00\x08" + atom + b"\x00" * 24) == ".mov"

    def test_an_mp4_video_is_read_like_an_m4a(self):
        assert message_audio.sniff_extension(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20) == ".m4a"

    def test_a_video_lives_in_media(self, tmp_path):
        path = message_audio.cached_media_path(
            _msg("videoMessage"), str(tmp_path / "voice"), str(tmp_path / "media"))
        assert path == os.path.join(str(tmp_path / "media"), "ABCDEF0123456789.wzmedia")


class TestCachedMediaPath:
    """Two folders and two suffixes, taken from `_save_message_media()`."""

    def test_a_voice_note_lives_in_voice_messages(self, tmp_path):
        path = message_audio.cached_media_path(
            _msg("audioMessage"), str(tmp_path / "voice"), str(tmp_path / "media")
        )
        assert path == os.path.join(
            str(tmp_path / "voice"), "ABCDEF0123456789.msv"
        )

    def test_a_document_lives_in_media(self, tmp_path):
        path = message_audio.cached_media_path(
            _msg("documentMessage", mimetype="audio/mpeg"),
            str(tmp_path / "voice"), str(tmp_path / "media"),
        )
        assert path == os.path.join(
            str(tmp_path / "media"), "ABCDEF0123456789.wzmedia"
        )

    def test_the_compound_id_is_cleaned_before_it_becomes_a_name(self, tmp_path):
        """The regression this catches is a silent miss — see TestCleanMessageId."""
        path = message_audio.cached_media_path(
            _msg("audioMessage", msg_id="false_1234@c.us_ABCDEF0123456789"),
            str(tmp_path / "voice"), str(tmp_path / "media"),
        )
        assert os.path.basename(path) == "ABCDEF0123456789.msv"

    def test_a_record_with_no_id_has_nowhere_to_look(self, tmp_path):
        assert message_audio.cached_media_path(
            {"key": {}, "messageType": "audioMessage"},
            str(tmp_path / "voice"), str(tmp_path / "media"),
        ) is None


# ── The sniffer ──────────────────────────────────────────────────────────────


class TestSniffExtension:
    """Every signature, and None for everything else — including raw PCM.

    None is the answer that matters, in both directions. `_toggle_playback()`
    falls back to the mimetype's extension here and is right to; a
    transcription may not, because the sentence the user then hears is decided
    by whatever ffmpeg's stderr happens to match. But None for something ffmpeg
    would have opened is the mirror failure, and TestFormatsFfmpegOpens is the
    half that pins it.
    """

    @pytest.mark.parametrize(
        "header, expected",
        [
            (WAV, ".wav"),
            (MP3_ID3, ".mp3"),
            (b"\xff\xfb\x90\x64", ".mp3"),
            (b"\xff\xf3\x90\x64", ".mp3"),
            (b"\xff\xf2\x90\x64", ".mp3"),
            (M4A, ".m4a"),
            (OGG, ".ogg"),
        ],
    )
    def test_each_signature_is_recognised(self, header, expected):
        assert message_audio.sniff_extension(header) == expected

    def test_a_flac_is_recognised(self):
        assert message_audio.sniff_extension(FLAC) == ".flac"

    @pytest.mark.parametrize("header", [AAC_MPEG4, AAC_MPEG2])
    def test_both_adts_aac_syncwords_are_recognised(self, header):
        """`\\xff\\xf1` is MPEG-4 AAC and `\\xff\\xf9` MPEG-2; ffmpeg writes the
        first, and plenty of encoders in circulation write the second."""
        assert message_audio.sniff_extension(header) == ".aac"

    @pytest.mark.parametrize("header", [AAC_MPEG4, AAC_MPEG2])
    def test_an_adts_syncword_is_not_mistaken_for_an_mpeg_frame(self, header):
        """They share the 12-bit syncword. The two bytes ADTS uses spell the
        reserved layer 00 in an MPEG audio frame, so nothing is given up by
        claiming them — but an MP3 answer here names the wrong demuxer."""
        assert message_audio.sniff_extension(header) != ".mp3"

    @pytest.mark.parametrize("header", [WEBM, MATROSKA])
    def test_ebml_is_recognised_whichever_doctype_follows(self, header):
        """One ffmpeg demuxer reads WebM and Matroska both, and the DocType
        that separates them starts at offset 27 — "matroska" runs past the
        32-byte window, so the suffix cannot honestly distinguish them."""
        assert message_audio.sniff_extension(header) == ".webm"

    @pytest.mark.parametrize("header", [AMR_NB, AMR_WB])
    def test_both_amr_flavours_are_recognised(self, header):
        """WhatsApp sent voice notes as AMR for years, and AMR-WB shares the
        `#!AMR` prefix with the narrowband one."""
        assert message_audio.sniff_extension(header) == ".amr"

    @pytest.mark.parametrize("header", [AIFF, AIFC])
    def test_aiff_is_recognised_by_its_type_not_by_form(self, header):
        assert message_audio.sniff_extension(header) == ".aiff"

    def test_an_iff_file_that_is_not_audio_is_not_claimed(self):
        """`FORM` alone is the IFF container, which carries images and
        animations too; the type at offset 8 is what makes it audio."""
        assert message_audio.sniff_extension(
            b"FORM\x00\x00\xfa.ILBMBMHD\x00\x00\x00\x14"
        ) is None

    def test_an_asf_container_is_recognised(self):
        assert message_audio.sniff_extension(WMA) == ".wma"

    def test_an_ftyp_box_at_the_end_of_the_window_still_counts(self):
        """The window is 32 bytes because an MP4 box can sit well past the
        start; 28 is the last offset that fits inside it."""
        assert message_audio.sniff_extension(b"\x00" * 28 + b"ftyp") == ".m4a"

    def test_an_ftyp_box_past_the_window_does_not(self):
        """Pinned so the window cannot be widened by accident: `ftyp` is four
        ordinary bytes, and finding it deep inside a file says nothing."""
        assert message_audio.sniff_extension(b"\x00" * 40 + b"ftypM4A ") is None

    def test_raw_pcm_is_not_recognised_and_must_not_be(self):
        """The whole reason this function exists. See the class docstring."""
        assert message_audio.sniff_extension(RAW_PCM) is None

    @pytest.mark.parametrize("header", [b"", None, b"\x00\x00"])
    def test_nothing_to_read_is_not_a_crash(self, header):
        assert message_audio.sniff_extension(header) is None

    def test_only_the_first_bytes_are_ever_read(self):
        """A megabyte of audio is not scanned to answer a four-byte question."""
        assert message_audio.sniff_extension(WAV + b"\xff\xfb" * 4096) == ".wav"


#: Every header below is the real first 32 bytes of a file the bundled ffmpeg
#: encoded and then converted back through `audio_prep._run_ffmpeg()`'s exact
#: command line. The conversion is not re-run here — a release build has no
#: reason to spawn ffmpeg nine times, and `client/lib/ffmpeg.exe` is not in the
#: repository — so what the table records is the measurement, and what the test
#: asserts is that the sniffer has not since been narrowed back past it.
_FFMPEG_OPENS = (
    ("FLAC", FLAC),
    ("ADTS AAC, MPEG-4", AAC_MPEG4),
    ("ADTS AAC, MPEG-2", AAC_MPEG2),
    ("WebM", WEBM),
    ("Matroska", MATROSKA),
    ("AMR-NB", AMR_NB),
    ("AMR-WB", AMR_WB),
    ("AIFF", AIFF),
    ("AIFF-C", AIFC),
    ("ASF/WMA", WMA),
)


class TestFormatsFfmpegOpens:
    """A format the bundled ffmpeg converts must not be refused before it.

    The refusal is not a fallback — nothing downstream retries, so a signature
    missing here is "this audio format was not recognised" spoken about a file
    the user can play in the conversation with Enter, after WinZapp has already
    downloaded and decrypted it. These all arrive in practice:
    `_resolve_media_filename()` keeps `audio/aac`, `audio/flac`, `audio/opus`
    and `audio/webm` in its own table, and `is_transcribable()` says yes to any
    `audioMessage` and to any `documentMessage` whose mimetype is `audio/*`.
    """

    @pytest.mark.parametrize("name, header", _FFMPEG_OPENS,
                             ids=[name for name, _ in _FFMPEG_OPENS])
    def test_it_is_not_turned_away(self, name, header):
        assert message_audio.sniff_extension(header) is not None, name

    @pytest.mark.parametrize("name, header", _FFMPEG_OPENS,
                             ids=[name for name, _ in _FFMPEG_OPENS])
    def test_the_temporary_is_named_for_what_it_is(
        self, name, header, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The suffix is only a hint — ffmpeg reads the content — but the tools
        around it do not, so a whole-path test is cheaper than trusting one."""
        source = _cached(tmp_path, fernet, header + b"\x00" * 64)
        temp = message_audio.decrypt_to_temp(source, fernet_key)
        try:
            assert os.path.splitext(temp)[1] == message_audio.sniff_extension(header)
        finally:
            message_audio.discard_temp(temp)
        assert _leftovers(own_temp_dir) == []


#: A bare frame stream — MP3 with no ID3 tag, ADTS AAC — has no container, so
#: the sniffer recognises it by a header and then a *second* header where the
#: first says the next frame begins. Each row is the real first 32 bytes of a
#: file that converted through `audio_prep._run_ffmpeg()`'s exact command with
#: the bundled ffmpeg, and the frame length worked out by hand from that
#: header (so it cross-checks the code's arithmetic rather than reusing it).
#:
#: The plain rows were encoded by the bundled ffmpeg itself. It has no switch
#: for a CRC, so the CRC rows were derived from those: the protection bit
#: cleared, a CRC-16 inserted after the header (MPEG: computed per ISO 11172-3
#: over the header's last two bytes and the side info, on a stream encoded
#: without the bit reservoir so the two tail bytes it displaces were unused;
#: ADTS: the length field grown by two, the CRC left zero, which ffmpeg does not
#: check by default). Each one decoded to PCM byte-identical to its source.
#: The old two-byte table recognised none of the CRC rows, and neither
#: MPEG-2.5 nor layer II.
_FRAME_STREAMS = (
    # 320 kbit/s, 44.1 kHz, no padding: 144 * 320000 / 44100 = 1044
    ("MPEG-1 layer III", 1044,
     b"\xff\xfb\xe0\xc4\x00\x001\xd2\x0b\nu\xdc\x80\x05}E\xe0C?\xc0\x00\x05\xdb$\x94\xe9\x9aD\xe7\xf9t\xe2"),
    ("MPEG-1 layer III, CRC", 1044,
     b"\xff\xfa\xe0\xc4\xb8\x12\x00\x001\xd2\x0b\nu\xdc\x80\x05}E\xe0C?\xc0\x00\x05\xdb$\x94\xe9\x9aD\xe7\xf9"),
    # 160 kbit/s, 22.05 kHz: 72 * 160000 / 22050 = 522
    ("MPEG-2 layer III", 522,
     b"\xff\xf3\xe0\xc4\x00{\x04\x11\xf0\x01^\xd8\x004-C\x13C\xb4M4gHSJ\x14\xaf4\xa7H\x13B"),
    ("MPEG-2 layer III, CRC", 522,
     b"\xff\xf2\xe0\xc4\x10\xe1\x00{\x04\x11\xf0\x01^\xd8\x004-C\x13C\xb4M4gHSJ\x14\xaf4\xa7H"),
    # 64 kbit/s, 8 kHz: 72 * 64000 / 8000 = 576
    ("MPEG-2.5 layer III, 8 kHz", 576,
     b"\xff\xe3\x88\xc4\x00v\xe4n\x18\x17]x\x00\x01\xe8\x00\x18\xe28\x98\xe29\x98\xe6:\x98\xea;\x98\xea9\x98"),
    # 64 kbit/s, 11.025 kHz: 72 * 64000 / 11025 = 417
    ("MPEG-2.5 layer III, 11 kHz", 417,
     b"\xff\xe3\x80\xc4\x00_C\xc6\x18\x03]\xd8\x00\t\x92\xe4\xb9\x92\xe4\xc9\x93$\xe9\x93\xa4\xf9\x93\xe4\xd9\x92\xe4\x89"),
    ("MPEG-2.5 layer III, 8 kHz, CRC", 576,
     b"\xff\xe2\x88\xc4\x82U\x00v\xe4n\x18\x17]x\x00\x01\xe8\x00\x18\xe28\x98\xe29\x98\xe6:\x98\xea;\x98\xea"),
    # Layer II, 128 kbit/s, 44.1 kHz: 144 * 128000 / 44100 = 417
    ("MPEG-1 layer II", 417,
     b"\xff\xfd\x80\xc4uVVeU[n\xb1\x00\x00\x00\x02\xcf\xff\xff\xff\xccQ\xf7/\xe1\xdca\xce\re\xda;"),
    # ADTS carries its length in the header: 0x1a << 3 | 0xdf >> 5 = 214
    ("ADTS AAC, MPEG-4, CRC", 214,
     b"\xff\xf0P@\x1a\xdf\xfc\x00\x00\xde\x02\x00Lavc58.42.102\x00\x02\\\xabY\xa9\x8c"),
    ("ADTS AAC, MPEG-2, CRC", 214,
     b"\xff\xf8P@\x1a\xdf\xfc\x00\x00\xde\x02\x00Lavc58.42.102\x00\x02\\\xabY\xa9\x8c"),
    # 0x44 << 3 | 0x9f >> 5 = 548
    ("ADTS AAC, MPEG-4", 548, AAC_MPEG4),
    ("ADTS AAC, MPEG-2", 548, AAC_MPEG2),
)


def _stream(first, length, frames=3):
    """`frames` frames of `length` bytes, each opening with the same header."""
    frame = first + b"\x00" * (length - len(first))
    return frame * frames


def _pcm_tone(rate=48000, seconds=1.0, hz=440.0, amplitude=12000):
    count = int(rate * seconds)
    return struct.pack(
        f"<{count}h",
        *(int(amplitude * math.sin(2 * math.pi * hz * i / rate)) for i in range(count)),
    )


def _pcm_noise(size=64000, seed=112):
    return random.Random(seed).randbytes(size)


# A first sample that spells a header: `ff fb` is -1025 as little-endian s16,
# which any recording passes through. Each of these is a header the sniffer
# accepts on its own — which is exactly why it cannot stop at one.
_FAKE_HEADERS = (
    ("MPEG-1 layer III", b"\xff\xfb\x90\x64"),
    ("MPEG-1 layer III, CRC", b"\xff\xfa\x90\x64"),
    ("MPEG-2 layer III", b"\xff\xf3\x90\x64"),
    ("MPEG-2.5 layer III", b"\xff\xe3\x88\xc4"),
    ("MPEG-1 layer II", b"\xff\xfd\x80\xc4"),
    ("ADTS", b"\xff\xf1\x50\x40\x1a\xdf\xfc"),
    ("ADTS, CRC", b"\xff\xf0\x50\x40\x1a\xdf\xfc"),
    ("ADTS, MPEG-2", b"\xff\xf9\x50\x40\x1a\xdf\xfc"),
)


class TestBareFrameStreams:
    """MP3 without ID3 and ADTS AAC: read by their fields, proven by a second
    frame.

    Both directions fail quietly. A byte table (which this was) refused MP3
    and ADTS files the bundled ffmpeg converts — every MPEG version and CRC
    flag is a different second byte — and the user was told the format was not
    recognised about a file that plays in the conversation. A header alone,
    on the other hand, lets raw PCM through whenever its first sample spells
    one; measured, pink noise behind such a header reached ffmpeg and came back
    as FFMPEG_FAILED rather than the format sentence.
    """

    @pytest.mark.parametrize("name, length, first", _FRAME_STREAMS,
                             ids=[name for name, _, _ in _FRAME_STREAMS])
    def test_every_version_layer_and_crc_flag_ffmpeg_converts_is_recognised(
        self, name, length, first
    ):
        expected = ".aac" if "ADTS" in name else ".mp3"
        assert message_audio.sniff_extension(_stream(first, length)) == expected, name

    @pytest.mark.parametrize("name, length, first", _FRAME_STREAMS,
                             ids=[name for name, _, _ in _FRAME_STREAMS])
    def test_a_second_header_one_byte_off_does_not_count(self, name, length, first):
        """The offset is the proof. A sync somewhere near it is what noise
        produces; one exactly at the length the first header promised is not."""
        frame = first + b"\x00" * (length - len(first))
        shifted = frame + b"\x00" + frame
        assert message_audio.sniff_extension(shifted) is None, name

    def test_a_second_header_at_another_rate_does_not_count(self):
        """Version, layer and sample rate hold for a whole stream; only the
        bitrate (VBR), the padding and the CRC flag change frame to frame."""
        first = b"\xff\xfb\x90\x64"           # 44.1 kHz, 417 bytes
        other = b"\xff\xfb\x94\x64"           # 48 kHz
        data = first + b"\x00" * 413 + other + b"\x00" * 600
        assert message_audio.sniff_extension(data) is None

    def test_a_vbr_stream_changing_bitrate_still_counts(self):
        first = b"\xff\xfb\x90\x64"           # 128 kbit/s, 417 bytes
        other = b"\xff\xfb\xe0\x64"           # 320 kbit/s
        data = first + b"\x00" * 413 + other + b"\x00" * 1100
        assert message_audio.sniff_extension(data) == ".mp3"

    @pytest.mark.parametrize(
        "why, first",
        [
            ("version 01 is reserved", b"\xff\xeb\x90\x64"),
            ("bitrate 1111 is invalid", b"\xff\xfb\xf0\x64"),
            ("free format has no length, and ffmpeg fails on it", b"\xff\xfb\x04\x64"),
            ("sample rate 11 is reserved", b"\xff\xfb\x9c\x64"),
            ("layer 00 behind an 11-bit sync is neither", b"\xff\xe1\x50\x40\x1a\xdf\xfc"),
            ("ADTS rate index 13 has no rate", b"\xff\xf1\x74\x40\x1a\xdf\xfc"),
            ("ADTS shorter than its own header", b"\xff\xf1\x50\x40\x00\x1f\xfc"),
        ],
    )
    def test_what_ffmpeg_itself_refuses_is_refused_here(self, why, first):
        """Accepting these would only move the refusal into ffmpeg's stderr,
        where its wording decides the sentence.

        Deliberately shorter than any frame, so there is no second header to
        fail on and the field alone has to do the refusing — a stream of
        copies would be refused anyway whenever the copies sat at the wrong
        distance for the length a loosened check computed, and the test would
        pass for the wrong reason."""
        data = first + b"\x00" * 100
        assert message_audio.sniff_extension(data) is None, why

    def test_a_stream_too_short_for_a_second_header_is_given_the_benefit(self):
        """Nothing to demand: a file shorter than one frame. A raw PCM voice
        note is seconds of audio, far past any frame length."""
        assert message_audio.sniff_extension(b"\xff\xfb\x90\x64" + b"\x00" * 100) == ".mp3"

    @pytest.mark.parametrize("body", ["tone", "noise"])
    @pytest.mark.parametrize("name, fake", _FAKE_HEADERS,
                             ids=[name for name, _ in _FAKE_HEADERS])
    def test_raw_pcm_whose_first_sample_spells_a_header_is_still_refused(
        self, name, fake, body, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The `.msv` of a failed OGG encode, reaching the user as the format
        sentence and not as whatever ffmpeg's stderr earns. A tone and pink
        noise behind each of these headers were also run through the bundled
        ffmpeg (not here — see _FFMPEG_OPENS) under the extension a header-only
        sniff would have picked: every one was refused, and the MPEG headers
        over noise in words that classify as FFMPEG_FAILED."""
        samples = _pcm_tone() if body == "tone" else _pcm_noise()
        payload = fake + samples[len(fake):]
        assert message_audio.sniff_extension(payload) is None
        source = _cached(tmp_path, fernet, payload)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.UNSUPPORTED_AUDIO_FORMAT
        assert _leftovers(own_temp_dir) == []


# ── Decrypting ───────────────────────────────────────────────────────────────


class TestDecryptToTemp:
    @pytest.mark.parametrize(
        "payload, suffix",
        [(WAV, ".wav"), (MP3_ID3, ".mp3"), (M4A, ".m4a"), (OGG, ".ogg")],
    )
    def test_the_temporary_carries_the_sniffed_suffix_and_the_plain_bytes(
        self, tmp_path, own_temp_dir, fernet, fernet_key, payload, suffix
    ):
        source = _cached(tmp_path, fernet, payload + b"\x00" * 64)
        temp = message_audio.decrypt_to_temp(source, fernet_key)
        try:
            assert temp.endswith(suffix)
            with open(temp, "rb") as handle:
                assert handle.read() == payload + b"\x00" * 64
        finally:
            message_audio.discard_temp(temp)
        assert _leftovers(own_temp_dir) == []

    def test_the_temporary_is_never_named_after_the_message(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """%TEMP% is not a private place, and the file name on disk *is* the
        WhatsApp message id."""
        source = _cached(tmp_path, fernet, WAV, name="ZZQQ7654321YYWW.msv")
        temp = message_audio.decrypt_to_temp(source, fernet_key)
        try:
            assert "ZZQQ7654321YYWW" not in os.path.basename(temp)
        finally:
            message_audio.discard_temp(temp)

    def test_raw_pcm_is_refused_rather_than_guessed_at(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The most important assertion in this file.

        A fallback to the mimetype's extension here would make this test pass
        a `.ogg` to ffmpeg, which would convert it at a rate nobody measured —
        and the user would be read an invented paragraph with no way to tell.
        """
        source = _cached(tmp_path, fernet, RAW_PCM)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.UNSUPPORTED_AUDIO_FORMAT
        assert _leftovers(own_temp_dir) == []

    def test_a_missing_file_is_a_download_that_has_not_finished(
        self, tmp_path, own_temp_dir, fernet_key
    ):
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(str(tmp_path / "nothing.msv"), fernet_key)
        assert caught.value.code == errors.MEDIA_NOT_DOWNLOADED
        assert _leftovers(own_temp_dir) == []

    def test_no_path_at_all_is_the_same_answer(self, own_temp_dir, fernet_key):
        """`cached_media_path()` answers None for a record with no id, and
        that has to reach the user as a sentence rather than a TypeError."""
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(None, fernet_key)
        assert caught.value.code == errors.MEDIA_NOT_DOWNLOADED

    def test_a_zero_byte_placeholder_is_a_download_in_flight(
        self, tmp_path, own_temp_dir, fernet_key
    ):
        """Read the same way audio_prep reads it: the user's answer is to wait,
        not to report a damaged file."""
        empty = tmp_path / "ABCDEF0123456789.msv"
        empty.write_bytes(b"")
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(str(empty), fernet_key)
        assert caught.value.code == errors.MEDIA_NOT_DOWNLOADED

    def test_a_file_fernet_refuses_is_damaged_audio(
        self, tmp_path, own_temp_dir, fernet_key
    ):
        """Truncated mid-write, or written under a different secret.key — and
        from the user's side the same thing: this recording is not usable."""
        broken = tmp_path / "ABCDEF0123456789.msv"
        broken.write_bytes(b"gAAAAA-this-is-not-a-fernet-token")
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(str(broken), fernet_key)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert _leftovers(own_temp_dir) == []

    def test_the_technical_reason_is_kept_for_the_log_and_out_of_the_sentence(
        self, tmp_path, own_temp_dir, fernet_key
    ):
        """`str(exc)` is one careless `wx.MessageBox` away from being spoken."""
        broken = tmp_path / "ABCDEF0123456789.msv"
        broken.write_bytes(b"not a token")
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(str(broken), fernet_key)
        assert caught.value.detail
        assert str(caught.value) == errors.AUDIO_INCOMPLETE
        assert caught.value.detail not in str(caught.value)

    def test_running_out_of_memory_is_told_apart_in_the_detail(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The whole file is read and decrypted in memory, and Fernet's base64
        step peaks at about three times its size — an audio document may be
        2 GB, so this is a machine running out of room, not a damaged file.
        The sentence is shared (a fifth error code costs five translations to
        say something only a log reader can use), so `detail` is the only place
        the two can be told apart when the report comes in.
        """
        source = _cached(tmp_path, fernet, WAV)

        def _exhausted(data, key):
            raise MemoryError()

        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key, decrypt=_exhausted)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert "MemoryError" in caught.value.detail
        # `str(MemoryError())` is empty, so a bare f-string would have written
        # "MemoryError: " and said nothing the log could use.
        assert caught.value.detail.strip() != "MemoryError:"
        assert _leftovers(own_temp_dir) == []

    def test_a_file_that_cannot_be_read_says_so_rather_than_blaming_fernet(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """A drive pulled mid-read and a truncated recording reach the user as
        the same sentence; only the log can separate them, so it must."""
        source = _cached(tmp_path, fernet, WAV)
        real_open = open

        def _refuse(path, *args, **kwargs):
            if str(path) == source:
                raise OSError("the device is not ready")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", _refuse)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert caught.value.detail.startswith("read failed:")
        assert "OSError" in caught.value.detail

    def test_a_decrypt_that_raises_never_leaves_a_temporary(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        source = _cached(tmp_path, fernet, WAV)

        def _explode(data, key):
            raise ValueError("boom")

        with pytest.raises(errors.TranscriptionError):
            message_audio.decrypt_to_temp(source, fernet_key, decrypt=_explode)
        assert _leftovers(own_temp_dir) == []

    def test_the_injected_decrypt_is_handed_the_file_and_the_key(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The seam part 6b's job uses; nothing here reaches for a MainWindow."""
        source = _cached(tmp_path, fernet, OGG)
        seen = {}

        def _record(data, key):
            seen["data"] = data
            seen["key"] = key
            return WAV

        temp = message_audio.decrypt_to_temp(source, fernet_key, decrypt=_record)
        message_audio.discard_temp(temp)
        with open(source, "rb") as handle:
            assert seen["data"] == handle.read()
        assert seen["key"] == fernet_key

    def test_a_write_that_fails_half_way_takes_the_temporary_with_it(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """The branch that matters: the name exists before the bytes do, so a
        failure between the two leaves a file nobody is left holding."""
        source = _cached(tmp_path, fernet, WAV)
        real_fdopen = os.fdopen

        def _fail(handle, *args, **kwargs):
            real_fdopen(handle, *args, **kwargs).close()
            raise OSError("the disk filled up")

        monkeypatch.setattr(os, "fdopen", _fail)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        # No error number at all, so nothing says the disk is full: the
        # sentence must not blame the recording either, which is what
        # AUDIO_INCOMPLETE would do.
        assert caught.value.code == errors.BACKEND_ERROR
        assert _leftovers(own_temp_dir) == []


class TestAFullDiskIsASentence:
    """Decrypting a 2 GB audio document into a nearly full system drive.

    This used to let a raw OSError escape, which is not the contract: every
    failure here is a TranscriptionError, so the caller can say it — and an
    OSError that escaped would be logged whole by the caller's catch-all,
    temporary path and Windows user name included.
    """

    def _fill_disk(self, monkeypatch, failure):
        real_fdopen = os.fdopen
        seen = {}

        def _full(handle, *args, **kwargs):
            real_fdopen(handle, *args, **kwargs).close()
            raise failure(seen)

        real_mkstemp = message_audio.tempfile.mkstemp

        def _mkstemp(*args, **kwargs):
            handle, path = real_mkstemp(*args, **kwargs)
            seen["path"] = path
            return handle, path

        monkeypatch.setattr(message_audio.tempfile, "mkstemp", _mkstemp)
        monkeypatch.setattr(os, "fdopen", _full)
        return seen

    @pytest.mark.parametrize(
        "make",
        [
            lambda seen: OSError(errno.ENOSPC, "No space left on device", seen["path"]),
            lambda seen: OSError(None, "There is not enough space on the disk",
                                 seen["path"], 112),
            lambda seen: OSError(None, "The disk is full", seen["path"], 39),
        ],
        ids=["enospc", "winerror-112", "winerror-39"],
    )
    def test_a_full_disk_says_temp_no_disk_space(
        self, make, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        source = _cached(tmp_path, fernet, WAV)
        seen = self._fill_disk(monkeypatch, make)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        # The temporary's own code, not the downloads' NO_DISK_SPACE: nothing
        # was being downloaded, and "for this download" sends the user to
        # look for one.
        assert caught.value.code == errors.TEMP_NO_DISK_SPACE
        assert _leftovers(own_temp_dir) == []
        # The temporary's folder carries the Windows user name.
        rendered = "".join(traceback.format_exception(caught.value))
        for text in (caught.value.detail, caught.value.log_line, rendered):
            assert seen["path"] not in text
            assert os.path.basename(seen["path"]) not in text

    @pytest.mark.parametrize("locale", sorted(_LANGUAGE_MAP))
    def test_the_sentence_is_not_the_downloads_one(self, locale):
        """Two codes that read the same would be one code with extra steps."""
        table = load_strings(locale)
        temp = table[errors.error_i18n_key(errors.TEMP_NO_DISK_SPACE)]
        download = table[errors.error_i18n_key(errors.NO_DISK_SPACE)]
        assert temp and temp != download

    def test_a_temp_folder_that_cannot_be_written_is_not_blamed_on_the_audio(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """mkstemp itself failing: there is no temporary to clean up, and the
        recording is fine."""
        source = _cached(tmp_path, fernet, WAV)

        def _refuse(*args, **kwargs):
            raise PermissionError(13, "Permission denied", str(own_temp_dir))

        monkeypatch.setattr(message_audio.tempfile, "mkstemp", _refuse)
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.BACKEND_ERROR
        assert str(own_temp_dir) not in caught.value.log_line


class TestTemporaryLifetime:
    """The temporary is a private recording in clear. It goes, every way out."""

    def test_the_context_manager_removes_it_on_success(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        source = _cached(tmp_path, fernet, WAV)
        with message_audio.decrypted_audio(source, fernet_key) as temp:
            assert os.path.isfile(temp)
        assert _leftovers(own_temp_dir) == []

    def test_the_context_manager_removes_it_when_the_block_raises(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """A cancellation and a backend failure both leave through here."""
        source = _cached(tmp_path, fernet, WAV)
        with pytest.raises(errors.TranscriptionError):
            with message_audio.decrypted_audio(source, fernet_key):
                raise errors.TranscriptionError(errors.CANCELLED, "by the user")
        assert _leftovers(own_temp_dir) == []

    def test_a_file_handed_on_survives_until_its_new_owner_discards_it(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """Why `decrypt_to_temp()` is not only a context manager: a run that
        failed on the GPU hands its audio to the re-run on the processor."""
        source = _cached(tmp_path, fernet, WAV)
        temp = message_audio.decrypt_to_temp(source, fernet_key)
        assert _leftovers(own_temp_dir) != []
        message_audio.discard_temp(temp)
        assert _leftovers(own_temp_dir) == []

    def test_discarding_twice_is_not_an_error(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        source = _cached(tmp_path, fernet, WAV)
        temp = message_audio.decrypt_to_temp(source, fernet_key)
        message_audio.discard_temp(temp)
        message_audio.discard_temp(temp)

    @pytest.mark.parametrize("value", [None, ""])
    def test_discarding_nothing_is_not_an_error(self, value):
        message_audio.discard_temp(value)


# ── Privacy of the log ───────────────────────────────────────────────────────


# Every local name in this module holds something the log may not carry: the
# media path and the temporary path (both named after the message id), the id
# itself, the record, and the decrypted bytes. Written as patterns rather than
# an enumeration because `\bpath\b` does not match `media_path` — `_` is a word
# character — which is why test_transcription_backend.py spells out
# `source_path` next to it.
#
# `clean`, `parts` and `head` are the ones that read as innocent and are not:
# `clean` is the message id after `clean_message_id()`, `parts` holds it split
# apart (`parts[2]` *is* the id, and `parts[1]` the chat JID), and `head` is the
# first bytes of the decrypted recording. A scan that stops at the two obvious
# paths is exactly as good as no scan on the day `test_this_module_logs_nothing
# _at_all` is relaxed, which is the day this one is supposed to take over.
_FORBIDDEN_IN_LOG = (
    r"_path\b", r"\bpath\b", r"_id\b", r"\bid\b", r"\bmsg\b", r"\btext\b",
    r"\bplain\b", r"\bheader\b", r"\bhead\b", r"\bclean\b", r"\bparts\b",
    r"\bjid\b", r"\bcontact\b", r"\bphone\b",
)


def _logging_arguments(path):
    """Every expression handed to a `logging.*` call in one module."""
    with open(path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if not (isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "logging"):
            continue
        for argument in list(node.args) + [kw.value for kw in node.keywords]:
            found.append((target.attr, ast.unparse(argument)))
    return found


class TestLogPrivacy:
    def test_this_module_logs_nothing_at_all(self):
        """The stronger of the two checks, and true today on purpose.

        Every value that passes through here is a path built from a message id,
        the id itself, or the decrypted recording — there is nothing left worth
        a log line. If a genuinely loggable fact ever appears, this assertion
        is the place that decision gets recorded, and the scan below is what
        keeps holding once it is relaxed.
        """
        with open(message_audio.__file__, "r", encoding="utf-8") as handle:
            source = handle.read()
        assert re.search(r"^\s*(import logging|from logging import)", source, re.M) is None

    def test_no_logging_call_could_be_handed_the_file_or_the_message(self):
        offenders = []
        for level, expression in _logging_arguments(message_audio.__file__):
            for pattern in _FORBIDDEN_IN_LOG:
                if re.search(pattern, expression):
                    offenders.append(f"logging.{level}({expression})")
        assert offenders == [], f"the log could identify the message: {offenders}"


# Shaped like a real WhatsApp id, so that a leak of it is a leak of something
# that would identify the message.
_LEAKY_ID = "3EB0C7F1A2B4D5E6F708"


def _open_raising(monkeypatch, source, failure):
    """`open()` of the media file raises `failure`; everything else is real."""
    real_open = open

    def _open(path, *args, **kwargs):
        if str(path) == source:
            raise failure
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _open)


def _read_raising(monkeypatch, source, failure):
    """The file opens, and `read()` raises — a drive pulled mid-read."""
    real_open = open

    class _Handle:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, *args):
            raise failure

    def _open(path, *args, **kwargs):
        if str(path) == source:
            return _Handle()
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _open)


class TestTheDetailNamesNoFile:
    """`detail` is what reaches the log, so it may not quote the file.

    This module logs nothing, and the scan above says so — but job.py logs
    `error.log_line` for every failure, which makes the `detail` built here
    this module's real log output. An OSError from `open()` quotes the path in
    both `str(exc)` and `exc.filename`, and the file is named after the message
    id. It is reachable: the user deleting the media just as a transcription
    starts, or an antivirus answering PermissionError.
    """

    def _assert_nothing_identifies_the_message(self, error, source):
        # The traceback too: anything that logs this error with exc_info would
        # print a chained original whole.
        rendered = "".join(traceback.format_exception(error))
        for where, text in (("detail", error.detail or ""),
                            ("log_line", error.log_line),
                            ("traceback", rendered)):
            for secret in (source, os.path.basename(source), _LEAKY_ID):
                assert secret not in text, f"{where} carries {secret!r}: {text!r}"

    def _source(self, tmp_path, fernet):
        folder = tmp_path / "voice_messages"
        folder.mkdir()
        return _cached(folder, fernet, WAV, name=f"{_LEAKY_ID}.msv")

    @pytest.mark.parametrize(
        "make",
        [
            lambda p: FileNotFoundError(2, "No such file or directory", p),
            lambda p: PermissionError(13, "Permission denied", p),
            lambda p: PermissionError(13, "Access is denied", p, 5),
            lambda p: OSError(22, "Invalid argument", p),
        ],
        ids=["vanished", "permission", "permission-winerror", "oserror"],
    )
    def test_an_open_that_fails_names_no_file(
        self, make, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        source = self._source(tmp_path, fernet)
        _open_raising(monkeypatch, source, make(source))
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        self._assert_nothing_identifies_the_message(caught.value, source)
        assert _leftovers(own_temp_dir) == []

    def test_a_read_that_fails_names_no_file(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        source = self._source(tmp_path, fernet)
        _read_raising(monkeypatch, source, PermissionError(13, "Permission denied", source))
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        self._assert_nothing_identifies_the_message(caught.value, source)

    def test_a_decrypt_whose_message_quotes_the_path_names_no_file(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """`decrypt` is injectable, so the text of what it raises is not the
        module's to vouch for — only its type is kept."""
        source = self._source(tmp_path, fernet)

        def _quoting(data, key):
            raise ValueError(f"cannot decrypt {source}")

        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key, decrypt=_quoting)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert "ValueError" in caught.value.detail
        self._assert_nothing_identifies_the_message(caught.value, source)

    def test_running_out_of_memory_names_no_file(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """The one branch this class did not cover, and the one that chained
        with `from exc`: a MemoryError is empty in production, but `decrypt`
        is injectable and the traceback printed the original whole."""
        source = self._source(tmp_path, fernet)

        def _exhausted(data, key):
            raise MemoryError(f"cannot allocate for {source}")

        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key, decrypt=_exhausted)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert caught.value.__cause__ is None
        self._assert_nothing_identifies_the_message(caught.value, source)

    def test_a_decrypt_raising_an_oserror_that_quotes_the_path_names_no_file(
        self, tmp_path, own_temp_dir, fernet, fernet_key
    ):
        """`strerror` is only the system's sentence when the system raised it.

        An injected `decrypt` can put anything there; measured, a path in it
        reached `log_line` while reading and decrypting shared one `try`.
        """
        source = self._source(tmp_path, fernet)

        def _quoting(data, key):
            raise OSError(5, f"cannot decrypt {source}")

        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key, decrypt=_quoting)
        assert caught.value.code == errors.AUDIO_INCOMPLETE
        assert "OSError" in caught.value.detail
        self._assert_nothing_identifies_the_message(caught.value, source)

    def test_what_the_log_keeps_is_still_worth_reading(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """Dropping the text must not drop the diagnosis: the type, the error
        number and the system's own sentence are what a report is read by."""
        source = self._source(tmp_path, fernet)
        _open_raising(monkeypatch, source, PermissionError(13, "Permission denied", source))
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        detail = caught.value.detail
        assert "PermissionError" in detail
        assert "errno=13" in detail
        assert "Permission denied" in detail

    def test_a_file_that_vanishes_before_it_is_read_is_not_downloaded(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """Deleted between the size check and the read: the same state the
        size check answers as not downloaded, not a damaged recording."""
        source = self._source(tmp_path, fernet)
        _open_raising(monkeypatch, source,
                      FileNotFoundError(2, "No such file or directory", source))
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.MEDIA_NOT_DOWNLOADED

    def test_a_permission_failure_is_still_a_damaged_read(
        self, tmp_path, own_temp_dir, fernet, fernet_key, monkeypatch
    ):
        """Only a missing file moves to MEDIA_NOT_DOWNLOADED; the file is there
        here, and waiting for a download would never end."""
        source = self._source(tmp_path, fernet)
        _open_raising(monkeypatch, source, PermissionError(13, "Permission denied", source))
        with pytest.raises(errors.TranscriptionError) as caught:
            message_audio.decrypt_to_temp(source, fernet_key)
        assert caught.value.code == errors.AUDIO_INCOMPLETE


def test_nothing_here_imports_wx():
    """Part 6a is the half that is testable without a wx.App, and stays so."""
    with open(message_audio.__file__, "r", encoding="utf-8") as handle:
        source = handle.read()
    assert re.search(r"^\s*(import wx|from wx)", source, re.M) is None
