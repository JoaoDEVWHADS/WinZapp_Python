"""Regression tests for WhatsApp-compatible audio preparation."""

import os
from types import SimpleNamespace

from core.audio_transcode import prepare_audio_for_whatsapp


def test_existing_ogg_opus_passes_through(tmp_path, monkeypatch):
    source = tmp_path / "voice.ogg"
    source.write_bytes(b"OggS" + b"x" * 40 + b"OpusHead" + b"audio")
    monkeypatch.setattr("core.audio_transcode.subprocess.run", lambda *a, **k: None)

    result = prepare_audio_for_whatsapp("missing-ffmpeg", str(source))

    assert result == (str(source), "audio/ogg; codecs=opus")


def test_ogg_vorbis_is_transcoded_to_opus(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "music.ogg"
    source.write_bytes(b"OggS" + b"\x01vorbis" + b"audio")

    def fake_run(command, **kwargs):
        output = command[-1]
        with open(output, "wb") as target:
            target.write(b"OggS" + b"OpusHead" + b"converted")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("core.audio_transcode.subprocess.run", fake_run)

    output, mime = prepare_audio_for_whatsapp(str(ffmpeg), str(source))

    assert output.endswith(".opus.ogg")
    assert os.path.isfile(output)
    assert mime == "audio/ogg; codecs=opus"


def test_ogg_vorbis_without_ffmpeg_fails_instead_of_uploading_bad_codec(tmp_path):
    source = tmp_path / "music.ogg"
    source.write_bytes(b"OggS" + b"\x01vorbis" + b"audio")

    assert prepare_audio_for_whatsapp("", str(source)) is None


def test_wav_is_transcoded_to_opus(tmp_path, monkeypatch):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_bytes(b"binary")
    source = tmp_path / "large-audio.wav"
    source_bytes = b"RIFF" + b"pcm-audio" * 100
    source.write_bytes(source_bytes)

    seen_command = []
    temp_kwargs = {}

    def fake_mkstemp(**kwargs):
        temp_kwargs.update(kwargs)
        output = tmp_path / "writable-system-temp.whatsapp.opus.ogg"
        return os.open(output, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600), str(output)

    def fake_run(command, **kwargs):
        seen_command.extend(command)
        with open(command[-1], "wb") as target:
            target.write(b"OggS" + b"OpusHead" + b"converted")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("core.audio_transcode.tempfile.mkstemp", fake_mkstemp)
    monkeypatch.setattr("core.audio_transcode.subprocess.run", fake_run)

    output, mime = prepare_audio_for_whatsapp(str(ffmpeg), str(source))

    assert output.endswith(".whatsapp.opus.ogg")
    assert mime == "audio/ogg; codecs=opus"
    assert "libopus" in seen_command
    assert str(source) in seen_command
    assert "dir" not in temp_kwargs
    assert source.read_bytes() == source_bytes


def test_wav_without_ffmpeg_fails_instead_of_uploading_native_wav(tmp_path):
    source = tmp_path / "large-audio.wav"
    source.write_bytes(b"RIFF" + b"pcm-audio")

    assert prepare_audio_for_whatsapp("", str(source)) is None


def test_other_supported_audio_formats_still_pass_through(tmp_path, monkeypatch):
    source = tmp_path / "music.mp3"
    source.write_bytes(b"mp3 audio")
    monkeypatch.setattr(
        "core.audio_transcode.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("MP3 must not be transcoded")
        ),
    )

    assert prepare_audio_for_whatsapp("missing-ffmpeg", str(source)) == (
        str(source), "audio/mpeg",
    )
