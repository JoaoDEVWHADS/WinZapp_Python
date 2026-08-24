"""Tests for the Settings > Conteúdo Falado "silence while recording" toggle:
AccessibleSpeechOutput's suppression gate and its silence() passthrough,
MainWindow._voice_recording_silence_active()'s gating logic, and
ConversationsPanel._silence_send_voice_focus_if_enabled()'s double-fire (now
+ delayed) attempt to catch the screen reader's Enviar-button focus
announcement whichever way it schedules its speech."""

import types

import ui.conversations as conversations_module
from core.accessible_speech import AccessibleSpeechOutput
from ui.conversations import ConversationsPanel


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


class TestSilenceSendVoiceFocusIfEnabled:
    class _FakeSpeakOutput:
        def __init__(self):
            self.silence_calls = 0

        def silence(self):
            self.silence_calls += 1

    class _FakeMainWindow:
        def __init__(self, enabled):
            self.settings = {"speech_content": {"silence_while_recording": enabled}}
            self.speak_output = TestSilenceSendVoiceFocusIfEnabled._FakeSpeakOutput()

    def _make_stub(self, enabled):
        stub = types.SimpleNamespace()
        stub.main_window = self._FakeMainWindow(enabled)
        stub._silence_send_voice_focus_if_enabled = types.MethodType(
            ConversationsPanel._silence_send_voice_focus_if_enabled, stub
        )
        return stub

    def test_noop_when_setting_disabled(self, monkeypatch):
        call_later_calls = []
        monkeypatch.setattr(
            conversations_module.wx, "CallLater",
            lambda delay, func: call_later_calls.append((delay, func)),
        )
        stub = self._make_stub(enabled=False)
        stub._silence_send_voice_focus_if_enabled()
        assert stub.main_window.speak_output.silence_calls == 0
        assert call_later_calls == []

    def test_fires_immediately_and_schedules_a_delayed_retry(self, monkeypatch):
        call_later_calls = []
        monkeypatch.setattr(
            conversations_module.wx, "CallLater",
            lambda delay, func: call_later_calls.append((delay, func)),
        )
        stub = self._make_stub(enabled=True)
        stub._silence_send_voice_focus_if_enabled()

        # Immediate call covers a screen reader that speaks synchronously.
        assert stub.main_window.speak_output.silence_calls == 1
        # A second, delayed call is scheduled to catch the far more common
        # case of the screen reader announcing the focus asynchronously.
        assert len(call_later_calls) == 1
        delay, func = call_later_calls[0]
        assert delay > 0
        func()
        assert stub.main_window.speak_output.silence_calls == 2
