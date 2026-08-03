"""Tests for the Settings > Audio Devices tab's underlying device-selection
and failure-fallback logic.

Devices are stored in settings by friendly name (not raw index — BASS/
PortAudio indices aren't stable across reboots or device (dis)connections),
so device-name matching (`_match_device`) is the piece most worth covering in
isolation. `SoundSystem.apply_output_device`/`handle_playback_failure` are
exercised against a stub BASS `Output` object standing in for
sound_lib.output.Output, since a real one needs an actual audio device.
"""

import ctypes

import core.audio_devices as audio_devices_module
import core.sound_system as sound_system_module
from core.audio_devices import _match_device, enumerate_output_devices
from core.sound_system import SoundSystem


class TestEnumerateOutputDevices:
    """BASS always lists a device literally named "Default" (with
    BASS_DEVICE_DEFAULT set) ahead of the real hardware entries — confirmed
    against a real machine's device list. Left unfiltered, that showed up in
    the Settings > Audio Devices output combo as a second, redundant "use
    the default" choice alongside the combo's own sentinel first entry."""

    def test_skips_the_bass_default_pseudo_device(self, monkeypatch):
        import sound_lib.external.pybass as pybass

        # (enabled, name) per 1-based BASS device index; a falsy entry (or a
        # missing one) ends the enumeration, like the real BASS_GetDeviceInfo
        # returning 0 past the last device.
        fake_devices = {
            1: (True, b"Default"),
            2: (True, b"Fone de ouvido do headset (CORSAIR HS80)"),
            3: (False, b"Some Disabled Device"),
        }

        def fake_get_device_info(count, info_ref):
            entry = fake_devices.get(count)
            if entry is None:
                return 0
            enabled, name = entry
            info = info_ref._obj
            info.flags = pybass.BASS_DEVICE_ENABLED if enabled else 0
            info.name = name
            return 1

        monkeypatch.setattr(pybass, "BASS_GetDeviceInfo", fake_get_device_info)

        devices = enumerate_output_devices()

        assert devices == [(2, "Fone de ouvido do headset CORSAIR HS80")]


class TestMatchDevice:
    def test_finds_matching_name(self):
        devices = [(1, "Speakers"), (2, "Headphones")]
        assert _match_device("Headphones", devices) == 2

    def test_no_match_returns_none(self):
        assert _match_device("USB Mic", [(1, "Speakers")]) is None

    def test_empty_name_is_system_default_sentinel(self):
        # "" means "use the Windows default" — never something to look up.
        assert _match_device("", [(1, "Speakers")]) is None
        assert _match_device(None, [(1, "Speakers")]) is None


class _StubOutput:
    """Stands in for sound_lib.output.Output: records set_device() calls and
    raises for indices in `fail_indices`, like a device that fails to open.
    Also exposes _device/free()/init_device() — SoundSystem._switch_to_default_device()
    uses those directly instead of set_device(-1), which real BASS rejects
    outright (see the docstring on that method)."""

    def __init__(self, fail_indices=None):
        self.fail_indices = fail_indices or set()
        self.current = -1
        self._device = -1
        self.set_device_calls = []
        self.free_calls = 0

    def set_device(self, device):
        self.set_device_calls.append(device)
        if device in self.fail_indices:
            raise Exception("simulated BASS device error")
        self.current = device
        self._device = device

    def free(self):
        self.free_calls += 1

    def init_device(self, device=None):
        self._device = device
        self.current = device


class _StubMainWindow:
    def __init__(self):
        # background_mode=True keeps _warn_device_failure from touching wx
        # (no wx.App is running in these tests).
        self.background_mode = True
        self.app_name = "WinZapp"
        self.load_sounds_calls = 0

    def load_sounds(self):
        self.load_sounds_calls += 1


def _make_sound_system(monkeypatch, name_to_index, fail_indices=None):
    ss = SoundSystem(_StubMainWindow(), sound_dir="C:\\nonexistent")
    ss.output = _StubOutput(fail_indices=fail_indices)
    monkeypatch.setattr(
        sound_system_module, "find_output_device_index", lambda name: name_to_index.get(name)
    )
    return ss


