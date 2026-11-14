"""How much of the speaker's audio is in the call microphone, for the log.

Pure numpy, no devices: CallAudioProcessor keeps the last seconds of the
speaker reference, the microphone and what it sent, and logs echo_coupling()
of each against the reference, so a report of "they still hear themselves"
says whether the echo was in the microphone, whether the canceller removed
it, and how late it arrived.
"""

from __future__ import annotations

import numpy as np

# Echo measurement for the call log, at 8 kHz (speech band, cheap): over the
# last window of audio, how much of the speaker reference is in the microphone
# before the module and in what it sends after it, and at which lag.
MEASURE_RATE = 8_000
MEASURE_DECIMATION = 48_000 // MEASURE_RATE
MEASURE_WINDOW_S = 2.0
# The echo arrives after the reference: device and room delay, usually tens of
# milliseconds, more than half a second through some mixer loopbacks.
MEASURE_MAX_LAG_S = 1.5
# ...and the reference may reach the module a little late (sender batching).
MEASURE_MAX_LEAD_S = 0.1


def decimate(samples: np.ndarray) -> np.ndarray:
    """48 kHz -> 8 kHz by block averaging (a crude low-pass, fine for a measure)."""
    usable = samples.size - samples.size % MEASURE_DECIMATION
    return samples[:usable].reshape(-1, MEASURE_DECIMATION).mean(axis=1)


def echo_coupling(reference: np.ndarray, signal: np.ndarray, *, rate: int = MEASURE_RATE,
                  max_lag_s: float = MEASURE_MAX_LAG_S,
                  max_lead_s: float = MEASURE_MAX_LEAD_S):
    """How much of *reference* *signal* carries, and how late.

    Both arrays end at the same moment; *reference* may be longer (it holds the
    past the lag search needs). Returns (coefficient, lag_ms): the peak of the
    normalised cross-correlation over lags [-max_lead, max_lag], 0..1, where
    ~0.9 means the signal is essentially a copy of the reference (a loopback)
    and under ~0.1 means no echo worth hearing. (0.0, None) when either side
    is silent.
    """
    signal = np.asarray(signal, dtype=np.float64)
    reference = np.asarray(reference, dtype=np.float64)
    n = signal.size
    back = int(max_lag_s * rate)
    ahead = int(max_lead_s * rate)
    if n == 0 or reference.size < n:
        return 0.0, None
    # ref[back] pairs with signal[0] at lag 0; the `ahead` zeros at the end let
    # the reference be a little behind the signal.
    have_back = min(back, reference.size - n)
    ref = np.concatenate((np.zeros(back - have_back),
                          reference[reference.size - n - have_back:],
                          np.zeros(ahead)))
    sig_energy = float(np.dot(signal, signal))
    if sig_energy < 1e-10 or float(np.dot(ref, ref)) < 1e-10:
        return 0.0, None
    size = 1 << int(np.ceil(np.log2(ref.size + n)))
    corr = np.fft.irfft(np.fft.rfft(ref, size) * np.conj(np.fft.rfft(signal, size)), size)
    # corr[k] = sum_t ref[t + k] * signal[t]; the signal lags by back - k.
    shifts = np.arange(0, back + ahead + 1)
    cumulative = np.concatenate(([0.0], np.cumsum(ref * ref)))
    window_energy = cumulative[shifts + n] - cumulative[shifts]
    coefficient = np.abs(corr[shifts]) / np.sqrt(np.maximum(window_energy, 1e-12) * sig_energy)
    coefficient[window_energy < 1e-10] = 0.0
    best = int(np.argmax(coefficient))
    return round(float(min(1.0, coefficient[best])), 2), round((back - best) * 1000 / rate)


def dbfs(samples: np.ndarray):
    if not samples.size:
        return None
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return round(20 * np.log10(max(rms, 1e-6)), 1)
