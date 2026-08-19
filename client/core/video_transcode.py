"""Video format conversion helpers used before uploading a video message."""

import logging
import mimetypes
import os
import subprocess
import sys


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

    Trusts the .mp4 extension the same way prepare_audio_for_whatsapp trusts
    anything that isn't .ogg — the overwhelmingly common case (a phone/
    camera/screen-recording export, or a video forwarded from WhatsApp
    itself) already is H.264/AAC MP4, and actually confirming the codec
    would need ffprobe, which WinZapp does not bundle (only ffmpeg.exe).
    """
    mime = mimetypes.guess_type(source_path)[0] or "video/mp4"
    if os.path.splitext(source_path)[1].lower() == ".mp4":
        return source_path, mime
    if not ffmpeg or not os.path.isfile(ffmpeg):
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
