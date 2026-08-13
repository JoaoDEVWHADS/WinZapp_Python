"""Tests for ConversationsPanel._is_message_forwarded() — used by
_render_message_line() to append a "Forwarded" label (comma-separated,
alongside edited/read/delivered) to any message carrying WhatsApp's own
contextInfo.isForwarded flag, whether it was forwarded by this app or by
anyone else.

Deliberately a separate helper from _get_context_info(): that one only ever
returns contextInfo when it also carries a quote, and a forwarded message is
very often neither a reply nor a mention.
"""

from ui.conversations import ConversationsPanel

_is_message_forwarded = ConversationsPanel._is_message_forwarded


class _Stub:
    _is_message_forwarded = ConversationsPanel._is_message_forwarded


class TestIsMessageForwarded:
    def test_plain_message_is_not_forwarded(self):
        stub = _Stub()
        msg = {"messageType": "conversation", "message": {"conversation": "hi"}}
        assert stub._is_message_forwarded(msg) is False

    def test_top_level_contextInfo_isForwarded_true(self):
        stub = _Stub()
        msg = {"contextInfo": {"isForwarded": True}, "message": {}}
        assert stub._is_message_forwarded(msg) is True

    def test_top_level_contextInfo_isForwarded_false(self):
        stub = _Stub()
        msg = {"contextInfo": {"isForwarded": False}, "message": {}}
        assert stub._is_message_forwarded(msg) is False

    def test_forwarded_flag_inside_extended_text_message(self):
        stub = _Stub()
        msg = {
            "message": {
                "extendedTextMessage": {
                    "text": "hi",
                    "contextInfo": {"isForwarded": True},
                }
            }
        }
        assert stub._is_message_forwarded(msg) is True

    def test_forwarded_flag_inside_image_message(self):
        stub = _Stub()
        msg = {
            "message": {
                "imageMessage": {"contextInfo": {"isForwarded": True}}
            }
        }
        assert stub._is_message_forwarded(msg) is True

    def test_a_reply_that_is_not_forwarded_is_not_flagged(self):
        stub = _Stub()
        msg = {
            "message": {
                "extendedTextMessage": {
                    "text": "hi",
                    "contextInfo": {"stanzaId": "ABC", "quotedMessage": {}},
                }
            }
        }
        assert stub._is_message_forwarded(msg) is False

    def test_non_dict_message_is_not_forwarded(self):
        stub = _Stub()
        assert stub._is_message_forwarded("not a dict") is False

    def test_forwarded_message_with_no_message_key_is_not_forwarded(self):
        stub = _Stub()
        msg = {"key": {"id": "abc"}}
        assert stub._is_message_forwarded(msg) is False
