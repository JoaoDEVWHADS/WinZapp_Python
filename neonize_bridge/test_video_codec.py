"""The video of a call through ffmpeg: cutting the streams, and a real round
trip (JPEG -> H.264 -> JPEG) when there is an ffmpeg."""
import io
import os
import shutil
import threading
from pathlib import Path

import pytest

import video_codec as vc

AUD = b"\x00\x00\x00\x01\x09\xf0"
SPS = b"\x00\x00\x00\x01\x67\x42\x00\x1f"
IDR = b"\x00\x00\x01\x65\x88\x84"
SLICE = b"\x00\x00\x00\x01\x41\x9a"


def test_the_stream_is_cut_at_each_delimiter():
    stream = b"junk" + AUD + SPS + IDR + AUD + SLICE + AUD + SLICE[:3]
    units, rest = vc.split_access_units(stream)
    assert units == [SPS + IDR, SLICE]
    assert rest == AUD + SLICE[:3]
    more, rest = vc.split_access_units(rest + SLICE[3:] + AUD)
    assert more == [SLICE] and rest == AUD


def test_without_a_delimiter_nothing_is_whole_yet():
    assert vc.split_access_units(SPS + IDR) == ([], SPS + IDR)
    units, rest = vc.split_access_units(b"\x00" * (vc._PENDING_LIMIT + 10))
    assert units == [] and len(rest) == vc._PENDING_LIMIT


def test_delimiters_are_dropped_and_other_nal_units_kept():
    assert vc.drop_delimiters(AUD + SPS + IDR) == SPS + IDR
    assert vc.nal_starts(SPS + IDR) == [(0, 4), (len(SPS), len(SPS) + 3)]


def test_jpegs_are_cut_whole():
    one, two = b"\xff\xd8abc\xff\xd9", b"\xff\xd8de\xff\xd9"
    assert vc.jpeg_frames(b"x" + one + two + b"\xff\xd8f") == ([one, two], b"\xff\xd8f")
    assert vc.jpeg_frames(b"nothing") == ([], b"")


def test_the_commands_ask_for_what_meowcaller_carries():
    encoder = " ".join(vc.encoder_command("ffmpeg"))
    assert "-f mjpeg" in encoder and "libx264" in encoder and "baseline" in encoder
    assert "aud=1" in encoder and "-bf 0" in encoder and encoder.endswith("-f h264 -")
    assert encoder.count("threads") == 2              # no frame threads: they delay
    assert "-threads 1 -f h264" in " ".join(vc.decoder_command("ffmpeg"))
    decoder = " ".join(vc.decoder_command("ffmpeg"))
    assert "-f h264 -i -" in decoder and "-c:v mjpeg" in decoder


def _ffmpeg():
    bundled = Path(__file__).resolve().parents[1] / "client" / "lib" / "ffmpeg.exe"
    return str(bundled) if bundled.exists() else shutil.which("ffmpeg")


def _jpeg(shade):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (320, 180), (shade, 80, 160)).save(out, "JPEG")
    return out.getvalue()


@pytest.mark.skipif(not _ffmpeg(), reason="no ffmpeg here")
def test_a_real_round_trip():
    ffmpeg = _ffmpeg()
    units, jpegs = [], []
    got_units, got_jpegs = threading.Event(), threading.Event()

    def on_unit(unit):
        units.append(unit)
        if len(units) >= 3:
            got_units.set()

    def on_jpeg(jpeg):
        jpegs.append(jpeg)
        got_jpegs.set()

    encoder = vc.Encoder(ffmpeg, on_unit)
    try:
        for n in range(12):
            encoder.push(_jpeg(20 * n % 255))
            threading.Event().wait(0.1)
        assert got_units.wait(15), "the encoder gave no access unit"
    finally:
        encoder.close()
    first = units[0]
    # the first unit is a key frame with its parameter sets, and no delimiter
    kinds = {first[h] & 0x1F for _, h in vc.nal_starts(first)}
    assert {7, 8, 5} <= kinds and 9 not in kinds
    decoder = vc.Decoder(ffmpeg, on_jpeg)
    try:
        for unit in units:
            decoder.push(unit)
            threading.Event().wait(0.05)
        assert got_jpegs.wait(15), "the decoder gave no JPEG"
    finally:
        decoder.close()
    assert jpegs[0].startswith(b"\xff\xd8") and jpegs[0].endswith(b"\xff\xd9")


def test_no_codec_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(vc, "find_ffmpeg", lambda: None)
    assert vc.FfmpegCodec.available() is None
    monkeypatch.setattr(vc, "find_ffmpeg", lambda: os.devnull)
    assert vc.FfmpegCodec.available().ffmpeg == os.devnull
