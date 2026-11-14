"""From a WhatsApp message to a plain audio file ffmpeg can open.

`audio_prep` converts *a file* into what Whisper wants. This module answers the
question before it: which file, and how to get at it — WinZapp stores message
media encrypted, under a name derived from the message id, in one of two
folders depending on the type.

Three decisions carry this module, and the first one is the important one.

* **An audio WinZapp cannot identify is refused here, so that it is refused in
  the right words.** The one real case being turned away is a voice note
  recorded here: it falls back to writing **raw PCM** into the `.msv` when the
  OGG encode fails (`ogg_bytes or audio_data` in
  `ui/conversation_panel/voice_recording.py`), and the sample rate and channel
  count it was captured at (`_recording_actual_rate` / `_recording_actual_ch`)
  are not written anywhere in that file, so there is no saving it.

  What this sniff is *not* protecting against is an invented transcription.
  Measured against the bundled `client/lib/ffmpeg.exe` with `audio_prep`'s own
  arguments — which pass `-i <file>` and never `-f s16le -ar N` — raw PCM is
  refused under every extension a mimetype could suggest (`.ogg`, `.mp3`,
  `.wav`, `.m4a`, and the ones added since): ffmpeg only reads headerless PCM at
  a guessed rate when it is *told* the format, which this code never does. What
  varies is the **wording** of the refusal, and with it the sentence the user
  hears — and it varies with the content of the samples as much as with the
  extension: the same extension was measured to come back as
  UNSUPPORTED_AUDIO_FORMAT for one recording and as the generic FFMPEG_FAILED
  for another, and a stderr that happens to match audio_prep's truncation
  markers reports a damaged recording (AUDIO_INCOMPLETE) instead. No table of
  "this extension earns that sentence" holds. Sniffing first is what makes the
  answer UNSUPPORTED_AUDIO_FORMAT every time — the one sentence of the three a
  blind user can act on.

  Which is also why the table is not kept narrow. A format the bundled ffmpeg
  opens must not be refused here: FLAC, ADTS AAC, WebM/Matroska, AMR, AIFF and
  WMA all arrive in practice (`_resolve_media_filename()` keeps `audio/aac`,
  `audio/flac`, `audio/opus` and `audio/webm` in its own table and
  `_toggle_playback()` plays those files), and each one below was confirmed to
  convert through `audio_prep`'s exact command before it was added. None stays
  fatal, but it now means "nothing recognised it", not "it was not one of four".

* **The id is cleaned the way the media downloader cleans it, not the way
  `local_media_cache_paths()` does.** Two rules genuinely coexist in this
  repository: `local_media_cache_paths()` takes the raw id (it names files the
  *sender* side wrote, under a local UUID that has no underscores), while
  `_save_message_media()` and the Save As flow strip a `false_<jid>_<id>`
  prefix down to its third part. A transcription reads a file that WhatsApp's
  own download wrote — `handle_audio_message()` / `handle_media_message()`,
  reached through that same Save As path — so it follows that rule. Using the
  raw id here would simply miss the file on every message whose id carries the
  prefix.

* **Nothing here may reach the log.** The temporary holds the decrypted audio
  of a private conversation and the `.msv` is named after the message id, so
  neither path, neither file name and no id is ever logged — the same rule
  job.py states and `tests/test_transcription_message_audio.py` enforces
  statically. That covers the `detail` of every error raised here too, since
  `detail` is precisely what job.py writes to the log: it is built from error
  numbers and type names, never from an exception's own text, which for an
  `open()` failure quotes the path. The temporary is written under a random
  name for the same reason, and is deleted on success, on failure, on
  cancellation and on a re-run.
"""

from __future__ import annotations

import contextlib
import errno
import os
import tempfile

from core.transcription import errors
from core.utils import decrypt_bytes

