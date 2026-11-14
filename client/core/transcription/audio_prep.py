"""Turning whatever WhatsApp stored into the one thing Whisper wants.

Whisper's encoder consumes 16 kHz mono PCM, and a voice message can be OGG
Opus, OGG Vorbis, MP3, M4A, WAV or an MP4 with an audio track — so every run
starts with a conversion. ffmpeg does it, and ffmpeg's *path* is a parameter:
`MainWindow._find_api_ffmpeg()` (main_window/sending.py) already knows where
the bundled binary is, and a core module importing main to ask would be a
cycle through every module MainWindow is built from. The subprocess details
(CREATE_NO_WINDOW, stderr kept and decoded with `errors="replace"`) follow
core/audio_transcode.py, which has been converting audio here for far longer.

Two decisions carry most of the weight:

* **The four audio failures are four different sentences to the user**, so they
  are distinguished as far as ffmpeg genuinely allows and no further. "There is
  nothing to read" is decided before ffmpeg runs at all; a truncated file is
  recognised from the markers only a truncated file produces; anything ffmpeg
  simply could not parse is an unsupported format. Everything else is
  FFMPEG_FAILED, on purpose: a wrong diagnosis sends a blind user to fix
  something that is not broken, while the generic one at least says the audio
  could not be converted. Truncation is checked *before* unrecognised, because
  a file cut in half usually prints both kinds of line.

* **ffmpeg's own log names the file it read, and that name is the message id.**
  The issue forbids the log from carrying it, so the stderr is scrubbed of our
  own paths before it can reach an error detail. The technical detail is worth
  keeping; the name identifies the message and, through it, the conversation.

The converted file is a temporary that is always removed — on success by the
caller (`discard()`), and on every failure and cancellation by this module
itself. A run that hands the file on instead of finishing with it, so that a
transcription which failed on the GPU can be redone on the CPU without
converting the audio again, makes the receiver the one who calls `discard()`.
It is written under a random name rather than the message's, for the same
privacy reason.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass

from core.transcription import _fileops, errors
from core.transcription._fileops import check_cancel, unlink

TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1

# How often the conversion is checked on: it bounds how long a cancellation
# waits, and a wx user pressing Escape is the only thing waiting on it.
_POLL_SECONDS = 0.1

# A ceiling, not a schedule. Sized like audio_transcode.prepare_audio_for_
# whatsapp()'s: generous per megabyte, because a phone recording an hour of
# audio is a real thing and a conversion killed at 90% costs the user the whole
# wait a second time.
_MIN_TIMEOUT_SECONDS = 120
_MAX_TIMEOUT_SECONDS = 1800
_TIMEOUT_BYTES_PER_SECOND = 512 * 1024

# Only a truncated file prints these. Kept apart from the unrecognised markers
# and checked first: a file cut in half often prints "Invalid data found"
# further down as well, and whichever table is checked second never wins.
_TRUNCATED_MARKERS = (
    "moov atom not found",
    "truncat",
    "partial file",
    "premature end",
    "unexpected end of file",
    "incomplete frame",
)

# The disk under %TEMP% filled while ffmpeg was writing the WAV. That file is
# far larger than the note it comes from (~115 MB per hour of audio at 16 kHz
# mono, against a few MB of Opus), so a nearly full system drive lets the
# decryption through and stops here. ffmpeg reports the C library's
# strerror(ENOSPC) — "No space left on device" — and a Windows build that
# surfaces the system message says one of the other two (ERROR_DISK_FULL,
# ERROR_HANDLE_DISK_FULL). Checked before everything else: the write failing
# half way can also print "partial file", and blaming the recording would send
# the user to fix audio that is fine.
_NO_SPACE_MARKERS = (
    "no space left on device",
    "not enough space on the disk",
    "the disk is full",
)

# ffmpeg read the bytes and could not make a stream of them.
_UNRECOGNISED_MARKERS = (
    "invalid data found when processing input",
    "unknown format",
    "could not find codec parameters",
    "decoder not found",
    "does not contain any stream",
    "unsupported codec",
)


@dataclass(frozen=True)
class PreparedAudio:
    """The converted file, and how long it turned out to be."""

    path: str
    duration_seconds: float


def prepare_audio(ffmpeg, source_path, should_cancel=None) -> PreparedAudio:
    """Convert `source_path` to PCM 16 kHz mono, or raise the right code."""
    check_cancel(should_cancel)

    try:
        source_bytes = os.path.getsize(source_path)
    except OSError:
        source_bytes = 0
    if not source_bytes:
        # No file, or a zero-byte placeholder: WhatsApp's own media download has
        # not finished, or never started. Deliberately not FFMPEG_FAILED — the
        # user's answer is to wait, not to report a broken installation.
        raise errors.TranscriptionError(
            errors.MEDIA_NOT_DOWNLOADED, f"{source_bytes} bytes on disk"
        )

    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise errors.TranscriptionError(
            errors.FFMPEG_FAILED, "ffmpeg was not found next to the API"
        )

    # A random name, never the source's: the media file is named after the
    # WhatsApp message id, and %TEMP% is not a private place.
    handle, output_path = tempfile.mkstemp(prefix="winzapp-transcribe-", suffix=".wav")
    os.close(handle)
    try:
        returncode, stderr_text = _run_ffmpeg(
            ffmpeg, source_path, output_path, source_bytes, should_cancel
        )
        if returncode != 0:
            raise _classify_ffmpeg_failure(returncode, stderr_text)
        duration = _wav_duration(output_path)
        if duration <= 0:
            # ffmpeg was happy and produced no samples: the container was
            # readable and what it held was not. "Damaged" is the closest of
            # the four, and the only one whose advice (this recording is not
            # usable) is true here.
            raise errors.TranscriptionError(
                errors.AUDIO_INCOMPLETE, "the conversion produced no audio"
            )
    except BaseException:
        # Every exit but the successful one goes through here, cancellation
        # included: a run abandoned half way must not leave a WAV of an hour of
        # audio behind in %TEMP%. BaseException rather than Exception because a
        # KeyboardInterrupt on a developer's machine leaves the same file.
        unlink(output_path)
        raise

    logging.info(
        "[transcription] prepared %.1fs of audio for transcription", duration
    )
    return PreparedAudio(path=output_path, duration_seconds=duration)


def discard(prepared) -> None:
    """Remove a prepared file. Safe to call twice, and on None."""
    if prepared is None:
        return
    path = getattr(prepared, "path", None)
    if path and not unlink(path) and os.path.exists(path):
        # Basename only: the full path has the user's name in it.
        leftover = os.path.basename(path)
        logging.warning("[transcription] could not remove the converted audio %s",
                        leftover)


def _run_ffmpeg(ffmpeg, source_path, output_path, source_bytes, should_cancel):
    """(returncode, scrubbed stderr) — and a killed process on cancellation."""
    command = [
        ffmpeg, "-nostdin", "-y",
        "-i", source_path,
        "-vn",
        "-ac", str(TARGET_CHANNELS),
        "-ar", str(TARGET_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        "-f", "wav",
        output_path,
    ]
    creationflags = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    deadline = time.monotonic() + _timeout_for(source_bytes)
    # stderr into a temporary file rather than a pipe: this waits in slices so
    # that a cancellation is noticed, instead of calling communicate(), and a
    # pipe nobody is draining deadlocks ffmpeg as soon as the OS buffer fills —
    # which a file with an odd stream fills with warnings.
    with tempfile.TemporaryFile() as stderr_file:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise errors.TranscriptionError(
                errors.FFMPEG_FAILED, f"{type(exc).__name__}: {exc}"
            ) from exc

        try:
            while True:
                try:
                    returncode = process.wait(timeout=_POLL_SECONDS)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if should_cancel is not None and should_cancel():
                    raise errors.TranscriptionError(
                        errors.CANCELLED, "cancelled while converting the audio"
                    )
                if time.monotonic() > deadline:
                    raise errors.TranscriptionError(
                        errors.FFMPEG_FAILED, "the conversion timed out"
                    )
        except BaseException:
            # Killed, not merely abandoned: an orphaned ffmpeg keeps the media
            # file open (so nothing can clean it up) and keeps burning a core
            # for as long as the app runs.
            _fileops.kill_process(process, "ffmpeg")
            raise

        stderr_file.seek(0)
        stderr_text = stderr_file.read().decode("utf-8", errors="replace")

    return returncode, _scrub(stderr_text, source_path, output_path)


def _classify_ffmpeg_failure(returncode, stderr_text):
    """The error a non-zero ffmpeg exit deserves."""
    message = (stderr_text or "").lower()
    tail = (stderr_text or "").strip()[-800:]
    if any(marker in message for marker in _NO_SPACE_MARKERS):
        return errors.TranscriptionError(errors.TEMP_NO_DISK_SPACE, f"rc={returncode}: {tail}")
    if any(marker in message for marker in _TRUNCATED_MARKERS):
        return errors.TranscriptionError(errors.AUDIO_INCOMPLETE, tail)
    if has_picture_but_no_sound(message):
        return errors.TranscriptionError(errors.NO_AUDIO_TRACK, tail)
    if any(marker in message for marker in _UNRECOGNISED_MARKERS):
        return errors.TranscriptionError(errors.UNSUPPORTED_AUDIO_FORMAT, tail)
    return errors.TranscriptionError(errors.FFMPEG_FAILED, f"rc={returncode}: {tail}")


_STREAM_LINE = re.compile(r"stream #\d+:\d+[^\n]*?: (video|audio):")


def has_picture_but_no_sound(stderr_text) -> bool:
    """Whether ffmpeg's log describes an input with a video stream and no audio
    stream — a silent video. ffmpeg then fails with "does not contain any
    stream" (the picture was dropped by -vn and nothing was left), which would
    otherwise read as an unrecognised format."""
    kinds = set(_STREAM_LINE.findall((stderr_text or "").lower()))
    return "video" in kinds and "audio" not in kinds


def _wav_duration(path) -> float:
    """Seconds in the converted file, read from its own header.

    Exact and free, where an ffprobe call would be a second process. A file we
    wrote ourselves that will not open is our failure, not the source's, which
    is why it is FFMPEG_FAILED rather than one of the audio codes.
    """
    try:
        with contextlib.closing(wave.open(path, "rb")) as handle:
            rate = handle.getframerate() or TARGET_SAMPLE_RATE
            return handle.getnframes() / float(rate)
    except Exception as exc:
        raise errors.TranscriptionError(
            errors.FFMPEG_FAILED, f"unreadable output: {type(exc).__name__}: {exc}"
        ) from exc


def read_waveform(path):
    """The prepared WAV as the float32 signal Whisper consumes, or None.

    faster-whisper given a *path* decodes it with PyAV, and a PyAV older than
    the one it was written against fails with "open() got an unexpected
    keyword argument 'metadata_errors'" — after the model loaded, so the user
    heard only "an internal error". The file is ours (PCM s16le, 16 kHz, mono,
    see `_run_ffmpeg()`), so reading it here takes PyAV out of the path
    entirely. None means "could not, let the backend try the path itself":
    this is an optimisation of the hand-over, never a new way to fail.
    """
    try:
        import numpy

        with contextlib.closing(wave.open(path, "rb")) as handle:
            if (
                handle.getsampwidth() != 2
                or handle.getnchannels() != TARGET_CHANNELS
                or handle.getframerate() != TARGET_SAMPLE_RATE
            ):
                return None
            frames = handle.readframes(handle.getnframes())
        samples = numpy.frombuffer(frames, dtype="<i2").astype(numpy.float32)
        # In place: one float32 copy, not two (a video's sound track is long).
        samples /= 32768.0
        return samples
    except Exception:
        return None


def _scrub(text, *paths) -> str:
    """ffmpeg's log with our own file names taken out of it.

    ffmpeg echoes every path it was handed ("Input #0, ogg, from '...'"), and
    the media file's name is the WhatsApp message id — which the issue forbids
    the log to carry, because it identifies the message and, through it, the
    conversation. The rest of the line is exactly the technical detail worth
    keeping.
    """
    scrubbed = text or ""
    for path in paths:
        if not path:
            continue
        for form in (path, os.path.basename(path)):
            if form:
                scrubbed = scrubbed.replace(form, "<audio>")
    return scrubbed


def _timeout_for(source_bytes) -> float:
    return float(
        max(
            _MIN_TIMEOUT_SECONDS,
            min(_MAX_TIMEOUT_SECONDS, source_bytes // _TIMEOUT_BYTES_PER_SECOND),
        )
    )
