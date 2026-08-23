"""Audio format conversion helpers used by the in-app player."""

import logging
import mimetypes
import os
import subprocess
import sys


def transcode_audio_to_wav(ffmpeg: str, source_path: str) -> str | None:
    """Convert any ffmpeg-readable audio stream to PCM WAV for reliable BASS playback.

    Originally MP4/M4A-only (hence the old name), this is also the fallback for
    any other container BASS can't open directly — notably an OGG whose codec
    isn't Opus (or whose bassopus.dll plugin failed to register), which BASS
    rejects with error 41 "unsupported file format" for both the decode+Tempo
    stream and the plain direct stream. Re-encoding through ffmpeg sidesteps
    BASS's codec support entirely rather than depending on it.
    """
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return None

    output_path = source_path + ".wav"
    creationflags = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", source_path, "-vn",
                "-c:a", "pcm_s16le", output_path,
            ],
            capture_output=True,
            timeout=60,
            creationflags=creationflags,
        )
        if (
            result.returncode == 0
            and os.path.isfile(output_path)
            and os.path.getsize(output_path) > 44
        ):
            return output_path
        logging.error(
            "[UI Audio Playback] audio→WAV conversion failed (rc=%s): %s",
            result.returncode,
            (result.stderr or b"").decode("utf-8", errors="replace")[-800:],
        )
    except Exception:
        logging.exception("[UI Audio Playback] audio→WAV conversion failed")

    try:
        os.unlink(output_path)
    except OSError:
        pass
    return None


def prepare_audio_for_whatsapp(ffmpeg: str, source_path: str) -> tuple[str, str] | None:
    """Return a WhatsApp-compatible audio path and MIME type.

    WhatsApp accepts OGG audio through sendFile only when its stream is Opus.
    Generic ``.ogg`` files may contain Vorbis, which WPPConnect rejects with
    ``InvalidMediaCheckRepairFailedType``. Existing OGG/Opus files pass through.
    """
    mime = mimetypes.guess_type(source_path)[0] or "application/octet-stream"
    if os.path.splitext(source_path)[1].lower() != ".ogg":
        return source_path, mime

    try:
        with open(source_path, "rb") as source:
            header = source.read(4096)
    except OSError:
        return None
    if b"OpusHead" in header:
        return source_path, "audio/ogg; codecs=opus"
    if not ffmpeg or not os.path.isfile(ffmpeg):
        return None

    output_path = source_path + ".opus.ogg"
    creationflags = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", source_path, "-vn", "-ac", "1",
                "-c:a", "libopus", "-b:a", "64k", output_path,
            ],
            capture_output=True,
            timeout=120,
            creationflags=creationflags,
        )
        if (
            result.returncode == 0
            and os.path.isfile(output_path)
            and os.path.getsize(output_path) > 0
        ):
            return output_path, "audio/ogg; codecs=opus"
        logging.error(
            "[send_media] OGG/Vorbis to OGG/Opus conversion failed (rc=%s): %s",
            result.returncode,
            (result.stderr or b"").decode("utf-8", errors="replace")[-800:],
        )
    except Exception:
        logging.exception("[send_media] OGG/Vorbis to OGG/Opus conversion failed")
    try:
        os.unlink(output_path)
    except OSError:
        pass
    return None