# Message types a transcription will accept.
#
# `audioMessage` covers both a voice note and an audio file: they arrive under
# the same type, and the ptt flag only separates them for the UI's own purposes
# — both are speech worth transcribing.
#
# `videoMessage` is accepted too: the speech is the video's sound track, and
# audio_prep's ffmpeg command drops the picture (`-vn`) and converts that track
# exactly as it converts a voice note. A GIF (`gifPlayback`) is refused: it is
# a silent loop with nothing to hear.
#
# `documentMessage` is accepted only when its mimetype is audio/* or video/*:
# sending an mp3 or an mp4 as a document instead of as media is an ordinary
# thing to do, and the resulting message is the same recording under a
# different wrapper.
TRANSCRIBABLE_TYPES = ("audioMessage", "videoMessage", "documentMessage")

# Only the leading bytes are examined for a container signature, and 32 is
# what the `ftyp` test needs (an MP4 box can sit past the first few bytes). A
# bare frame header is the one exception — see _frame_header() for why it also
# looks where the second frame has to begin.
_SNIFF_BYTES = 32

# Bitrates in kbit/s by bitrate index, keyed by (MPEG-1?, layer). Index 0 is
# "free format", which has no length to compute — and which the bundled ffmpeg
# was measured to fail on with `audio_prep`'s arguments, so refusing it here
# loses nothing ffmpeg would have converted.
_MPEG_BITRATES = {
    (True, 1): (0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448),
    (True, 2): (0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384),
    (True, 3): (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320),
    (False, 1): (0, 32, 48, 56, 64, 80, 96, 112, 128, 144, 160, 176, 192, 224, 256),
    (False, 2): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
    (False, 3): (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160),
}

# Sample rates by the header's version field: 11 is MPEG-1, 10 MPEG-2, 00 the
# unofficial MPEG-2.5 (8 and 11 kHz, which the bundled ffmpeg converts). 01 is
# reserved, and absent here so that it is refused.
_MPEG_RATES = {
    0b11: (44100, 48000, 32000),
    0b10: (22050, 24000, 16000),
    0b00: (11025, 12000, 8000),
}

# ADTS sampling_frequency_index 13-15 have no rate, and ffmpeg's ADTS parser
# refuses them.
_ADTS_RATE_INDICES = 13

# The longest frame header read below (ADTS; MPEG audio needs 4).
_FRAME_HEADER_BYTES = 7


def clean_message_id(msg_id) -> str:
    """The part of a WhatsApp message id that media files are named after.

    WPPConnect hands ids in two shapes: a bare `3EB0...`, and the compound
    `false_<jid>_<id>` (or `true_<jid>_<id>` for our own) that carries the chat
    it belongs to. The media downloader keeps only the last component — the
    third one when there is a third, the last otherwise — and that is the name
    on disk. See the module docstring for why this is not
    `local_media_cache_paths()`'s rule.
    """
    text = str(msg_id or "")
    if "_" not in text:
        return text
    parts = text.split("_")
    return parts[2] if len(parts) > 2 else parts[-1]


def is_transcribable(msg) -> bool:
    """Whether this message holds speech a transcription could read.

    The reasoning for the set it accepts is in TRANSCRIBABLE_TYPES.
    """
    if not isinstance(msg, dict):
        return False
    msg_type = msg.get("messageType") or ""
    if msg_type == "audioMessage":
        return True
    if msg_type == "videoMessage":
        return not is_gif(msg)
    if msg_type != "documentMessage":
        return False
    return _message_mimetype(msg).startswith(("audio/", "video/"))


def is_video(msg) -> bool:
    """Whether the speech of this message is a video's sound track: a video
    message, or a document whose mimetype is video/*."""
    if not isinstance(msg, dict):
        return False
    msg_type = msg.get("messageType") or ""
    if msg_type == "videoMessage":
        return True
    return msg_type == "documentMessage" and _message_mimetype(msg).startswith("video/")


def is_gif(msg) -> bool:
    """A video message WhatsApp plays as a silent, looping GIF."""
    payload = msg.get("message") if isinstance(msg, dict) else None
    video = payload.get("videoMessage") if isinstance(payload, dict) else None
    return isinstance(video, dict) and bool(video.get("gifPlayback"))


def media_seconds(msg) -> int:
    """The recording's length as WhatsApp states it (audio or video), 0 when it
    does not."""
    payload = msg.get("message") if isinstance(msg, dict) else None
    if not isinstance(payload, dict):
        return 0
    inner = payload.get(msg.get("messageType") or "")
    if not isinstance(inner, dict):
        return 0
    try:
        return max(0, int(inner.get("seconds") or 0))
    except (TypeError, ValueError):
        return 0


