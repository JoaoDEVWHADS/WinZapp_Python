"""Tests for the Settings > Audio Devices tab's underlying device-selection
and failure-fallback logic.

Devices are stored in settings by friendly name (not raw index — BASS/
PortAudio indices aren't stable across reboots or device (dis)connections),
so device-name matching (`_match_device`) is the piece most worth covering in
isolation. `SoundSystem.apply_output_device`/`handle_playback_failure` are
exercised against a stub BASS `Output` object standing in for
sound_lib.output.Output, since a real one needs an actual audio device.
"""

import core.sound_system as sound_system_module
from core.audio_devices import _match_device
from core.sound_system import SoundSystem


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
    raises for indices in `fail_indices`, like a device that fails to open."""

    def __init__(self, fail_indices=None):
        self.fail_indices = fail_indices or set()
        self.current = -1
        self.set_device_calls = []

    def set_device(self, device):
        self.set_device_calls.append(device)
        if device in self.fail_indices:
            raise Exception("simulated BASS device error")
        self.current = device


class _StubMainWindow:
    def __init__(self):
        # background_mode=True keeps _warn_device_failure from touching wx
        # (no wx.App is running in these tests).
        self.background_mode = True
        self.app_name = "WinZapp"


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


class TestHandlePlaybackFailure:
    def test_no_configured_device_means_nothing_to_fall_back_from(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {})
        assert ss.handle_playback_failure() is False

    def test_first_failure_falls_back_and_reports_true(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        assert ss.handle_playback_failure() is True
        assert ss.output.current == -1

    def test_repeated_failures_only_warn_once_per_session(self, monkeypatch):
        ss = _make_sound_system(monkeypatch, {"Speakers": 1})
        ss.apply_output_device("Speakers")
        assert ss.handle_playback_failure() is True
        # Same broken device failing again and again shouldn't keep
        # popping message boxes for the rest of the session.
        assert ss.handle_playback_failure() is False
        assert ss.handle_playback_failure() is False