class TestApplyOutputDevice:
    def test_empty_name_means_default(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {})
        assert ss.apply_output_device("") is True
        assert ss.output.current == -1

    def test_known_device_switches_to_it(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        assert ss.apply_output_device("Speakers") is True
        assert ss.output.current == 1
        assert ss._configured_output_device == "Speakers"

    def test_unknown_device_falls_back_to_default(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {})
        assert ss.apply_output_device("Ghost Device") is False
        assert ss.output.current == -1

    def test_device_that_fails_to_open_falls_back_to_default(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Broken": 2}, fail_indices={2})
        assert ss.apply_output_device("Broken") is False
        assert ss.output.current == -1

    def test_switching_resets_the_warned_flag(self, monkeypatch):
        # A fresh device choice (e.g. the user picked a different one in
        # Settings) should get its own chance to warn on a later failure,
        # not inherit "already warned" from whatever was configured before.
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss._warned_output_failure = True
        ss.apply_output_device("Speakers")
        assert ss._warned_output_failure is False

    def test_switching_back_to_default_uses_free_and_init_not_set_device(self, monkeypatch):
        # Regression: sound_lib.output.Output.set_device(-1) always raised
        # "illegal device number" on real BASS — it calls BASS_SetDevice(-1)
        # internally, and -1 is only ever valid as a BASS_Init() argument.
        # That exception used to be silently swallowed, so "switch back to
        # default" was a no-op lying about success: the previously-selected
        # device stayed active. Confirmed live against a real BASS device
        # before writing this fix.
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        assert ss.output.current == 1

        ss.apply_output_device("")

        assert ss.output.current == -1
        assert ss.output.free_calls == 1
        # -1 must never reach set_device() — only real device indices do.
        assert -1 not in ss.output.set_device_calls


class TestHandlePlaybackFailure:
    def test_no_configured_device_means_nothing_to_fall_back_from(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {})
        assert ss.handle_playback_failure() is False

    def test_first_failure_falls_back_and_reports_true(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        assert ss.handle_playback_failure() is True
        assert ss.output.current == -1

    def test_reloads_cached_sound_events_after_falling_back(self, monkeypatch):
        # BASS_Free()/BASS_Init() during the fallback invalidates every
        # cached Settings > Sound Events stream (startup_sound, error_sound,
        # ...) that existed before it — reloading them here is what lets
        # future calls to those cached objects recover on their own, instead
        # of every one of their many call sites needing its own retry logic.
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        ss.handle_playback_failure()
        assert ss.main_window.load_sounds_calls == 1

    def test_repeated_failures_only_warn_once_per_session(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        assert ss.handle_playback_failure() is True
        # Same broken device failing again and again shouldn't keep
        # popping message boxes for the rest of the session.
        assert ss.handle_playback_failure() is False
        assert ss.handle_playback_failure() is False


class _FakePyAudioStream:
    def close(self):
        pass


class _FakePyAudio:
    """Stands in for pyaudio.PyAudio: accepts open() only for the exact
    (rate, channels) pairs in `accepted_configs`, like a real device that
    only supports its own native sample rate."""

    def __init__(self, accepted_configs):
        self.accepted_configs = accepted_configs
        self.opened_with = []

    def open(self, rate, channels, format, input, input_device_index, frames_per_buffer, start):
        self.opened_with.append((rate, channels))
        if (rate, channels) not in self.accepted_configs:
            raise OSError(-9997, "Invalid sample rate")
        return _FakePyAudioStream()

    def terminate(self):
        pass


class TestTestInputDevice:
    """Regression coverage for a real bug: hardcoding a single (44100, 1)
    test config rejected every device on a machine where every WASAPI
    device's native rate was 48000 — "Invalid sample rate" for every one of
    them, regardless of the device actually being fine. The test now walks
    the same fallback chain _start_voice_recording() itself uses."""

    def test_succeeds_on_the_first_supported_combo(self, monkeypatch):
        fake_pa = _FakePyAudio(accepted_configs={(48000, 1)})
        monkeypatch.setattr(audio_devices_module.pyaudio, "PyAudio", lambda: fake_pa)
        assert audio_devices_module.test_input_device(5) is True
        assert fake_pa.opened_with == [(48000, 1)]

    def test_falls_back_to_a_later_combo(self, monkeypatch):
        # Only the very last combo in the fallback chain works.
        fake_pa = _FakePyAudio(accepted_configs={(44100, 2)})
        monkeypatch.setattr(audio_devices_module.pyaudio, "PyAudio", lambda: fake_pa)
        assert audio_devices_module.test_input_device(5) is True
        assert fake_pa.opened_with == audio_devices_module.RECORDING_SAMPLE_CONFIGS

    def test_fails_only_when_no_combo_is_supported(self, monkeypatch):
        fake_pa = _FakePyAudio(accepted_configs=set())
        monkeypatch.setattr(audio_devices_module.pyaudio, "PyAudio", lambda: fake_pa)
        assert audio_devices_module.test_input_device(5) is False
        assert fake_pa.opened_with == audio_devices_module.RECORDING_SAMPLE_CONFIGS