def _message_mimetype(msg) -> str:
    """The message's own mimetype, lowercased and without its parameters.

    Read from the same three places `_resolve_media_filename()` reads it, in
    the same order: WPPConnect puts it on the inner payload, on the record
    itself or under `mediaData` depending on which event produced it, and a
    document that arrived through the one place this did not look would be
    treated as if it had no mimetype at all.
    """
    if not isinstance(msg, dict):
        return ""
    payload = msg.get("message")
    inner = payload.get(msg.get("messageType") or "") if isinstance(payload, dict) else None
    if not isinstance(inner, dict):
        inner = {}
    media_data = msg.get("mediaData") if isinstance(msg.get("mediaData"), dict) else {}
    mimetype = inner.get("mimetype") or msg.get("mimetype") or media_data.get("mimetype") or ""
    return str(mimetype).split(";")[0].strip().lower()


def cached_media_path(msg, voice_dir, media_dir):
    """Where this message's media sits once it has been downloaded, or None.

    The two folders and the two suffixes are `_save_message_media()`'s: an
    `audioMessage` is written as `voice_messages/<id>.msv`, everything else as
    `media/<id>.wzmedia`. None means the record carries no id to look up — not
    that the file is absent, which only the filesystem can say.
    """
    if not isinstance(msg, dict):
        return None
    key = msg.get("key") if isinstance(msg.get("key"), dict) else {}
    clean = clean_message_id(key.get("id"))
    if not clean:
        return None
    if msg.get("messageType") == "audioMessage":
        return os.path.join(voice_dir, f"{clean}.msv")
    return os.path.join(media_dir, f"{clean}.wzmedia")


