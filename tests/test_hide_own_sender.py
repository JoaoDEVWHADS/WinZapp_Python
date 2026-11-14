"""Settings > User Interface > "Hide the sender on my own messages in the
messages list" (user_interface.hide_own_sender_in_message_list, default off).

Only the lead of the user's own message rows changes; incoming rows keep their
sender and the self-reference word stays in use everywhere else (reactions,
mentions, quoted replies, group notices). The row is exercised against a stub
that binds the real _render_message_line(), as tests/test_forwarded_prefix_setting.py
does, because ConversationsPanel is a wx.Panel.
"""
import pytest

from core.utils import DEFAULT_SETTINGS
from ui.conversation_panel.own_sender import (
    hide_own_sender_enabled,
    row_lead,
    should_hide_sender,
)
from ui.conversation_panel.message_rendering import MessageRenderingMixin

ON = {"user_interface": {"hide_own_sender_in_message_list": True}}


def test_the_setting_ships_off():
    assert DEFAULT_SETTINGS["user_interface"]["hide_own_sender_in_message_list"] is False


@pytest.mark.parametrize("settings,expected", [
    (ON, True),
    ({"user_interface": {"hide_own_sender_in_message_list": False}}, False),
    ({"user_interface": {"hide_own_sender_in_message_list": "yes"}}, False),
    ({"user_interface": {}}, False),
    ({"user_interface": None}, False),
    ({}, False),
    (None, False),
])
def test_only_an_explicit_true_enables_it(settings, expected):
    assert hide_own_sender_enabled(settings) is expected


def test_only_my_own_non_call_messages_lose_their_sender():
    mine = {"key": {"fromMe": True}, "messageType": "conversation"}
    theirs = {"key": {"fromMe": False}, "messageType": "conversation"}
    assert should_hide_sender(mine, ON) is True
    assert should_hide_sender(theirs, ON) is False
    assert should_hide_sender(mine, {}) is False
    assert should_hide_sender("not a message", ON) is False


def test_a_call_record_keeps_its_sender():
    from core.call_log import CALL_LOG_MESSAGE_TYPE
    call = {"key": {"fromMe": True}, "messageType": CALL_LOG_MESSAGE_TYPE}
    assert should_hide_sender(call, ON) is False


@pytest.mark.parametrize("sender,replying,hide,expected", [
    ("Eu", "", False, "Eu: oi"),
    ("Eu", "respondendo a Ana", False, "Eu, respondendo a Ana: oi"),
    ("Eu", "", True, "oi"),
    ("Eu", "respondendo a Ana", True, "respondendo a Ana: oi"),
])
def test_row_lead(sender, replying, hide, expected):
    assert row_lead(sender, replying, "oi", hide) == expected


class _FakeI18n:
    def t(self, key):
        return {"replying_to": "respondendo a {name}"}.get(key, f"[{key}]")


class _Stub:
    _render_message_line = MessageRenderingMixin._render_message_line
    _is_message_forwarded = MessageRenderingMixin._is_message_forwarded
    _is_system_event = staticmethod(MessageRenderingMixin._is_system_event)

    def __init__(self, hide, quoted=""):
        self.main_window = type("MW", (), {
            "settings": {"user_interface": {"hide_own_sender_in_message_list": hide}},
            "i18n": _FakeI18n(),
        })()
        self._quoted = quoted
        self._message_list_mode = "classic"
        self._media_upload_progress = {}
        self._upload_stages_seen = {}
        self.selected_messages = set()

    def _is_separator(self, msg):
        return False

    def _extract_timestamp(self, msg):
        return 0

    def _format_date(self, ts):
        return ""

    def _get_message_content(self, msg):
        return "oi"

    def _sender_label(self, msg):
        return "Eu" if msg["key"]["fromMe"] else "Ana"

    def _map_status(self, msg):
        return ""

    def _get_context_info(self, msg):
        return {"quotedMessage": {}} if self._quoted else None

    def _get_quoted_sender(self, ctx, msg):
        return self._quoted

    def _get_quoted_preview(self, quoted):
        return ""

    def _reaction_counts(self, msg_id):
        return {}


def _msg(from_me):
    return {"key": {"id": "M1", "fromMe": from_me}, "messageType": "conversation",
            "message": {"conversation": "oi"}}


def test_default_keeps_the_sender_on_every_row():
    stub = _Stub(hide=False)
    assert stub._render_message_line(_msg(True)) == "Eu: oi"
    assert stub._render_message_line(_msg(False)) == "Ana: oi"


def test_my_row_starts_with_its_content_and_incoming_rows_keep_the_sender():
    stub = _Stub(hide=True)
    assert stub._render_message_line(_msg(True)) == "oi"
    assert stub._render_message_line(_msg(False)) == "Ana: oi"


def test_my_reply_row_starts_with_the_replying_clause():
    stub = _Stub(hide=True, quoted="Ana")
    assert stub._render_message_line(_msg(True)) == "respondendo a Ana: oi"
    assert stub._render_message_line(_msg(False)) == "Ana, respondendo a Ana: oi"
