"""The echo measure the call log carries, so a tester's report can be read.

A tester still heard an echo with the WebRTC canceller on, and the log could
not say whether the echo was in the microphone at all. These pin what the new
fields mean.
"""

import numpy as np

from core.call_audio_processing import APM_SAMPLE_RATE, CallAudioProcessor
from core.call_echo_measure import MEASURE_RATE, dbfs, decimate, echo_coupling

SR = MEASURE_RATE


def _noise(seconds, seed):
    rng = np.random.default_rng(seed)
    return rng.standard_normal(int(SR * seconds)) * 0.1


def test_a_delayed_copy_is_found_with_its_lag():
    reference = _noise(3, 1)
    lag = int(0.25 * SR)
    signal = np.concatenate((np.zeros(lag), reference[:-lag]))[-2 * SR:] * 0.5
    coefficient, lag_ms = echo_coupling(reference, signal)
    assert coefficient > 0.95
    assert lag_ms == 250


def test_an_echo_a_second_late_is_still_found():
    reference = _noise(3, 2)
    lag = int(0.9 * SR)
    signal = np.concatenate((np.zeros(lag), reference[:-lag]))[-2 * SR:]
    coefficient, lag_ms = echo_coupling(reference, signal)
    assert coefficient > 0.9 and lag_ms == 900


def test_a_reference_that_arrived_slightly_late_gives_a_negative_lag():
    reference = _noise(3, 3)
    lead = int(0.05 * SR)
    signal = reference[lead:][-2 * SR:]
    reference = reference[:-lead]
    coefficient, lag_ms = echo_coupling(reference, signal)
    assert coefficient > 0.9 and lag_ms == -50


def test_an_unrelated_signal_scores_low():
    coefficient, _ = echo_coupling(_noise(3, 4), _noise(2, 5))
    assert coefficient < 0.1


def test_silence_on_either_side_reports_nothing():
    assert echo_coupling(np.zeros(3 * SR), _noise(2, 6)) == (0.0, None)
    assert echo_coupling(_noise(3, 7), np.zeros(2 * SR)) == (0.0, None)
    assert echo_coupling(_noise(1, 8), _noise(2, 9)) == (0.0, None)  # not enough reference


def test_decimate_and_dbfs():
    assert decimate(np.ones(97)).size == 16
    assert dbfs(np.full(100, 0.5)) == -6.0
    assert dbfs(np.empty(0)) is None


def test_the_log_shows_the_echo_before_and_its_absence_after_the_canceller():
    rng = np.random.default_rng(11)
    far = (rng.standard_normal(APM_SAMPLE_RATE * 6) * 0.1).astype(np.float32)
    mic = np.zeros_like(far)
    mic[2400:] = far[:-2400] * 0.9
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    for i in range(0, len(far), 960):
        processor.push_reference(far[i:i + 960])
        processor.process(mic[i:i + 960])
    measured = processor.diagnostics()
    assert measured["echo_in"] > 0.9
    assert measured["echo_in_lag_ms"] == 50
    assert measured["echo_out"] < 0.2
    assert measured["sent_dbfs"] < measured["mic_dbfs"] - 20


def test_no_measure_without_echo_cancellation_or_before_a_second_of_audio():
    processor = CallAudioProcessor(echo_cancellation=False, noise_suppression=True)
    processor.process(np.zeros(APM_SAMPLE_RATE * 2, dtype=np.float32))
    assert "echo_in" not in processor.diagnostics()
    fresh = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    fresh.process(np.zeros(APM_SAMPLE_RATE // 2, dtype=np.float32))
    assert "echo_in" not in fresh.diagnostics()
