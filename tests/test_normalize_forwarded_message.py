"""Tests for WebSocketClient._normalize_wpp_message() threading through
WhatsApp's own contextInfo.isForwarded flag.

isForwarded is a real WhatsApp protocol field (contextInfo.isForwarded in
the raw proto; WPPConnect's own Message model also exposes it as a
top-level convenience boolean — see @wppconnect-team/wppconnect's
message.d.ts) present on ANY forwarded message, from anyone — not just ones
this app itself forwarded. _normalize_wpp_message() used to only ever build
a contextInfo dict when the message had a quote or a mention, silently
dropping isForwarded for a forwarded message that was neither.

WebSocketClient needs a live Socket.IO client normally, but
_normalize_wpp_message()/_clean_jid() touch no I/O — exercised as plain
functions against a small stub, same approach as
tests/test_normalize_document_forward.py.
"""

from core.websocket_client import WebSocketClient


class _Stub:
    _normalize_wpp_message = WebSocketClient._normalize_wpp_message
    _clean_jid = WebSocketClient._clean_jid


def _base_msg(**overrides):
    msg = {
        "id": "false_5511999999999@c.us_ABC123",
        "from": "5511999999999@c.us",
        "to": "5511999999999@c.us",
        "fromMe": False,
        "timestamp": 1700000000,
        "type": "chat",
        "body": "hello",
    }
    msg.update(overrides)
    return msg


class TestForwardedFlagIsPreserved:
    def test_forwarded_plain_text_message_carries_the_flag(self):
        stub = _Stub()
        msg = _base_msg(isForwarded=True)

        result = stub._normalize_wpp_message(msg)

        # A plain "conversation" message with any contextInfo is promoted to
        # extendedTextMessage — same as the quote/mention paths already do.
        ctx = result["message"]["extendedTextMessage"]["contextInfo"]
        assert ctx["isForwarded"] is True

    def test_non_forwarded_message_gets_no_context_info_at_all(self):
        """No quote, no mention, no forward — contextInfo must not appear,
        same as before this change (avoids bloating every plain message)."""
        stub = _Stub()
        msg = _base_msg(isForwarded=False)

        result = stub._normalize_wpp_message(msg)

        assert result["messageType"] == "conversation"
        assert "contextInfo" not in result["message"].get("conversation", {})
        assert "extendedTextMessage" not in result["message"]

    def test_forwarded_image_message_carries_the_flag_in_its_sub_key(self):
        stub = _Stub()
        msg = _base_msg(type="image", isForwarded=True, caption="pic")

        result = stub._normalize_wpp_message(msg)

        assert result["message"]["imageMessage"]["contextInfo"]["isForwarded"] is True

    def test_falls_back_to_contextInfo_isForwarded_when_top_level_is_missing(self):
        """Some payload shapes only carry it nested under contextInfo
        (Baileys/raw-proto convention) rather than as WPPConnect's top-level
        convenience field."""
        stub = _Stub()
        msg = _base_msg(contextInfo={"isForwarded": True})

        result = stub._normalize_wpp_message(msg)

        ctx = result["message"]["extendedTextMessage"]["contextInfo"]
        assert ctx["isForwarded"] is True

    def test_forwarded_and_quoted_message_carries_both(self):
        stub = _Stub()
        msg = _base_msg(
            isForwarded=True,
            quotedStanzaID="true_5511999999999@c.us_XYZ",
            quotedParticipant="5511888888888@c.us",
        )

        result = stub._normalize_wpp_message(msg)

        ctx = result["message"]["extendedTextMessage"]["contextInfo"]
        assert ctx["isForwarded"] is True
        assert ctx["stanzaId"] == "XYZ"
