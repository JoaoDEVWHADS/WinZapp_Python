"""Regression tests for WhatsApp-compatible video attachment preparation.

WhatsApp's video pipeline expects H.264/AAC inside an MP4 container.
send_media_attachment() used to send whatever container/codec the user
picked as-is, which WPPConnect's upload then rejected server-side with a
bare 500 for anything else (.mkv, .webm, .avi, HEVC inside an .mp4, ...) —
reported live as "erro 500 ao enviar vídeos em diferentes formatos". Mirrors
tests/test_ogg_audio_upload.py's approach for the equivalent audio helper.
"""

import os
from types import SimpleNamespace

from core.video_transcode import prepare_video_for_whatsapp


def test_existing_mp4_passes_through_untouched(tmp_path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not real mp4 bytes")
    monkeypatch.setattr("core.video_transcode.subprocess.run", lambda *a, **k: None)

    result = prepare_video_for_whatsapp("missing-ffmpeg", str(source))

    assert result == (str(source), "video/mp4")


def test_mkv_is_transcoded_to_h264_aac_mp4(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "clip.mkv"
    source.write_bytes(b"fake mkv bytes")

    def fake_run(command, **kwargs):
        assert "-c:v" in command and "libx264" in command
        assert "-c:a" in command and "aac" in command
        output = command[-1]
        with open(output, "wb") as target:
            target.write(b"fake mp4 bytes")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("core.video_transcode.subprocess.run", fake_run)

    output, mime = prepare_video_for_whatsapp(str(ffmpeg), str(source))

    assert output.endswith(".whatsapp.mp4")
    assert os.path.isfile(output)
    assert mime == "video/mp4"


def test_webm_without_ffmpeg_fails_instead_of_uploading_incompatible_video(tmp_path):
    source = tmp_path / "clip.webm"
    source.write_bytes(b"fake webm bytes")

    assert prepare_video_for_whatsapp("", str(source)) is None


def test_conversion_failure_cleans_up_partial_output(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "clip.avi"
    source.write_bytes(b"fake avi bytes")

    def fake_run(command, **kwargs):
        output = command[-1]
        # Simulate ffmpeg writing a partial file before failing.
        with open(output, "wb") as target:
            target.write(b"partial")
        return SimpleNamespace(returncode=1, stderr=b"unsupported codec")

    monkeypatch.setattr("core.video_transcode.subprocess.run", fake_run)

    result = prepare_video_for_whatsapp(str(ffmpeg), str(source))

    assert result is None
    assert not os.path.isfile(str(source) + ".whatsapp.mp4")
