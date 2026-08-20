"""Regression coverage for ConversationsPanel._start_voice_recording()'s
background stream open (_bg_open_stream).

Opening the PyAudio input stream moved off the UI thread because pa.open()
can block for seconds negotiating with the driver. That handed the method a
new failure mode: _recording_starting is set to True *before* the thread
starts and only _on_stream_opened() ever sets it back to False, so anything
that stops _on_stream_opened() from being scheduled leaves the flag stuck.
on_record_voice_message() gates on `elif not self._recording_starting`, so a
stuck flag means the record button silently stops responding for the rest of
the session — no dialog, no sound, and (in a daemon thread) no traceback
anywhere the user can see.

find_input_device_index() is the realistic raiser: core.audio_devices'
_pyaudio_input_devices() falls back to an unguarded get_default_host_api_info()
when the WASAPI query fails, which is exactly the kind of broken audio stack
the background open exists to survive in the first place.

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App, so the method under test is bound onto a plain stub carrying only the
attributes it touches, matching the pattern used throughout this suite (see
test_voice_recording_unavailable.py).
"""

import threading
import types

import pytest

import ui.conversations as conversations_module
from ui.conversations import ConversationsPanel


class _FakeI18n:
    def t(self, key):
        return key


class _FakeMainWindow:
    def __init__(self, device_name="Microfone USB"):
        self.i18n = _FakeI18n()
        self.output_calls = []
        # Non-empty so _bg_open_stream() actually calls
        # find_input_device_index() — the raiser under test.
        self.effective_input_device_name = device_name

    def output(self, text):
        self.output_calls.append(text)


class _Stub:
    _start_voice_recording = ConversationsPanel._start_voice_recording

    def __init__(self):
        self.conversation = {"remoteJid": "5511999999999@s.whatsapp.net"}
        self.main_window = _FakeMainWindow()
        # Not None, so the method skips constructing a real pyaudio.PyAudio()
        # (which would talk to the actual audio hardware).
        self._recording_pa = object()
        self._recording_starting = False
        self._recording_open_token = 0
        self._is_recording = False
        self._recording_stream = None


@pytest.fixture
def scheduled(monkeypatch):
    """Capture wx.CallAfter(...) instead of dispatching it, and expose an
    Event so the test can wait for the background thread deterministically."""
    calls = []
    fired = threading.Event()

    def _fake_call_after(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        fired.set()

    monkeypatch.setattr(conversations_module.wx, "CallAfter", _fake_call_after)
    # A stand-in for the real module: present (so the method doesn't take the
    # "PyAudio not installed" early return) but never actually touched,
    # because find_input_device_index() raises first.
    monkeypatch.setattr(
        conversations_module,
        "pyaudio",
        types.SimpleNamespace(paInt16=8, paContinue=0),
    )
    return calls, fired


def _boom(*_args, **_kwargs):
    raise OSError("no default host API")


def test_stream_open_failure_still_schedules_the_callback(scheduled, monkeypatch):
    """An exception inside the background thread must not swallow the
    wx.CallAfter — otherwise _on_stream_opened() never runs."""
    calls, fired = scheduled
    monkeypatch.setattr(conversations_module, "find_input_device_index", _boom)

    stub = _Stub()
    stub._start_voice_recording()

    assert fired.wait(timeout=5), "background thread never scheduled _on_stream_opened"
    assert len(calls) == 1
    _func, args, _kwargs = calls[0]
    stream, rate, ch, fell_back = args
    # Nothing opened, and no device fallback was reached before the raise.
    assert stream is None
    assert rate is None
    assert ch is None
    assert fell_back is False


def test_recording_flag_is_released_after_a_failed_open(scheduled, monkeypatch):
    """The whole point of the callback still running: the flag it clears is
    what on_record_voice_message() checks before allowing another attempt."""
    calls, fired = scheduled
    monkeypatch.setattr(conversations_module, "find_input_device_index", _boom)

    stub = _Stub()
    stub._start_voice_recording()
    assert stub._recording_starting is True, "flag should be set while opening"

    assert fired.wait(timeout=5)
    func, args, _kwargs = calls[0]
    func(*args)  # what wx would have run on the main thread

    assert stub._recording_starting is False
    # A failed open must not leave the panel believing it is recording.
    assert stub._is_recording is False
    assert stub._recording_stream is None


def test_record_button_still_responds_after_a_failed_open(scheduled, monkeypatch):
    """End-to-end guard on the actual user-visible symptom: the second press
    of the record button must reach _start_voice_recording() again."""
    calls, fired = scheduled
    monkeypatch.setattr(conversations_module, "find_input_device_index", _boom)

    stub = _Stub()
    stub._start_voice_recording()
    assert fired.wait(timeout=5)
    func, args, _kwargs = calls[0]
    func(*args)

    # Replay on_record_voice_message()'s own guard rather than trusting the
    # flag by name: this is the condition that used to be permanently False.
    reached = []
    stub._start_voice_recording = lambda: reached.append(True)
    if stub._is_recording:
        pass
    elif not stub._recording_starting:
        stub._start_voice_recording()

    assert reached == [True], "record button stayed dead after a failed open"
