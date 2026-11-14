"""Take one still picture out of a video, locally, so only a picture leaves.

The video's audio is never opened: only the video stream is demuxed and
decoded. The frame is then shaped by ``image_input.prepare_image`` like any
photo (oriented, re-encoded, metadata removed).
"""
from io import BytesIO

from .config import MAX_PIXELS
from .errors import DescriptionError

#: A second in usually skips a black or fading first frame; a shorter video
#: uses its middle.
_TARGET_SECONDS = 1.0
#: Frames decoded at most while looking for the target (about 10 s at 30 fps).
_MAX_FRAMES = 300
_ROTATIONS = {90: 90, 180: 180, 270: 270}


def extract_frame(data):
    """JPEG bytes of one frame of the video in ``data``.

    Raises ``DescriptionError`` ``media_format`` for anything that is not a
    decodable video and ``media_size`` for a picture larger than the image
    limit."""
    try:
        import av
        from av.error import FFmpegError
    except ImportError:
        raise DescriptionError("media_format") from None
    try:
        with av.open(BytesIO(data), mode="r") as container:
            if not container.streams.video:
                raise DescriptionError("media_format")
            stream = container.streams.video[0]
            if (stream.width or 0) * (stream.height or 0) > MAX_PIXELS:
                raise DescriptionError("media_size")
            frame = _pick_frame(container, stream, av)
            if frame is None:
                raise DescriptionError("media_format")
            image = frame.to_image()
            turns = _ROTATIONS.get(int(round(getattr(frame, "rotation", 0) or 0)) % 360)
            if turns:
                # PyAV reports the display matrix as counter-clockwise degrees.
                image = image.rotate(turns, expand=True)
            output = BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=92)
            return output.getvalue()
    except DescriptionError:
        raise
    except (FFmpegError, OSError, ValueError, TypeError, MemoryError):
        raise DescriptionError("media_format") from None


def _pick_frame(container, stream, av):
    duration = float(container.duration) / av.time_base if container.duration else 0.0
    target = min(_TARGET_SECONDS, duration / 2) if duration > 0 else 0.0
    if target > 0:
        try:
            container.seek(int(target * av.time_base))
        except (av.error.FFmpegError, OSError, ValueError):
            container.seek(0)
    chosen = None
    for count, frame in enumerate(container.decode(stream)):
        chosen = frame
        if (frame.time or 0.0) >= target or count + 1 >= _MAX_FRAMES:
            break
    return chosen
