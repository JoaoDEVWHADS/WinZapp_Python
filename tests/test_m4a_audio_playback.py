"""Regression tests for MP4/M4A (and other BASS-unsupported) voice-message
playback through BASS, both funnelled through transcode_audio_to_wav()."""

import pathlib
import sys
import types


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client"))


def test_m4a_is_transcoded_to_nonempty_wav(tmp_path, monkeypatch):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"stub")

    from core import audio_transcode

    def fake_run(command, **_kwargs):
        pathlib.Path(command[-1]).write_bytes(b"RIFF" + b"\x00" * 64)
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(audio_transcode.subprocess, "run", fake_run)

    output = audio_transcode.transcode_audio_to_wav(str(ffmpeg), str(source))

    assert output == str(source) + ".wav"
    assert pathlib.Path(output).read_bytes().startswith(b"RIFF")


def test_failed_conversion_removes_partial_wav(tmp_path, monkeypatch):
    source = tmp_path / "voice.m4a"
    source.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"stub")

    from core import audio_transcode

    def fake_run(command, **_kwargs):
        pathlib.Path(command[-1]).write_bytes(b"partial")
        return types.SimpleNamespace(returncode=1, stderr=b"unsupported codec")

    monkeypatch.setattr(audio_transcode.subprocess, "run", fake_run)

    output = audio_transcode.transcode_audio_to_wav(str(ffmpeg), str(source))

    assert output is None
    assert not pathlib.Path(str(source) + ".wav").exists()


def test_ogg_that_bass_cannot_decode_is_also_transcoded(tmp_path, monkeypatch):
    """Issue #54: an OGG whose codec BASS can't open (Vorbis, or a bassopus.dll
    plugin that failed to register) fails BOTH the decode+Tempo stream and the
    plain direct stream with error 41 "unsupported file format" — the same
    ffmpeg fallback used for M4A is the last resort there too, and it isn't
    gated on the ".m4a" extension at all."""
    source = tmp_path / "voice.ogg"
    source.write_bytes(b"OggS" + b"\x00" * 32)
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_bytes(b"stub")

    from core import audio_transcode

    def fake_run(command, **_kwargs):
        pathlib.Path(command[-1]).write_bytes(b"RIFF" + b"\x00" * 64)
        return types.SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(audio_transcode.subprocess, "run", fake_run)

    output = audio_transcode.transcode_audio_to_wav(str(ffmpeg), str(source))

    assert output == str(source) + ".wav"
    assert pathlib.Path(output).read_bytes().startswith(b"RIFF")
