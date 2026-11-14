"""Calls on the Neonize engine: the bridge cannot place or answer them.

Audit F4, M5: it answers 501 to call/offer and call/accept but still reports
incoming calls and can reject them. Calling and Answering used to open the
microphone and the speakers first and only then post, so the user heard "HTTP
501" after a failed audio start. Now they refuse up front, with sentences the
catalogs already have, before any device is touched; Reject is unaffected.
"""
import types

from main import MainWindow


class _I18n:
    @staticmethod
    def t(key):
        return {
            "voice_call_start_failed": "Could not start the call: {error}",
            "incoming_call_answer_failed": "Could not answer the call: {error}",
            "call_log_action_unavailable": "This action is not available for calls.",
        }.get(key, key)


def _window(neonize):
    spoken = []

    def forbidden(*args, **kwargs):
        raise AssertionError("a device or a request was used for a call the bridge cannot take")

    return types.SimpleNamespace(
        i18n=_I18n(), spoken=spoken, _uses_neonize=lambda: neonize,
        output=lambda text, interrupt=False: spoken.append(text),
        _normalize_jid=lambda jid: jid, _is_self_jid=lambda jid: False,
        _active_voice_call=None, _active_incoming_calls={}, _incoming_call_details={},
        _start_voice_call_audio=forbidden, _post_call_control=forbidden,
        _build_call_audio_session=forbidden, stop_incoming_call_alert=forbidden,
    )


def test_calling_is_refused_before_any_device_or_request():
    window = _window(neonize=True)
    MainWindow._start_call(window, "5511999990000@s.whatsapp.net", "Ana",
                           is_video=False, is_group=False)
    assert window.spoken == ["Could not start the call: This action is not available for calls."]
    assert window._active_voice_call is None


def test_answering_is_refused_before_any_device_or_request():
    window = _window(neonize=True)
    window._active_incoming_calls = {"call-1": True}
    MainWindow.accept_incoming_call(window, "call-1")
    assert window.spoken == [
        "Could not answer the call: This action is not available for calls."]


def test_the_rejection_path_is_not_touched():
    import inspect
    source = inspect.getsource(MainWindow.reject_incoming_call)
    assert "_uses_neonize" not in source
