"""A call refused because WhatsApp Web's VoIP never initialised is said so.

docs/traps/voice-calls.md: pinned main glue and Meta's live worker bundle can
disagree, VoIP never becomes ready, and the server answers a failed offer with
the page's error text. The classifier is pure; the two MainWindow methods are
called unbound against a stub.
"""

import types

import pytest

from core.call_voip_errors import VoipUnavailableError, is_voip_init_failure
from main import MainWindow


@pytest.mark.parametrize("text", [
    "WhatsApp VoIP initialization failed: WhatsApp VoIP initializer completed without becoming ready",
    '{"status":"error","message":"WhatsApp VoIP initializer completed  without\nbecoming ready"}',
    "call offer failed: without successful voipInit",
    "whatsapp voip INITIALIZATION FAILED",
])
def test_the_voip_wordings_are_recognised(text):
    assert is_voip_init_failure(text) is True


@pytest.mark.parametrize("text", [
    "", None, "HTTP 500", "chat not found", "call permission denied",
    "WhatsApp VoIP is busy",
])
def test_other_failures_are_not(text):
    assert is_voip_init_failure(text) is False


def _response(status, text):
    return types.SimpleNamespace(status_code=status, text=text)


def test_a_voip_failure_raises_the_specific_error():
    body = "x" * 600 + "WhatsApp VoIP initializer completed without becoming ready"
    with pytest.raises(VoipUnavailableError):
        MainWindow._raise_for_call_response(object(), _response(500, body), "offer")


def test_other_failures_stay_a_plain_status_error():
    with pytest.raises(RuntimeError) as err:
        MainWindow._raise_for_call_response(object(), _response(500, "boom"), "offer")
    assert not isinstance(err.value, VoipUnavailableError)
    assert str(err.value) == "HTTP 500"


def test_success_is_returned_untouched():
    ok = _response(200, "")
    assert MainWindow._raise_for_call_response(object(), ok, "offer") is ok


def test_the_error_text_is_the_localized_instruction_with_the_menu_names_filled_in():
    strings = {
        "voice_call_voip_unavailable": 'Try "{option}" in the {menu} menu.',
        "menu_help": "&Help",
        "menu_force_reinstall_wpp": "Force reinstall &WPPConnect",
    }
    stub = types.SimpleNamespace(
        i18n=types.SimpleNamespace(t=lambda key: strings.get(key, key)),
        _CALL_ERROR_MAX_SPOKEN=5,
    )
    assert MainWindow._call_error_text(stub, VoipUnavailableError("HTTP 500")) == \
        'Try "Force reinstall WPPConnect" in the Help menu.'
    assert MainWindow._call_error_text(stub, RuntimeError("HTTP 500")) == "HTTP..."


def test_every_locale_keeps_the_same_placeholders():
        from tests.locales import load_strings, registered_locale_codes
        for loc in registered_locale_codes():
            text = load_strings(loc)["voice_call_voip_unavailable"]
        assert "{menu}" in text and "{option}" in text, loc
        text.format(menu="m", option="o")  # no stray placeholder
