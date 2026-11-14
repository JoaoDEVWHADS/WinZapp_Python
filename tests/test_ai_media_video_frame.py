"""A video is described from one still frame taken locally: only a picture is sent."""
import io

import pytest

from core.ai_media import config, prompts
from core.ai_media.errors import DescriptionError
from core.ai_media.payload import prepare_media
from core.ai_media.video_frame import extract_frame

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")
from PIL import Image


def make_video(frames=30, rate=10, rotation=0, audio=False):
    """A small mp4 whose frame ``i`` is uniformly gray ``i * 8``."""
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="mp4") as container:
        stream = container.add_stream("mpeg4", rate=rate)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        if rotation:
            stream.set_display_rotation(rotation)
        if audio:
            container.add_stream("aac", rate=8000)
        for i in range(frames):
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 8, dtype=np.uint8), format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return buffer.getvalue()


def gray(jpeg):
    with Image.open(io.BytesIO(jpeg)) as image:
        return image.convert("L").resize((1, 1)).getpixel((0, 0)), image.size


def test_the_frame_is_a_jpeg_taken_about_a_second_in_not_the_first_frame():
    level, size = gray(extract_frame(make_video()))
    assert size == (64, 48)
    assert 60 <= level <= 100  # frame 10 of 30 at 10 fps is gray 80; the first would be 0


def test_a_clip_shorter_than_two_seconds_uses_its_middle():
    level, _ = gray(extract_frame(make_video(frames=10)))  # 1 s long: middle is frame 5 (gray 40)
    assert 25 <= level <= 55


def test_a_single_frame_video_still_gives_that_frame():
    level, _ = gray(extract_frame(make_video(frames=1)))
    assert level <= 10


def test_the_display_rotation_is_applied():
    _, size = gray(extract_frame(make_video(rotation=90)))
    assert size == (48, 64)


@pytest.mark.parametrize("data", [b"", b"not a video at all", b"\x00" * 4096, b"%PDF-1.7 body"])
def test_anything_that_is_not_a_video_is_a_format_error(data):
    with pytest.raises(DescriptionError, match="ai_error_media_format"):
        extract_frame(data)


def test_a_file_without_a_video_stream_is_a_format_error():
    buffer = io.BytesIO()
    with av.open(buffer, "w", format="wav") as container:
        stream = container.add_stream("pcm_s16le", rate=8000)
        frame = av.AudioFrame.from_ndarray(np.zeros((1, 800), dtype=np.int16), format="s16", layout="mono")
        frame.sample_rate = 8000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    with pytest.raises(DescriptionError, match="ai_error_media_format"):
        extract_frame(buffer.getvalue())


def test_a_picture_larger_than_the_image_limit_is_a_size_error(monkeypatch):
    from core.ai_media import video_frame
    monkeypatch.setattr(video_frame, "MAX_PIXELS", 64 * 48 - 1)
    with pytest.raises(DescriptionError, match="ai_error_media_size"):
        extract_frame(make_video())


def test_prepare_media_turns_a_video_into_an_image_payload():
    video = make_video(audio=True)
    media = prepare_media("video", video, "video/mp4")
    assert (media.kind, media.mime, media.filename) == ("image", "image/jpeg", "frame.jpg")
    assert media.data[:2] == b"\xff\xd8" and media.data != video and len(media.data) < len(video) * 4
    assert gray(media.data)[1] == (64, 48)


def test_a_video_is_described_by_any_provider_that_takes_pictures():
    for name, provider in config.PROVIDERS.items():
        assert config.supports(name, "video") == ("image" in provider.capabilities)
        assert "video" not in provider.capabilities  # nobody is sent a video


def test_a_video_cannot_reach_a_provider_as_a_video():
    from core.ai_media.payload import Media
    from core.ai_media.providers import build_request
    for name, provider in config.PROVIDERS.items():
        with pytest.raises(DescriptionError, match="ai_error_request"):
            build_request(name, provider.model, "key", Media("video", b"x", "video/mp4", "video.mp4"), (), "q", "i", "balanced")


def test_the_prompt_describes_one_frame_and_does_not_promise_story_or_speech():
    text = prompts.instructions("pt-BR", "balanced", "video")
    assert "single frame taken from a video" in text and "do not guess" in text
    assert "what is said in order" not in text and "what happens in order" not in text
    assert "frame" not in prompts.instructions("pt-BR", "balanced", "image")
