"""Regression tests for WhatsApp-compatible OGG attachment preparation."""

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
