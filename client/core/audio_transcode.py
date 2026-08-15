"""Audio format conversion helpers used by the in-app player."""

import logging
import os
import subprocess
import sys


def transcode_m4a_to_wav(ffmpeg: str, source_path: str) -> str | None:
    """Convert an MP4/M4A audio stream to PCM WAV for reliable BASS playback."""
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
            "[UI Audio Playback] M4A→WAV conversion failed (rc=%s): %s",
            result.returncode,
            (result.stderr or b"").decode("utf-8", errors="replace")[-800:],
        )
    except Exception:
        logging.exception("[UI Audio Playback] M4A→WAV conversion failed")

    try:
        os.unlink(output_path)
    except OSError:
        pass
    return None
