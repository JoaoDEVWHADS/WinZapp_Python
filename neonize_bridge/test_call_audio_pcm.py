"""Synthetic sample count, split invariance and anti-alias contracts; no device."""
import array
import math

import pytest

from call_audio_pcm import PCM48To16


def pcm(values):
    return array.array("h", values).tobytes()


def unpack(data):
    return array.array("h", data).tolist()


@pytest.mark.parametrize("split", [1, 2, 5, 127, 1920, 2048])
def test_packet_splits_preserve_samples_and_exact_clock(split):
    source = pcm(round(14000 * math.sin(i / 17)) for i in range(4800))
    whole = PCM48To16().push(source)
    converter = PCM48To16()
    parts = b"".join(converter.push(source[i:i+split]) for i in range(0, len(source), split))
    assert parts == whole
    assert len(parts) == 3200


def test_clear_discards_filter_and_incomplete_sample_history():
    converter = PCM48To16()
    converter.push(pcm([25000] * 1000) + b"\x01")
    converter.clear()
    assert converter.push(pcm([0] * 960)) == pcm([0] * 320)


@pytest.mark.parametrize("frequency,maximum_db", [(9000, -60), (12000, -65), (20000, -65)])
def test_frequencies_above_output_nyquist_do_not_fold_into_speech(frequency, maximum_db):
    values = [round(20000 * math.sin(2 * math.pi * frequency * i / 48000)) for i in range(4800)]
    output = unpack(PCM48To16().push(pcm(values)))[80:]
    rms = math.sqrt(sum(float(v)**2 for v in output) / len(output))
    relative_db = 20 * math.log10(max(rms, 1e-12) / (20000 / math.sqrt(2)))
    assert relative_db < maximum_db


def test_speech_band_level_and_dc_are_preserved_after_fixed_delay():
    values = [round(16000 * math.sin(2 * math.pi * 1000 * i / 48000)) for i in range(4800)]
    output = unpack(PCM48To16().push(pcm(values)))[80:]
    rms = math.sqrt(sum(float(v)**2 for v in output) / len(output))
    assert abs(20 * math.log10(rms / (16000 / math.sqrt(2)))) < 0.1
    steady = unpack(PCM48To16().push(pcm([12000] * 4800)))[80:]
    assert max(abs(value - 12000) for value in steady) <= 1


def test_full_scale_never_wraps_or_raises():
    output = unpack(PCM48To16().push(pcm([32767, -32768] * 2400)))
    assert len(output) == 1600
    assert all(-32768 <= value <= 32767 for value in output)
