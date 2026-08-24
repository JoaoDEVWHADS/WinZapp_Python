"""Video format conversion helpers used before uploading a video message."""

import logging
import mimetypes
import os
import re
import subprocess
import sys


# Codecs WhatsApp's own video pipeline accepts inside an MP4 container.
# Anything else has to be re-encoded before upload — see
# prepare_video_for_whatsapp below.
_ACCEPTED_VIDEO_CODECS = {"h264"}
_ACCEPTED_AUDIO_CODECS = {"aac"}

# "Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p, ..."
# ffmpeg prints one of these per stream; the codec name is the first token
# after "Video:"/"Audio:".
_STREAM_RE = re.compile(
    r"^\s*Stream #\d+:\d+.*?:\s*(Video|Audio):\s*([A-Za-z0-9_]+)",
    re.MULTILINE,
)


def probe_stream_codecs(ffmpeg_stderr: str) -> tuple[set[str], set[str]]:
    """Parse ``ffmpeg -i <file>`` stderr into ``(video_codecs, audio_codecs)``.

    ffprobe is the natural tool for this and WinZapp does not bundle it —
    but plain ``ffmpeg -i`` with no output file prints exactly the same
    stream table to stderr before exiting non-zero ("At least one output
    file must be specified"), which is all this needs. Pure function so the
    parsing is unit-testable without running ffmpeg.
    """
    video: set[str] = set()
    audio: set[str] = set()
    for kind, codec in _STREAM_RE.findall(ffmpeg_stderr or ""):
        (video if kind == "Video" else audio).add(codec.lower())
    return video, audio


def _probe(ffmpeg: str, source_path: str) -> tuple[set[str], set[str]] | None:
    """Run ``ffmpeg -i`` on *source_path* and return its stream codecs.

    ``None`` means the probe itself could not be trusted (ffmpeg missing,
    crashed, printed nothing recognisable) — callers treat that as "unknown",
    never as "no streams".
    """
    creationflags = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [ffmpeg, "-hide_banner", "-i", source_path],
            capture_output=True,
            timeout=60,
            creationflags=creationflags,
        )
    except Exception:
        logging.exception("[send_media] video codec probe failed")
        return None
    stderr = (result.stderr or b"").decode("utf-8", errors="replace")
    video, audio = probe_stream_codecs(stderr)
    if not video and not audio:
        logging.warning(
            "[send_media] video codec probe produced no stream info for %s: %s",
            source_path, stderr[-400:],
        )
        return None
    return video, audio


def needs_transcode(extension: str, codecs: tuple[set[str], set[str]] | None) -> bool:
    """Whether a file has to be re-encoded before WhatsApp will accept it.

    *extension* is the source file's lowercase extension (".mp4", ".mkv",
    ...) and *codecs* is what _probe() returned, or ``None`` when the probe
    could not tell.

    A non-MP4 container always needs converting. An MP4 needs converting
    when its streams are anything other than H.264 video / AAC audio — an
    MP4 is just a container, and an iPhone's HEVC or a modern
    screen-recorder's AV1 sits inside one exactly as happily as H.264 does.
    When the probe fails, an .mp4 is passed through unchanged: that is the
    behaviour this function replaced (extension trusted outright) and it is
    the safe side — a needless re-encode of every video is worse than the
    occasional upload that still has to be retried.
    """
    if extension != ".mp4":
        return True
    if codecs is None:
        return False
    video, audio = codecs
    if video and not video <= _ACCEPTED_VIDEO_CODECS:
        return True
    # No audio track at all is fine — WhatsApp accepts a silent video.
    if audio and not audio <= _ACCEPTED_AUDIO_CODECS:
        return True
    return False


def prepare_video_for_whatsapp(ffmpeg: str, source_path: str) -> tuple[str, str] | None:
    """Return a WhatsApp-compatible video path and MIME type.

    WhatsApp's video pipeline expects an MP4 container carrying H.264 video
    and AAC audio. Unlike audio (see core/audio_transcode.py's
    prepare_audio_for_whatsapp — the exact same idea, applied earlier),
    send_media_attachment() never transcoded video at all: any other
    container (.mkv, .webm, .avi, a phone's .mov, ...) or codec (VP9/Opus,
    HEVC, ...) went to WPPConnect's upload exactly as picked, which then
    failed server-side with a bare, unexplained 500 — reported live as
    "erro 500 ao enviar vídeos em diferentes formatos".

    The container alone is not enough to decide: an .mp4 is only a box, and
    the ones an iPhone or a modern screen recorder produce routinely carry
    HEVC/AV1 inside it, which fails identically. This used to trust the
    .mp4 extension outright (ffprobe, the obvious way to check, is not
    bundled), so exactly those files kept reproducing the 500 the rest of
    this function exists to prevent. The codecs are now read out of plain
    ``ffmpeg -i`` instead — see probe_stream_codecs().
    """
    mime = mimetypes.guess_type(source_path)[0] or "video/mp4"
    extension = os.path.splitext(source_path)[1].lower()
    have_ffmpeg = bool(ffmpeg) and os.path.isfile(ffmpeg)
    # Only an .mp4 is worth probing: every other container has to be
    # converted whatever is inside it, so spending an ffmpeg run to confirm
    # that would just slow the send down.
    if extension == ".mp4":
        codecs = _probe(ffmpeg, source_path) if have_ffmpeg else None
        if not needs_transcode(extension, codecs):
            return source_path, mime
    if not have_ffmpeg:
        return None

    output_path = source_path + ".whatsapp.mp4"
    creationflags = 0
    if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
        creationflags = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run(
            [
                ffmpeg, "-y", "-i", source_path,
                "-c:v", "libx264", "-profile:v", "baseline", "-level", "3.0",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", output_path,
            ],
            capture_output=True,
            timeout=600,
            creationflags=creationflags,
        )
        if (
            result.returncode == 0
            and os.path.isfile(output_path)
            and os.path.getsize(output_path) > 0
        ):
            return output_path, "video/mp4"
        logging.error(
            "[send_media] video conversion to H.264/AAC MP4 failed (rc=%s): %s",
            result.returncode,
            (result.stderr or b"").decode("utf-8", errors="replace")[-800:],
        )
    except Exception:
        logging.exception("[send_media] video conversion to H.264/AAC MP4 failed")
    try:
        os.unlink(output_path)
    except OSError:
        pass
    return None
