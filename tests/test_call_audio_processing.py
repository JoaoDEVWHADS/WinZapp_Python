"""CallAudioProcessor: 10 ms framing around WebRTC's audio processing module."""

import numpy as np

from core.call_audio_processing import APM_FRAME, APM_SAMPLE_RATE, CallAudioProcessor


class _Frame:
    def __init__(self, samples):
        self.samples = np.asarray(samples, dtype=np.float32).copy()


class _Apm:
    """Records the call order; halves every near-end frame it processes."""

    def __init__(self, log, *, fail_stream=False):
        self.log = log
        self.fail_stream = fail_stream
        self.delays = []

    def set_stream_delay_ms(self, delay):
        self.delays.append(delay)

    def process_reverse_stream(self, frame):
        assert frame.samples.size == APM_FRAME
        self.log.append("ref")

    def process_stream(self, frame):
        assert frame.samples.size == APM_FRAME
        self.log.append("mic")
        if self.fail_stream:
            raise RuntimeError("refused")
        frame.samples *= 0.5


def _processor(log, *, echo=True, noise=False, **apm_kwargs):
    built = []

    def factory(**kwargs):
        built.append(kwargs)
        return _Apm(log, **apm_kwargs)

    processor = CallAudioProcessor(
        echo_cancellation=echo, noise_suppression=noise, apm_factory=factory,
        frame_factory=_Frame, frame_reader=lambda frame: frame.samples)
    return processor, built


def test_the_module_is_built_with_the_configured_features():
    _, built = _processor([], echo=True, noise=False)
    assert built == [{"echo_cancellation": True, "noise_suppression": False}]


def test_output_comes_in_whole_10ms_frames_and_conserves_length():
    processor, _ = _processor([])
    total = 0
    for size in (100, 960, 333, 1000, 487):
        total += processor.process(np.ones(size, dtype=np.float32)).size
    assert total == (100 + 960 + 333 + 1000 + 487) // APM_FRAME * APM_FRAME
    assert processor.process(np.ones(10, dtype=np.float32)).size == 0


def test_the_module_output_is_what_comes_back():
    processor, _ = _processor([])
    out = processor.process(np.full(APM_FRAME * 2, 0.4, dtype=np.float32))
    assert np.allclose(out, 0.2)


def test_reference_reaches_the_module_in_10ms_frames_before_the_microphone():
    log = []
    processor, _ = _processor(log)
    processor.push_reference(np.zeros(APM_FRAME + 100, dtype=np.float32))
    processor.process(np.zeros(APM_FRAME, dtype=np.float32))
    processor.push_reference(np.zeros(APM_FRAME - 100, dtype=np.float32))
    processor.process(np.zeros(APM_FRAME, dtype=np.float32))
    assert log == ["ref", "mic", "ref", "mic"]


def test_a_held_back_reference_reaches_the_module_that_much_later():
    log = []
    processor, _ = _processor(log)
    processor._reference_delay = APM_FRAME * 3
    processor.push_reference(np.zeros(APM_FRAME * 4, dtype=np.float32))
    processor.process(np.zeros(APM_FRAME, dtype=np.float32))
    assert log == ["ref", "mic"]
    processor.push_reference(np.zeros(APM_FRAME, dtype=np.float32))
    processor.process(np.zeros(APM_FRAME, dtype=np.float32))
    assert log == ["ref", "mic", "ref", "mic"]


def test_reference_is_ignored_when_only_noise_suppression_is_on():
    log = []
    processor, _ = _processor(log, echo=False, noise=True)
    processor.push_reference(np.zeros(APM_FRAME * 3, dtype=np.float32))
    assert log == []


def test_a_refused_frame_is_sent_as_captured():
    processor, _ = _processor([], fail_stream=True)
    data = np.full(APM_FRAME, 0.3, dtype=np.float32)
    assert np.allclose(processor.process(data), 0.3)
    assert processor.diagnostics()["errors"] == 1


def test_a_missing_module_passes_the_microphone_through_and_logs_once(caplog):
    calls = []

    def broken(**kwargs):
        calls.append(kwargs)
        raise ImportError("no livekit")

    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False,
                                   apm_factory=broken)
    processor.reset()
    data = np.arange(7, dtype=np.float32)
    assert np.array_equal(processor.process(data), data)
    assert not processor.available
    assert processor.diagnostics()["engine"] == "unavailable"
    assert len(calls) == 1
    assert caplog.text.count("WebRTC audio processing unavailable") == 1


def test_the_delay_hint_is_rounded_and_survives_a_reset():
    log = []
    processor, _ = _processor(log)
    processor.set_stream_delay_ms(37.6)
    assert processor._apm.delays[-1] == 38
    processor.reset()
    assert processor._apm.delays == [38]
    processor.set_stream_delay_ms(-5)
    assert processor._apm.delays[-1] == 0


def test_the_release_builds_ship_the_webrtc_library():
    # livekit_ffi.dll is a data file loaded through importlib.resources:
    # without --collect-all the frozen app has no echo cancellation at all.
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    collect_all = (root / "build.py").read_text(encoding="utf-8").split(
        "collect_all = [", 1)[1].split("]", 1)[0]
    assert '"livekit"' in collect_all
    assert '"livekit"' in (root / "macos" / "build_app.py").read_text(encoding="utf-8")


def test_the_real_webrtc_module_removes_a_delayed_echo():
    rng = np.random.default_rng(11)
    far = (rng.standard_normal(APM_SAMPLE_RATE * 5) * 0.1).astype(np.float32)
    mic = np.zeros_like(far)
    mic[2400:] = far[:-2400] * 0.9
    processor = CallAudioProcessor(echo_cancellation=True, noise_suppression=False)
    assert processor.available
    out = []
    for i in range(0, len(far), 960):
        processor.push_reference(far[i:i + 960])
        out.append(processor.process(mic[i:i + 960]))
    out = np.concatenate(out)
    tail = slice(-APM_SAMPLE_RATE, None)
    reduction_db = 10 * np.log10(np.mean(mic[tail] ** 2) / np.mean(out[tail] ** 2))
    assert reduction_db > 25
