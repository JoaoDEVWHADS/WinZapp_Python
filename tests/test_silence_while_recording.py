"""Tests for the Settings > Conteúdo Falado "silence while recording" toggle:
AccessibleSpeechOutput's suppression gate and its silence() passthrough, plus
MainWindow._voice_recording_silence_active()'s gating logic."""

import types

from core.accessible_speech import AccessibleSpeechOutput


class _FakeOutput:
    def __init__(self):
        self.spoken = []
        self.silenced = False

    def speak(self, text, **options):
        self.spoken.append(text)

    def silence(self):
        self.silenced = True


class _FakeAuto:
    def __init__(self, output):
        self._output = output
        self.outputs = [output]

    def get_first_available_output(self):
        return self._output


class TestAccessibleSpeechOutputSuppression:
    def test_output_dropped_while_suppressed(self):
        fake = _FakeOutput()
        speech = AccessibleSpeechOutput(
            _FakeAuto(fake), lambda: {}, suppressed_getter=lambda: True
        )
        speech.output("hello")
        assert fake.spoken == []

    def test_output_spoken_when_not_suppressed(self):
        fake = _FakeOutput()
        speech = AccessibleSpeechOutput(
            _FakeAuto(fake), lambda: {}, suppressed_getter=lambda: False
        )
        speech.output("hello")
        assert fake.spoken == ["hello"]

    def test_output_spoken_when_no_suppressed_getter_given(self):
        fake = _FakeOutput()
        speech = AccessibleSpeechOutput(_FakeAuto(fake), lambda: {})
        speech.output("hello")
        assert fake.spoken == ["hello"]

    def test_silence_bypasses_suppression(self):
        fake = _FakeOutput()
        speech = AccessibleSpeechOutput(
            _FakeAuto(fake), lambda: {}, suppressed_getter=lambda: True
        )
        speech.silence()
        assert fake.silenced is True

    def test_silence_noop_when_output_lacks_silence(self):
        class _NoSilenceOutput:
            def speak(self, text, **options):
                pass

        speech = AccessibleSpeechOutput(_FakeAuto(_NoSilenceOutput()), lambda: {})
        speech.silence()  # must not raise

    def test_silence_respects_accessibility_master_switch(self):
        fake = _FakeOutput()
        speech = AccessibleSpeechOutput(
            _FakeAuto(fake),
            lambda: {"accessibility": {"extended_sr_compat_enabled": False}},
        )
        speech.silence()
        assert fake.silenced is False


class TestVoiceRecordingSilenceActive:
    def _make_stub(self, silence_setting, is_recording, has_panel=True):
        stub = types.SimpleNamespace()
        stub.settings = {"speech_content": {"silence_while_recording": silence_setting}}
        if has_panel:
            stub.conversations_panel = types.SimpleNamespace(_is_recording=is_recording)
        from main import MainWindow
        stub._voice_recording_silence_active = types.MethodType(
            MainWindow._voice_recording_silence_active, stub
        )
        return stub

    def test_false_when_setting_disabled(self):
        stub = self._make_stub(silence_setting=False, is_recording=True)
        assert stub._voice_recording_silence_active() is False

    def test_false_when_setting_enabled_but_not_recording(self):
        stub = self._make_stub(silence_setting=True, is_recording=False)
        assert stub._voice_recording_silence_active() is False

    def test_true_when_setting_enabled_and_recording(self):
        stub = self._make_stub(silence_setting=True, is_recording=True)
        assert stub._voice_recording_silence_active() is True

    def test_false_when_no_conversations_panel_yet(self):
        stub = self._make_stub(silence_setting=True, is_recording=True, has_panel=False)
        assert stub._voice_recording_silence_active() is False
