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

from core.video_transcode import (
    needs_transcode,
    prepare_video_for_whatsapp,
    probe_stream_codecs,
)


def test_existing_mp4_passes_through_when_the_codecs_cannot_be_probed(tmp_path, monkeypatch):
    """No usable ffmpeg means no way to read the streams. That falls back to
    the old extension-only behaviour deliberately: a needless re-encode of
    every single video is worse than the occasional upload that still has to
    be retried."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"not real mp4 bytes")
    monkeypatch.setattr("core.video_transcode.subprocess.run", lambda *a, **k: None)

    result = prepare_video_for_whatsapp("missing-ffmpeg", str(source))

    assert result == (str(source), "video/mp4")


_H264_AAC_STDERR = b"""Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'clip.mp4':
  Duration: 00:00:12.05, start: 0.000000, bitrate: 1794 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1280x720, 30 fps
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo
At least one output file must be specified
"""

_HEVC_STDERR = b"""Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'IMG_0042.mp4':
  Stream #0:0[0x1](und): Video: hevc (Main) (hvc1 / 0x31637668), yuv420p, 1920x1080
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 44100 Hz, stereo
At least one output file must be specified
"""


def test_an_mp4_that_really_is_h264_aac_is_not_re_encoded(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake mp4 bytes")

    def fake_run(command, **kwargs):
        assert "-i" in command and command[-1] == str(source)
        return SimpleNamespace(returncode=1, stdout=b"", stderr=_H264_AAC_STDERR)

    monkeypatch.setattr("core.video_transcode.subprocess.run", fake_run)

    assert prepare_video_for_whatsapp(str(ffmpeg), str(source)) == (
        str(source), "video/mp4",
    )


def test_hevc_inside_an_mp4_is_transcoded(tmp_path, monkeypatch):
    """The container says .mp4 but the stream is HEVC — an iPhone export or
    a modern screen recording. Trusting the extension sent it as-is and
    WPPConnect answered the same bare 500 this whole module exists to stop."""
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "IMG_0042.mp4"
    source.write_bytes(b"fake mp4 bytes")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        if "-c:v" not in command:  # the probe
            return SimpleNamespace(returncode=1, stdout=b"", stderr=_HEVC_STDERR)
        output = command[-1]
        with open(output, "wb") as target:
            target.write(b"fake h264 mp4 bytes")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("core.video_transcode.subprocess.run", fake_run)

    output, mime = prepare_video_for_whatsapp(str(ffmpeg), str(source))

    assert output.endswith(".whatsapp.mp4")
    assert mime == "video/mp4"
    assert len(calls) == 2  # probe, then convert


class TestProbeStreamCodecs:
    """ffprobe is not bundled with WinZapp — plain `ffmpeg -i <file>` with no
    output file prints the same stream table to stderr, which is all the
    codec check needs."""

    def test_reads_video_and_audio_codecs(self):
        video, audio = probe_stream_codecs(_H264_AAC_STDERR.decode())
        assert video == {"h264"}
        assert audio == {"aac"}

    def test_reads_hevc(self):
        video, audio = probe_stream_codecs(_HEVC_STDERR.decode())
        assert video == {"hevc"}

    def test_output_with_no_stream_lines_yields_nothing(self):
        assert probe_stream_codecs("clip.mp4: No such file or directory") == (set(), set())

    def test_empty_input_yields_nothing(self):
        assert probe_stream_codecs("") == (set(), set())


class TestNeedsTranscode:
    def test_a_non_mp4_container_always_needs_converting(self):
        assert needs_transcode(".mkv", ({"h264"}, {"aac"})) is True
        assert needs_transcode(".webm", None) is True

    def test_an_h264_aac_mp4_does_not(self):
        assert needs_transcode(".mp4", ({"h264"}, {"aac"})) is False

    def test_a_silent_h264_mp4_does_not(self):
        assert needs_transcode(".mp4", ({"h264"}, set())) is False

    def test_a_non_h264_video_stream_does(self):
        assert needs_transcode(".mp4", ({"hevc"}, {"aac"})) is True
        assert needs_transcode(".mp4", ({"av1"}, {"aac"})) is True

    def test_a_non_aac_audio_stream_does(self):
        assert needs_transcode(".mp4", ({"h264"}, {"opus"})) is True

    def test_an_unreadable_probe_leaves_an_mp4_alone(self):
        assert needs_transcode(".mp4", None) is False


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
