"""An echo that comes back later than AEC3 can reach is still cancelled.

A tester with a mixer loopback heard his whole voice come back with the
WebRTC canceller on (2026-10-19). Simulated: AEC3 removes ~70 dB of a loopback
copy up to 450 ms late and 1-2 dB from 600 ms. CallAudioProcessor now measures
the delay and holds the reference back so AEC3 sees the echo early enough.
These run the real module.
"""

import numpy as np

from core.call_audio_processing import (
    APM_SAMPLE_RATE, DIRECT_ECHO_MAX_MS, ECHO_TARGET_MS, CallAudioProcessor,
)

SR = APM_SAMPLE_RATE


def _speech(seconds, seed):
    rng = np.random.default_rng(seed)
    n = SR * seconds
    x = np.convolve(rng.standard_normal(n), np.ones(6) / 6, "same")
    envelope = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.uniform(0.08, 0.3) * SR)
        envelope[i:i + length] = rng.uniform(0.2, 1.0) if rng.random() < 0.7 else 0.0
        i += length
    envelope = np.convolve(envelope, np.ones(480) / 480, "same")
    return (x * envelope * 0.5).astype(np.float32)


def _call(far, mic, processor, speaker_period=960):
    """The microphone in 20 ms frames; the speaker in its own device periods."""
    out, pushed = [], 0
    for i in range(0, len(far) - 960, 960):
        while pushed < i + 960:
            processor.push_reference(far[pushed:pushed + speaker_period])
            pushed += speaker_period
        out.append(processor.process(mic[i:i + 960]))
    return np.concatenate(out)


def _reduction_db(mic, out, seconds=4):
    tail = slice(-seconds * SR, None)
    return 10 * np.log10(np.mean(mic[:len(out)][tail] ** 2) / (np.mean(out[tail] ** 2) + 1e-12))


def _loopback(far, delay_ms, gain=1.0):
    delay = delay_ms * SR // 1000
    mic = np.zeros_like(far)
    mic[delay:] = np.clip(far[:-delay] * gain, -1.0, 1.0)
    return mic


def test_a_loopback_900ms_late_is_cancelled():
    far = _speech(14, 1)
    mic = _loopback(far, 900)
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    out = _call(far, mic, processor)
    assert _reduction_db(mic, out) > 40
    held = processor.diagnostics()["reference_held_ms"]
    assert abs(held - (900 - ECHO_TARGET_MS)) <= 20


def test_odd_speaker_periods_still_measure_and_cancel_the_late_echo():
    # 441 and 448 sample periods are not multiples of the 48->8 kHz factor;
    # dropping each chunk's remainder broke the measure (review of #563).
    for period in (441, 448, 487):
        far = _speech(14, 1)
        mic = _loopback(far, 900)
        processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
        out = _call(far, mic, processor, speaker_period=period)
        measured = processor.diagnostics()
        assert abs(measured["reference_held_ms"] - (900 - ECHO_TARGET_MS)) <= 20, period
        assert measured["echo_in"] > 0.9, period
        assert _reduction_db(mic, out) > 40, period


def test_an_echo_within_reach_is_not_held_back():
    far = _speech(10, 2)
    mic = _loopback(far, 120, gain=0.5)
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    out = _call(far, mic, processor)
    assert processor.diagnostics()["reference_held_ms"] == 0
    assert _reduction_db(mic, out) > 40


def test_a_headset_with_no_echo_never_moves_the_reference():
    far = _speech(8, 3)
    near = _speech(8, 4)  # the user talking, nothing of the far end
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    _call(far, near, processor)
    assert processor.diagnostics()["reference_held_ms"] == 0


def test_the_hold_follows_when_the_loopback_delay_drops_back():
    far = _speech(24, 5)
    late, early = _loopback(far, 800), _loopback(far, 100)
    half = len(far) // 2
    mic = np.concatenate((late[:half], early[half:]))
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    out = _call(far, mic, processor)
    assert processor.diagnostics()["reference_held_ms"] == 0
    assert _reduction_db(mic, out, seconds=3) > 30


def test_the_threshold_leaves_aec3_its_own_range():
    assert ECHO_TARGET_MS < DIRECT_ECHO_MAX_MS < 450
