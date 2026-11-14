"""Streaming 48 -> 16 kHz s16le mono, without a bridge-only dependency.

The client has already cleaned/captured 48 kHz PCM. Decimation still needs an
anti-alias filter here: averaging three samples folds microphone frequencies
above 8 kHz into speech. The 97-tap Blackman FIR has a fixed 1 ms delay and
keeps its history across packets; it never flushes old speech into a new call.
"""
import array
import math
import operator
import sys

RATIO = 3
TAPS = 97


def _coefficients():
    radius = (TAPS - 1) // 2
    cutoff = 0.30                 # 7.2 kHz at 48 kHz, transition below Nyquist
    weights = []
    for n in range(TAPS):
        x = n - radius
        sinc = cutoff if x == 0 else math.sin(math.pi * cutoff * x) / (math.pi * x)
        window = 0.42 - 0.5 * math.cos(2 * math.pi * n / (TAPS - 1))
        window += 0.08 * math.cos(4 * math.pi * n / (TAPS - 1))
        weights.append(sinc * window)
    total = sum(weights)
    return tuple(value / total for value in weights)


_WEIGHTS = _coefficients()


class PCM48To16:
    """Own one filter per microphone stream; packet splits do not change it."""

    def __init__(self):
        self.clear()

    def clear(self):
        self._history = [0] * (TAPS - 1)
        self._carry = b""

    def push(self, pcm):
        data = self._carry + pcm
        whole = len(data) // (2 * RATIO) * (2 * RATIO)
        self._carry = data[whole:]
        samples = array.array("h")
        samples.frombytes(data[:whole])
        if sys.byteorder != "little":
            samples.byteswap()
        available = self._history + samples.tolist()
        output = array.array("h")
        # Taps are symmetric, so the forward window is the causal convolution.
        for end in range(TAPS - 1 + RATIO - 1, len(available), RATIO):
            value = round(sum(map(operator.mul, _WEIGHTS, available[end - TAPS + 1:end + 1])))
            output.append(max(-32768, min(32767, value)))
        self._history = available[-(TAPS - 1):]
        if sys.byteorder != "little":
            output.byteswap()
        return output.tobytes()
