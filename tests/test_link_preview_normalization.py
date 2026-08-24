"""Tests for WebSocketClient._normalize_wpp_message()'s handling of WhatsApp's
own OG link-preview metadata (title/description/canonicalUrl).

Link previews stopped rendering after the move from Evolution API to
WPPConnect: WPPConnect's message model flattens that metadata straight onto
the raw message object (same field names sender.layer.js's own
sendLinkPreview() writes on the way out — see that file), and most
link-preview text still arrives with type "chat" like any other plain text
message, not "extendedText". _normalize_wpp_message() used to only ever pull
`body`/`text` for a "chat" message, silently dropping the preview fields —
ConversationsPanel._get_message_content() never even had anywhere to read
them from.

WebSocketClient needs a live Socket.IO client normally, but
_normalize_wpp_message()/_clean_jid() touch no I/O — exercised as plain
functions against a small stub, same approach as
tests/test_normalize_forwarded_message.py.
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
        "body": "check this out https://example.com",
    }
    msg.update(overrides)
    return msg


class TestLinkPreviewPromotion:
    def test_chat_message_with_preview_is_promoted_to_extended_text(self):
        stub = _Stub()
        msg = _base_msg(
            title="Example Domain",
            description="Example site used for illustration",
            canonicalUrl="https://example.com",
        )

        result = stub._normalize_wpp_message(msg)

        assert result["messageType"] == "extendedTextMessage"
        ext = result["message"]["extendedTextMessage"]
        assert ext["text"] == "check this out https://example.com"
        assert ext["title"] == "Example Domain"
        assert ext["description"] == "Example site used for illustration"
        assert ext["canonicalUrl"] == "https://example.com"

    def test_plain_chat_message_without_preview_is_untouched(self):
        stub = _Stub()
        msg = _base_msg(body="just some text, no link")

        result = stub._normalize_wpp_message(msg)

        assert result["messageType"] == "conversation"
        assert result["message"]["conversation"] == "just some text, no link"
        assert "extendedTextMessage" not in result["message"]

    def test_falls_back_to_matched_text_when_canonical_url_missing(self):
        stub = _Stub()
        msg = _base_msg(title="Example Domain", description="desc", matchedText="https://example.com")

        result = stub._normalize_wpp_message(msg)

        assert result["message"]["extendedTextMessage"]["canonicalUrl"] == "https://example.com"

    def test_title_only_is_enough_to_promote(self):
        stub = _Stub()
        msg = _base_msg(title="Example Domain", description="")

        result = stub._normalize_wpp_message(msg)

        assert result["messageType"] == "extendedTextMessage"
        assert result["message"]["extendedTextMessage"]["title"] == "Example Domain"

    def test_extended_text_type_also_carries_the_preview_fields(self):
        stub = _Stub()
        msg = _base_msg(
            type="extendedText",
            title="Example Domain",
            description="desc",
            canonicalUrl="https://example.com",
        )

        result = stub._normalize_wpp_message(msg)

        ext = result["message"]["extendedTextMessage"]
        assert ext["title"] == "Example Domain"
        assert ext["description"] == "desc"
        assert ext["canonicalUrl"] == "https://example.com"

    def test_preview_and_forward_flag_coexist(self):
        """The preview promotion must not clobber the existing
        quote/mention/forward contextInfo-promotion path (see
        test_normalize_forwarded_message.py) — both need to land on the same
        extendedTextMessage dict."""
        stub = _Stub()
        msg = _base_msg(
            title="Example Domain",
            description="desc",
            canonicalUrl="https://example.com",
            isForwarded=True,
        )

        result = stub._normalize_wpp_message(msg)

        ext = result["message"]["extendedTextMessage"]
        assert ext["title"] == "Example Domain"
        assert ext["contextInfo"]["isForwarded"] is True