def _frame_header(data, offset):
    """(extension, frame length, identity) of the frame header at `offset`, or None.

    For an MP3 carrying no ID3 tag, and for ADTS AAC — the two formats that
    have no container, only a stream of frames. Read field by field rather
    than matched against a list of byte pairs: a list is what this used to be,
    and it kept being short, because every combination of MPEG version (1, 2,
    2.5) and CRC flag is a different second byte, and so is ADTS's CRC flag.
    Each one left out was a file ffmpeg converts being refused here.

    Both open with the same 11 set bits. The two-bit *layer* field after them
    separates them: 00 is reserved in MPEG audio, and it is exactly what ADTS
    writes, behind a 12-bit sync. Any other layer is MPEG audio — layers I and
    II included, which ffmpeg's mp3 demuxer reads as well. What is refused
    below is what ffmpeg's own `ff_mpa_check_header()` and ADTS parser refuse;
    accepting that would only move the refusal into ffmpeg's stderr, which is
    the thing the sniff exists to avoid.

    The caller then demands a *second* header where this one says the next
    frame begins, and that is the part that matters for the `.msv` holding raw
    PCM: its first sample can spell a perfectly valid header — two bytes out of
    a whole recording — and measured against the bundled ffmpeg, pink noise
    behind a fake MPEG header came back as the generic FFMPEG_FAILED instead of
    UNSUPPORTED_AUDIO_FORMAT. A second header, at the one offset the first
    predicts and with the same version, layer and rate, is what ffmpeg's own
    probe looks for too, and is not something noise produces by accident.
    `identity` is what the two must share.
    """
    b = bytes(data[offset:offset + _FRAME_HEADER_BYTES])
    if len(b) < 4 or b[0] != 0xFF or (b[1] & 0xE0) != 0xE0:
        return None
    layer_bits = (b[1] >> 1) & 0x3
    if layer_bits == 0:
        rate_index = (b[2] >> 2) & 0xF
        if (b[1] & 0xF0) != 0xF0 or rate_index >= _ADTS_RATE_INDICES or len(b) < 7:
            return None
        # frame_length counts the header itself, which is 7 bytes, or 9 when
        # the protection_absent bit is clear and a CRC follows it.
        length = ((b[3] & 0x3) << 11) | (b[4] << 3) | (b[5] >> 5)
        if length < (7 if b[1] & 0x1 else 9):
            return None
        return ".aac", length, (b[1] & 0xFE, rate_index)
    version = (b[1] >> 3) & 0x3
    bitrate_index = b[2] >> 4
    rate_index = (b[2] >> 2) & 0x3
    if version not in _MPEG_RATES or bitrate_index in (0, 0xF) or rate_index == 3:
        return None
    layer = 4 - layer_bits
    mpeg1 = version == 0b11
    bitrate = _MPEG_BITRATES[(mpeg1, layer)][bitrate_index] * 1000
    rate = _MPEG_RATES[version][rate_index]
    padding = (b[2] >> 1) & 0x1
    if layer == 1:
        length = (12 * bitrate // rate + padding) * 4
    elif layer == 3 and not mpeg1:
        length = 72 * bitrate // rate + padding
    else:
        length = 144 * bitrate // rate + padding
    # The CRC bit is left out of the identity: the header carries it frame by
    # frame, so nothing obliges it to hold across the stream.
    return ".mp3", length, (b[1] & 0xFE, rate_index)


def sniff_extension(header):
    """The file extension these leading bytes identify, or None.

    None is a real answer and the caller must treat it as one: it is the `.msv`
    holding raw PCM, and the module docstring explains both what refusing it
    buys and what it does not. `_toggle_playback()` falls back to the mimetype's
    extension at this point; a transcription may not, because that fallback is
    what turns an actionable "this format was not recognised" into whichever
    sentence ffmpeg's stderr happens to earn.

    Every signature here was confirmed to convert through `audio_prep`'s exact
    ffmpeg command before it was added — a format the bundled ffmpeg opens has
    no business being refused. Exact prefixes first, then the `ftyp` substring
    search, which is the only one that can match bytes it did not begin with.
    `header` may be the whole file: only a bare MPEG/ADTS frame stream reads
    past the first 32 bytes, and then only the one header where its second
    frame begins (see `_frame_header()`).
    """
    if not header:
        return None
    head = bytes(header[:_SNIFF_BYTES])
    if head.startswith(b"RIFF"):
        return ".wav"
    if head.startswith(b"OggS"):
        return ".ogg"
    if head.startswith(b"ID3"):
        return ".mp3"
    first = _frame_header(header, 0)
    if first is not None:
        extension, length, identity = first
        following = _frame_header(header, length)
        if following is not None and following[2] == identity:
            return extension
        if len(header) < length + _FRAME_HEADER_BYTES:
            # Too short to hold a second header, so there is nothing to
            # demand. Only a file under ~8 KB gets here, and a raw PCM voice
            # note is seconds of audio — tens of kilobytes at the very least.
            return extension
    if head.startswith(b"fLaC"):
        return ".flac"
    if head.startswith(b"\x1aE\xdf\xa3"):
        # EBML, which WebM and Matroska share; one ffmpeg demuxer reads both,
        # and the DocType that tells them apart sits at offset 27 and runs past
        # this window for "matroska". So both are named .webm — the suffix is a
        # hint for the tools around ffmpeg, and ffmpeg itself reads the content.
        return ".webm"
    if head.startswith(b"#!AMR"):
        # Covers AMR-WB too ("#!AMR-WB\n"), which shares the prefix. WhatsApp
        # used AMR for voice notes for years, so these are still in circulation.
        return ".amr"
    if head.startswith(b"FORM") and head[8:12] in (b"AIFF", b"AIFC"):
        # `FORM` alone is IFF, not necessarily audio — the type at offset 8 is
        # what makes it an AIFF, and AIFC is the compressed flavour.
        return ".aiff"
    if head.startswith(b"\x30\x26\xb2\x75"):
        return ".wma"
    if b"ftyp" in head:
        return ".m4a"
    if head[4:8] in (b"moov", b"mdat", b"wide", b"free", b"skip"):
        # A QuickTime/MP4 file that does not open with an `ftyp` box — older
        # .mov files from phones and cameras start straight with one of these.
        # The same ffmpeg demuxer reads it; only the video ones arrive here.
        return ".mov"
    return None


def decrypt_to_temp(media_path, key, decrypt=None) -> str:
    """Decrypt a cached media file into a temporary, and return its path.

    The suffix is whatever `sniff_extension()` recognised, because ffmpeg picks
    its demuxer by content but several of the tools around it do not, and a
    file named for what it actually is costs nothing.

    The caller owns the file that comes back and must call `discard_temp()` on
    it — including when a failed GPU run hands it to a re-run on the processor,
    which is why this is not only a context manager (see `decrypted_audio()`).
    """
    decrypt = decrypt or decrypt_bytes

    try:
        size = os.path.getsize(media_path) if media_path else 0
    except OSError:
        size = 0
    if not size:
        # Absent, or the zero-byte placeholder a download in flight leaves
        # behind — the same reading, and the same code, as audio_prep's own
        # first check: the user's answer is to wait, not to report a fault.
        raise errors.TranscriptionError(
            errors.MEDIA_NOT_DOWNLOADED, f"{size} bytes on disk"
        )

    # Reading and decrypting are two separate `try` blocks, and the split is
    # what makes the OSError branch below honest. Its `detail` keeps
    # `strerror`, which is only safe for an OSError the *operating system*
    # raised: there it is the system's own sentence ("Permission denied") and
    # the path lives in `filename`, which is dropped. The injectable `decrypt`
    # can raise an OSError too, built from whatever text it likes — one
    # quoting the path was measured reaching the log through `strerror` when
    # both calls shared a block. Kept apart, only `open()`/`read()` reach the
    # branch that trusts `strerror`; everything `decrypt` raises is reduced to
    # its type name.
    try:
        with open(media_path, "rb") as handle:
            data = handle.read()
    except MemoryError:
        raise _out_of_memory() from None
    except OSError as exc:
        # The bytes could not be read off the disk at all — a removable drive
        # pulled mid-read, an antivirus holding the file, a path too long.
        #
        # Built from the numbers and never from `str(exc)` or `exc.filename`:
        # an OSError raised by `open()` carries the path in both, the file is
        # named after the message id, and `detail` is the half that goes to
        # the log. `strerror` is the system's own sentence ("No such file or
        # directory") and holds no path — true of what `open()` and `read()`
        # raise, which is all that can reach this branch (see above); an
        # OSError raised with a bare message has neither number, and loses its
        # text here on purpose — this module cannot vouch for what that text
        # contains.
        #
        # A file that vanished between `getsize()` and `open()` — the user
        # deleting the media just as the transcription starts — is the state
        # the size check above already answers, so it gets the same answer
        # rather than being called a damaged recording.
        code = (errors.MEDIA_NOT_DOWNLOADED if isinstance(exc, FileNotFoundError)
                else errors.AUDIO_INCOMPLETE)
        raise errors.TranscriptionError(
            code,
            f"read failed: {type(exc).__name__}: errno={exc.errno}"
            f" winerror={getattr(exc, 'winerror', None)} strerror={exc.strerror}",
        ) from None

    try:
        plain = decrypt(data, key)
    except errors.TranscriptionError:
        raise
    except MemoryError:
        raise _out_of_memory() from None
    except Exception as exc:
        # Fernet refuses a file that was truncated mid-write, one written under
        # a different secret.key, and one that was never encrypted at all.
        # AUDIO_INCOMPLETE over the alternatives because its sentence — "the
        # audio file is incomplete or damaged" — is true of every one of them,
        # and because the other candidates each send the user somewhere wrong:
        # MEDIA_NOT_DOWNLOADED tells them to wait for a download that already
        # finished, and UNSUPPORTED_AUDIO_FORMAT blames a format nothing has
        # managed to look at yet. The technical reason goes in `detail`, which
        # is the half that never reaches the user — and which is the only thing
        # separating these four cases, since a fifth error code would cost five
        # translations to say something only a log reader can use.
        #
        # The type name only, never the message. Fernet's InvalidToken has an
        # empty one, so in production the message adds nothing; and `decrypt`
        # is injectable, so the text of whatever it raises is not this
        # module's to vouch for — one quoting a path would put the message id
        # in the log. The type is also what tells the cases apart (InvalidToken
        # against, say, a TypeError from a malformed key).
        #
        # `from None` here and in every branch above: the original exception
        # is exactly what was kept out of `detail`, and chained as `__cause__`
        # it would reach the log whole the first time anything logs this error
        # with its traceback. (It still sits in `__context__` — `from None`
        # only stops the traceback printing it — so nothing may walk the chain
        # by hand to log it.)
        raise errors.TranscriptionError(
            errors.AUDIO_INCOMPLETE, f"decrypt failed: {type(exc).__name__}"
        ) from None

    extension = sniff_extension(plain)
    if extension is None:
        raise errors.TranscriptionError(
            errors.UNSUPPORTED_AUDIO_FORMAT, "no recognised container signature"
        )

    # A random name, never the message's: the file on disk is named after the
    # message id, and %TEMP% is not a private place.
    temp_path = None
    try:
        handle, temp_path = tempfile.mkstemp(prefix="winzapp-audio-", suffix=extension)
        with os.fdopen(handle, "wb") as out:
            out.write(plain)
    except OSError as exc:
        # A partly written temporary is decrypted audio of a private
        # conversation sitting in %TEMP% with nobody left to delete it.
        discard_temp(temp_path)
        # Decrypting a 2 GB audio document into a nearly full system drive is
        # an ordinary way for this to happen, and it must reach the user as a
        # sentence: an OSError escaping from here lands in the caller's
        # catch-all, which logs its text — and the text of an OSError about
        # this file quotes the temporary's path, whose folder carries the
        # Windows user name. So the detail is numbers and the type only, never
        # `filename`, and the code says what the user can act on: a full disk
        # is TEMP_NO_DISK_SPACE (not the downloads' NO_DISK_SPACE — see
        # errors.py), and anything else here (a %TEMP% that cannot be
        # written at all) is nobody's audio at fault, hence BACKEND_ERROR
        # rather than a sentence blaming the recording.
        raise errors.TranscriptionError(
            errors.TEMP_NO_DISK_SPACE if _is_disk_full(exc) else errors.BACKEND_ERROR,
            f"temporary write failed: {type(exc).__name__}: errno={exc.errno}"
            f" winerror={getattr(exc, 'winerror', None)}",
        ) from None
    except BaseException:
        discard_temp(temp_path)
        raise
    return temp_path


# ERROR_DISK_FULL and ERROR_HANDLE_DISK_FULL. Python maps both to ENOSPC on
# its own, but only when the OSError was raised with the winerror argument —
# checking both spellings costs nothing and does not depend on that.
_WINERROR_DISK_FULL = (112, 39)


def _is_disk_full(exc) -> bool:
    return (getattr(exc, "errno", None) == errno.ENOSPC
            or getattr(exc, "winerror", None) in _WINERROR_DISK_FULL)


def _out_of_memory():
    """The error for a file too large to hold in memory, read or decrypted.

    The whole file is read and decrypted in memory, and Fernet's internal
    base64 step peaks at roughly three times its size — an audio document may
    be 2 GB, so this is reachable on a real machine rather than theoretical.
    The file is perfectly fine, and every other branch describes one that is
    not, so it gets its own `detail`: sending a user to re-download an intact
    2 GB recording is a long, wasted trip. `str(MemoryError())` is empty,
    hence the spelled-out text — and the caller raises it `from None`, because
    a MemoryError raised with a message is not this module's to vouch for.
    """
    return errors.TranscriptionError(
        errors.AUDIO_INCOMPLETE, "MemoryError: not enough memory to decrypt the file"
    )


def discard_temp(path) -> None:
    """Delete a temporary written by `decrypt_to_temp()`. Never raises.

    Silent on failure, and silent in the log either way: this module logs
    nothing (a test pins it), so a leftover is for temp_sweep to remove at the
    next start (once it is a day old).
    """
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


@contextlib.contextmanager
def decrypted_audio(media_path, key, decrypt=None):
    """`decrypt_to_temp()` with the file removed however the block ends.

    For callers that will never pass the file on. A run that may be redone on
    the processor keeps the file past its own end, so it calls
    `decrypt_to_temp()` and `discard_temp()` itself.
    """
    temp_path = decrypt_to_temp(media_path, key, decrypt=decrypt)
    try:
        yield temp_path
    finally:
        discard_temp(temp_path)
