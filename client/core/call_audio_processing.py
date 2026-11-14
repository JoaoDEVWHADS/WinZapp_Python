"""Echo cancellation and noise suppression for the outgoing call microphone.

Both run in WebRTC's own audio processing module (AEC3 and its noise
suppressor), the engine Chrome, Google Meet and WhatsApp's own clients use,
through the ``livekit`` package's binding. The page's WebRTC stack cannot do
it for us: WhatsApp Web only ever sees WinZapp's synthetic microphone track
(callMediaBridge.ts never opens the physical microphone), and the speaker is
played by Python, so Chrome's AEC has neither signal. Python owns both and
must cancel here.

This replaced a hand-written numpy canceller (a frequency-domain Kalman filter
behind a correlation gate) that measured 5-11 dB of echo reduction on the
same synthetic speech where AEC3 gives ~32 dB within the first seconds and
~70 dB once converged. On a laptop speaker or a mixer loopback the echo is
nearly as loud as the user's voice, so 10 dB left it plainly audible: "it
cancels nothing", as testers put it. AEC3 also carries the residual echo
suppressor and its own delay estimator, the two parts the old one lacked.

The module processes exactly 10 ms frames. Far-end audio (what the speaker
played) goes in through ``push_reference`` and near-end audio through
``process``, both on the microphone sender thread, in the order they happened.
"""

from __future__ import annotations

import logging

import numpy as np

from core.call_echo_measure import (
    MEASURE_DECIMATION, MEASURE_MAX_LAG_S, MEASURE_RATE, MEASURE_WINDOW_S, decimate, dbfs, echo_coupling,
)

APM_SAMPLE_RATE = 48_000
APM_FRAME = APM_SAMPLE_RATE // 100  # 10 ms, the only size the module accepts

# AEC3 only finds an echo up to ~0.5 s after its reference: measured on a
# loopback copy, ~70 dB of reduction at 450 ms and 1-2 dB at 600 ms. A mixer
# loopback through a long driver path can return later than that (a tester
# heard his whole voice back with the canceller on, 2026-10-19). So the
# processor measures the echo's delay itself (echo_coupling, up to
# MEASURE_MAX_LAG_S) and, past DIRECT_ECHO_MAX_MS, holds the reference back so
# AEC3 sees the echo ~ECHO_TARGET_MS after it.
DIRECT_ECHO_MAX_MS = 350
ECHO_TARGET_MS = 150
ADAPT_EVERY_FRAMES = 100  # once a second of microphone audio
ADAPT_MIN_COUPLING = 0.4  # a clear echo; double talk and silence stay below
ADAPT_CONSISTENT_MS = 20  # two estimates in a row must agree this closely
ADAPT_MIN_STEP_MS = 30
HOLD_HYSTERESIS_MS = 50
REFERENCE_BUFFER_MAX = APM_SAMPLE_RATE * 2


def _default_apm_factory(*, echo_cancellation: bool, noise_suppression: bool):
    from livekit import rtc

    return rtc.AudioProcessingModule(
        echo_cancellation=echo_cancellation,
        noise_suppression=noise_suppression,
        # Rumble and DC offset below speech; WebRTC runs it in front of AEC3.
        high_pass_filter=True,
        # Off: it pumps the level between words, and the user already chose
        # their microphone gain in Windows.
        auto_gain_control=False,
    )


def _frame(samples: np.ndarray):
    from livekit import rtc

    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    return rtc.AudioFrame(bytearray(pcm.tobytes()), APM_SAMPLE_RATE, 1, APM_FRAME)


def _frame_samples(frame) -> np.ndarray:
    return np.frombuffer(bytes(frame.data), dtype="<i2").astype(np.float32) / 32768.0


