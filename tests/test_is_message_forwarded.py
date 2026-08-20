"""Tests for core.utils.is_message_forwarded() — used by
ConversationsPanel._render_message_line() (via its own thin
_is_message_forwarded() wrapper) to append a "Forwarded" label (comma-
separated, alongside edited/read/delivered) to any message carrying
WhatsApp's own contextInfo.isForwarded flag, whether it was forwarded by
this app or by anyone else — and, since a live bug (see
test_forward_does_not_corrupt_my_lid.py), also by main.py's
on_new_message() to keep a forwarded copy's residual provenance fields from
being mistaken for identifying who actually sent that copy.

Deliberately a separate helper from _get_context_info(): that one only ever
returns contextInfo when it also carries a quote, and a forwarded message is
very often neither a reply nor a mention.
"""

from core.utils import is_message_forwarded
from ui.conversations import ConversationsPanel

_is_message_forwarded = ConversationsPanel._is_message_forwarded


class TestModuleLevelFunctionDirectly:
    """The panel method is now a thin wrapper — pin the underlying function
    itself works the same, independent of ConversationsPanel."""

    def test_forwarded_flag_is_detected(self):
        assert is_message_forwarded({"contextInfo": {"isForwarded": True}, "message": {}}) is True

    def test_plain_message_is_not_forwarded(self):
        assert is_message_forwarded({"messageType": "conversation", "message": {"conversation": "hi"}}) is False

    def test_non_dict_message_is_not_forwarded(self):
        assert is_message_forwarded("not a dict") is False
        assert is_message_forwarded(None) is False


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
