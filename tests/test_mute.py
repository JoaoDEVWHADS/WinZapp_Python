"""Tests for muting a chat.

No chat could be muted at all. WPPConnect's /send-mute route ran the legacy
``WAPI.sendMute`` shim, which drives ``Store.SendMute.sendConversationMute()``
and then decides success purely from ``response.status === 200``. On current
WhatsApp Web builds that no longer holds, so every mute came back as HTTP 500
with a hardcoded ``"This chat is already mute"`` — a string the shim emits for
*any* non-200, regardless of the chat's real state. A live example:

    [mute_chat] API error 500 for 120363151058129530@g.us:
    {"status":"error","message":"Error on send mute","error":{...
     "erro":true,"text":"This chat is already mute","type":"sendMute",...}}

WinZapp treated that as a rejection and rolled its optimistic mute back, so the
chat un-muted itself and the user got an error dialog. The real fix is the
patched sendMute controller (which uses ``WPP.chat.mute``); mute_response_accepted()
keeps the client correct against an API build that predates that patch.

The mute-duration presets are also checked here: the row context menu and the
Alt+Shift+S accelerator must offer exactly the same list, which is why they now
both build it from ConversationsPanel.MUTE_PRESETS.
"""

import pytest

from core.utils import mute_response_accepted
from ui.conversations import ConversationsPanel

# The exact body observed in the field, trimmed to what matters.
_ALREADY_MUTE_500 = (
    '{"status":"error","message":"Error on send mute","error":'
    '{"erro":true,"text":"This chat is already mute","type":"sendMute",'
    '"time":8,"timeType":"hours"},"session":"f61ec0d2"}'
)
_NOT_MUTE_500 = (
    '{"status":"error","message":"Error on send mute","error":'
    '{"erro":true,"text":"is not mute to remove","type":"sendMute"}}'
)


class TestMuteResponseAccepted:
    def test_a_plain_success_is_accepted(self):
        assert mute_response_accepted(True, '{"status":"success"}', is_unmute=False) is True
        assert mute_response_accepted(True, "", is_unmute=True) is True

    def test_already_mute_is_the_desired_end_state(self):
        assert mute_response_accepted(False, _ALREADY_MUTE_500, is_unmute=False) is True

    def test_already_mute_does_not_excuse_a_failed_unmute(self):
        """"Already muted" is precisely NOT what an unmute asked for."""
        assert mute_response_accepted(False, _ALREADY_MUTE_500, is_unmute=True) is False

    def test_not_mute_to_remove_is_the_desired_end_state_for_an_unmute(self):
        assert mute_response_accepted(False, _NOT_MUTE_500, is_unmute=True) is True

    def test_not_mute_to_remove_does_not_excuse_a_failed_mute(self):
        assert mute_response_accepted(False, _NOT_MUTE_500, is_unmute=False) is False

    def test_a_real_failure_is_still_a_failure(self):
        body = '{"erro":true,"to":"5511@c.us","status":404}'
        assert mute_response_accepted(False, body, is_unmute=False) is False
        assert mute_response_accepted(False, body, is_unmute=True) is False

    def test_an_empty_or_missing_body_is_a_failure(self):
        assert mute_response_accepted(False, "", is_unmute=False) is False
        assert mute_response_accepted(False, None, is_unmute=False) is False

    def test_matching_is_case_insensitive(self):
        assert mute_response_accepted(False, "THIS CHAT IS ALREADY MUTE", is_unmute=False) is True


class TestMutePresets:
    def test_durations_are_positive_or_the_permanent_sentinel(self):
        for key, secs in ConversationsPanel.MUTE_PRESETS:
            assert key.startswith("mute_")
            assert secs == -1 or secs > 0, key

    def test_presets_are_ordered_shortest_first_with_permanent_last(self):
        secs = [s for _, s in ConversationsPanel.MUTE_PRESETS]
        assert secs[-1] == -1, "'always' must be the last option"
        assert secs[:-1] == sorted(secs[:-1])

    def test_the_week_option_the_user_asked_for_exists(self):
        presets = dict(ConversationsPanel.MUTE_PRESETS)
        assert presets["mute_1w"] == 7 * 24 * 3600

    def test_every_preset_key_is_translated_in_every_locale(self):
        import json

        from tests.locales import LANGUAGES_DIR, registered_locale_codes

        langs = LANGUAGES_DIR
        # From language_map.json rather than written out: pl was missing from
        # the list this replaces, so it was never checked at all. Through the
        # shared helper so an empty map cannot turn this loop into zero
        # iterations and still pass — see tests/locales.py.
        for locale in registered_locale_codes():
            strings = json.loads((langs / f"{locale}.json").read_text(encoding="utf-8"))
            for key, _ in ConversationsPanel.MUTE_PRESETS:
                assert strings.get(key), f"{locale} is missing {key}"
            assert strings.get("mute_chat_menu_title"), locale