class CallAudioProcessor:
    """Streaming microphone cleanup: push far-end audio, process near-end audio.

    ``apm_factory`` and ``frame_factory``/``frame_reader`` exist for the tests;
    the call always uses livekit's module. If the module cannot be built (the
    package missing from a broken install) the microphone passes through
    untouched rather than failing the call.
    """

    def __init__(self, *, echo_cancellation: bool, noise_suppression: bool,
                 apm_factory=None, frame_factory=None, frame_reader=None):
        self._echo_cancellation = bool(echo_cancellation)
        self._noise_suppression = bool(noise_suppression)
        self._apm_factory = apm_factory or _default_apm_factory
        self._frame_factory = frame_factory or _frame
        self._frame_reader = frame_reader or _frame_samples
        self._delay_ms = 0
        self._apm = None
        self._unavailable = False
        self.reset()

    @property
    def available(self) -> bool:
        return self._apm is not None

    def reset(self) -> None:
        """Forget the learned echo path; the next call starts from scratch."""
        self._mic = np.empty(0, dtype=np.float32)
        self._ref = np.empty(0, dtype=np.float32)
        self._frames = 0
        self._reference_frames = 0
        self._errors = 0
        # The last seconds at 8 kHz, for echo_measure().
        self._history_ref = np.empty(0)
        self._history_in = np.empty(0)
        self._history_out = np.empty(0)
        # Reference held back from the module, in samples (see DIRECT_ECHO_MAX_MS).
        self._reference_delay = 0
        # Speaker samples not yet decimated into _history_ref: device periods
        # (441, 448...) are not multiples of the decimation factor, and
        # dropping the remainder of every chunk shrank the history against the
        # microphone's until no echo correlated any more.
        self._ref_undecimated = np.empty(0, dtype=np.float32)
        self._last_lag_ms = None
        self._apm = None
        if self._unavailable:
            return
        try:
            self._apm = self._apm_factory(
                echo_cancellation=self._echo_cancellation,
                noise_suppression=self._noise_suppression,
            )
        except Exception:
            # Once is enough: every reset would otherwise log the same failure.
            self._unavailable = True
            logging.exception("[call_audio] WebRTC audio processing unavailable; "
                              "microphone is sent unprocessed")
            return
        self._apply_delay()

    def set_stream_delay_ms(self, delay_ms) -> None:
        """Hint how late the echo reaches the microphone (output + input latency).

        AEC3 finds the real delay itself; the hint only gives its estimator a
        starting point.
        """
        self._delay_ms = max(0, int(round(delay_ms or 0)))
        self._apply_delay()

    def _apply_delay(self) -> None:
        if self._apm is None or not self._echo_cancellation:
            return
        try:
            self._apm.set_stream_delay_ms(self._delay_ms)
        except Exception:
            logging.debug("[call_audio] could not set the echo delay hint", exc_info=True)

    def push_reference(self, samples: np.ndarray) -> None:
        """Far-end audio (48 kHz mono float32) as the speaker played it.

        Buffered: process() hands it to the module before the microphone
        frames, minus whatever is being held back for a late echo.
        """
        if self._apm is None or not self._echo_cancellation:
            return
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        if not data.size:
            return
        pending = np.concatenate((self._ref_undecimated, data))
        whole = pending.size - pending.size % MEASURE_DECIMATION
        self._ref_undecimated = pending[whole:]
        if whole:
            self._history_ref = self._remember(self._history_ref, pending[:whole],
                                               MEASURE_WINDOW_S + MEASURE_MAX_LAG_S)
        self._ref = np.concatenate((self._ref, data))
        if self._ref.size > REFERENCE_BUFFER_MAX:
            self._ref = self._ref[self._ref.size - REFERENCE_BUFFER_MAX:]

    def _feed_reference(self) -> None:
        while self._ref.size - self._reference_delay >= APM_FRAME:
            chunk, self._ref = self._ref[:APM_FRAME], self._ref[APM_FRAME:]
            try:
                self._apm.process_reverse_stream(self._frame_factory(chunk))
                self._reference_frames += 1
            except Exception:
                self._errors += 1

    def _adapt_reference_delay(self) -> None:
        """Hold the reference back when the echo comes back too late for AEC3."""
        coupling, lag_ms = echo_coupling(self._history_ref, self._history_in)
        if coupling < ADAPT_MIN_COUPLING or lag_ms is None:
            self._last_lag_ms = None
            return
        previous, self._last_lag_ms = self._last_lag_ms, lag_ms
        if previous is None or abs(lag_ms - previous) > ADAPT_CONSISTENT_MS:
            return
        current_ms = self._reference_delay * 1000 // APM_SAMPLE_RATE
        # Hysteresis: a path sitting right at the threshold must not toggle
        # the hold on and off, each toggle making AEC3 find the delay again.
        threshold = DIRECT_ECHO_MAX_MS - HOLD_HYSTERESIS_MS if current_ms else DIRECT_ECHO_MAX_MS
        target_ms = 0
        if lag_ms > threshold:
            target_ms = max(0, (lag_ms - ECHO_TARGET_MS) // 10 * 10)
        if abs(target_ms - current_ms) < ADAPT_MIN_STEP_MS:
            return
        new_delay = target_ms * APM_SAMPLE_RATE // 1000
        if new_delay < self._reference_delay:
            # The audio no longer held back has already been echoed: drop it
            # rather than burst it into AEC3's render buffer.
            keep = new_delay + self._ref.size - self._reference_delay
            self._ref = self._ref[max(0, self._ref.size - max(keep, new_delay)):]
        self._reference_delay = new_delay
        logging.info("[call_audio] echo returns %s ms late (coupling %s); "
                     "speaker reference now held back %s ms", lag_ms, coupling, target_ms)

    def process(self, samples: np.ndarray) -> np.ndarray:
        """Return the cleaned microphone audio.

        Output comes in whole 10 ms frames, so it can be shorter than the input
        (the remainder waits for the next call); length is conserved over the
        stream. Without a module, the input comes back as it is.
        """
        data = np.asarray(samples, dtype=np.float32).reshape(-1)
        if self._apm is None:
            return data
        self._mic = np.concatenate((self._mic, data))
        if self._echo_cancellation:
            self._feed_reference()
        out = []
        while self._mic.size >= APM_FRAME:
            chunk, self._mic = self._mic[:APM_FRAME], self._mic[APM_FRAME:]
            try:
                frame = self._frame_factory(chunk)
                self._apm.process_stream(frame)
                out.append(self._frame_reader(frame))
            except Exception:
                # A frame the module refused is sent as captured, so the other
                # person hears a moment of echo rather than a gap.
                self._errors += 1
                out.append(chunk)
            self._frames += 1
            if self._echo_cancellation:
                self._history_in = self._remember(self._history_in, chunk, MEASURE_WINDOW_S)
                self._history_out = self._remember(self._history_out, out[-1], MEASURE_WINDOW_S)
                if (self._frames % ADAPT_EVERY_FRAMES == 0
                        and self._history_in.size >= MEASURE_WINDOW_S * MEASURE_RATE):
                    self._adapt_reference_delay()
        if not out:
            return np.empty(0, dtype=np.float32)
        return np.concatenate(out)

    @staticmethod
    def _remember(history: np.ndarray, chunk: np.ndarray, seconds: float) -> np.ndarray:
        history = np.concatenate((history, decimate(np.asarray(chunk, dtype=np.float64))))
        keep = int(seconds * MEASURE_RATE)
        return history[-keep:] if history.size > keep else history

    def echo_measure(self) -> dict:
        """The speaker's echo in the microphone, before and after the module.

        ``echo_in`` near 1 with ``echo_out`` near 0 is the module working.
        ``echo_out`` staying high: the echo is in the reference and the module
        is not removing it. ``echo_in`` low while the other person hears
        themselves: the echo reaches the microphone through a path the
        reference does not carry (another program or device playing the call).
        Only meaningful while the other person talks (``speaker_dbfs``).
        """
        if not self._echo_cancellation or self._history_in.size < MEASURE_RATE:
            return {}
        echo_in, lag_in = echo_coupling(self._history_ref, self._history_in)
        echo_out, lag_out = echo_coupling(self._history_ref, self._history_out)
        return {
            "echo_in": echo_in, "echo_in_lag_ms": lag_in,
            "echo_out": echo_out, "echo_out_lag_ms": lag_out,
            "speaker_dbfs": dbfs(self._history_ref[-self._history_in.size:]),
            "mic_dbfs": dbfs(self._history_in),
            "sent_dbfs": dbfs(self._history_out),
        }

    def diagnostics(self) -> dict:
        """What the processor is doing, for the call log."""
        return {
            "engine": "webrtc" if self._apm is not None else "unavailable",
            "echo_cancellation": self._echo_cancellation,
            "noise_suppression": self._noise_suppression,
            "delay_hint_ms": self._delay_ms,
            "frames": self._frames,
            "reference_frames": self._reference_frames,
            "errors": self._errors,
            "reference_held_ms": self._reference_delay * 1000 // APM_SAMPLE_RATE,
            **self.echo_measure(),
        }
