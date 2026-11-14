"""A view-once message is announced as one, instead of vanishing (#47).

WhatsApp never delivers a view-once voice message, photo or video to a linked
device. WhatsApp Web holds a stand-in instead, inspected over CDP on a live
install when one arrived in a group:

    type: "ciphertext", subtype: "view_once_unavailable_fanout",
    no body, no media fields, typeOnInit: "ciphertext"

WinZapp took it for an ordinary undecrypted placeholder: the live funnel
dropped it while waiting for a decrypted copy that never comes (no badge, no
sound, no toast), and a sync stored it as "waiting for this message".
"""

import pytest

from core.notification_manager import format_notification_body
from core.view_once import VIEW_ONCE_UNAVAILABLE_TYPE, is_view_once_unavailable
from core.websocket_client import WebSocketClient
from main import MainWindow, is_countable_message
from main_window.message_events import MessageEventsMixin
from ui.conversations import ConversationsPanel

GROUP = "120363000000000001@g.us"


class _Normalizer:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _raw(**overrides):
    """WPPConnect's payload for the stand-in, fields as measured."""
    raw = {
        "id": f"false_{GROUP}_3A00000000EB5BCF7D0D_5511900000000@lid",
        "from": GROUP, "to": "5511911111111@c.us",
        "author": "5511900000000@lid", "fromMe": False,
        "timestamp": 1790723334, "t": 1790723334,
        "type": "ciphertext", "subtype": "view_once_unavailable_fanout",
        "notifyName": "Gustavo T",
    }
    raw.update(overrides)
    return raw


class _I18n:
    def t(self, key):
        return f"[{key}]"


class TestRecognisingIt:
    def test_the_measured_stand_in(self):
        assert is_view_once_unavailable(_raw()) is True

    def test_an_ordinary_undecrypted_message_is_not_it(self):
        """That one is still waiting for its decrypted copy."""
        assert is_view_once_unavailable(_raw(subtype=None)) is False
        assert is_view_once_unavailable(_raw(subtype="")) is False

    def test_a_real_message_carrying_a_subtype_is_not_it(self):
        assert is_view_once_unavailable(_raw(type="ptt")) is False

    @pytest.mark.parametrize("value", [None, "text", 3, []])
    def test_not_a_payload(self, value):
        assert is_view_once_unavailable(value) is False


class TestTheNormalizer:
    def test_it_becomes_its_own_type(self):
        msg = _Normalizer()._normalize_wpp_message(_raw())

        assert msg["messageType"] == VIEW_ONCE_UNAVAILABLE_TYPE
        assert msg["message"] == {VIEW_ONCE_UNAVAILABLE_TYPE: {}}
        assert msg["key"]["id"] == "3A00000000EB5BCF7D0D"
        assert msg["key"]["fromMe"] is False

    def test_a_plain_ciphertext_is_left_as_it_was(self):
        msg = _Normalizer()._normalize_wpp_message(_raw(subtype=None))

        assert msg["messageType"] == "ciphertext"


class TestItIsAMessage:
    """What the live funnel and the badge decide from."""

    def _view_once(self):
        return _Normalizer()._normalize_wpp_message(_raw())

    def test_the_live_funnel_does_not_drop_it_as_a_placeholder(self):
        assert MessageEventsMixin._is_undecrypted_placeholder(self._view_once()) is False
        assert MessageEventsMixin._is_undecrypted_placeholder(
            _Normalizer()._normalize_wpp_message(_raw(subtype=None))) is True

    def test_it_counts_and_can_be_the_chat_preview(self):
        """Badge, sort order and notification all hang on these two."""
        assert is_countable_message(self._view_once()) is True
        assert MainWindow._counts_as_last_message(self._view_once()) is True

    def test_the_notification_says_what_it_is(self):
        assert format_notification_body(self._view_once(), None, _I18n()) == "[view_once_message]"


class _Panel:
    _get_message_content = ConversationsPanel._get_message_content
    _is_displayable_message = ConversationsPanel._is_displayable_message

    def __init__(self):
        self.main_window = type("MW", (), {"i18n": _I18n(), "app_name": "WinZapp"})()
        self._download_progress = {}


class TestWhereItIsRead:
    def test_the_conversation_row(self):
        msg = _Normalizer()._normalize_wpp_message(_raw())
        panel = _Panel()

        assert panel._is_displayable_message(msg) is True
        assert panel._get_message_content(msg) == "[view_once_message]"

    def test_the_chat_list_preview(self):
        class _MWStub:
            _counts_as_last_message = classmethod(MainWindow._counts_as_last_message.__func__)
            _last_msg_preview = MainWindow._last_msg_preview
            _PREVIEW_MESSAGE_TYPES = MainWindow._PREVIEW_MESSAGE_TYPES

            def __init__(self):
                self.i18n = _I18n()
                self.settings = {"user_interface": {"show_delivery_status_in_chat_list": False}}
                self.conversations_panel = _Panel()

            def self_reference_label(self):
                return "Eu"

        msg = _Normalizer()._normalize_wpp_message(
            _raw(id="false_5511900000000@c.us_3A00000000EB5BCF7D0D",
                 **{"from": "5511900000000@c.us", "author": None}))
        chat = {"remoteJid": "5511900000000@s.whatsapp.net",
                "messages": {"messages": {"records": [msg]}}}

        assert "[view_once_message]" in _MWStub()._last_msg_preview(chat)

    def test_a_reaction_to_it_names_it_in_the_preview(self):
        """Not "unsupported message": the reaction preview names what was
        reacted to, and a view once message is a message WinZapp knows."""
        class _MWStub:
            _counts_as_last_message = classmethod(MainWindow._counts_as_last_message.__func__)
            _last_msg_preview = MainWindow._last_msg_preview
            _PREVIEW_MESSAGE_TYPES = MainWindow._PREVIEW_MESSAGE_TYPES

            def __init__(self):
                self.i18n = _I18n()
                self.settings = {"user_interface": {"show_delivery_status_in_chat_list": False}}
                self.conversations_panel = _Panel()

            def self_reference_label(self):
                return "Eu"

        msg = _Normalizer()._normalize_wpp_message(
            _raw(id="false_5511900000000@c.us_3A00000000EB5BCF7D0D",
                 **{"from": "5511900000000@c.us", "author": None}))
        chat = {"remoteJid": "5511900000000@s.whatsapp.net",
                "messages": {"messages": {"records": [msg]}},
                "_last_reaction": {"emoji": "x", "from_me": True,
                                   "target_id": msg["key"]["id"],
                                   "timestamp": msg["messageTimestamp"] + 60}}

        preview = _MWStub()._last_msg_preview(chat)

        assert "[view_once_message]" in preview
        assert "notif_unsupported" not in preview
