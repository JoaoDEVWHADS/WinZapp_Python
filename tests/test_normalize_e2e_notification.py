"""Tests for WebSocketClient._normalize_wpp_message()'s generic text-fallback
branch not mistaking a bare JID for real chat text.

Reported live: after a contact reinstalled WhatsApp (security code/E2E
identity changed), a raw @lid string leaked into the conversation as if it
were a message the contact had sent — e.g. "150418378248211@lid" shown with
a timestamp and no sender name. WPPConnect's raw payload for this kind of
internal notification-only event has no "type" this function maps to
anything (message_content stays {}), but its "body"/"text" field holds the
JID of whoever triggered the notification — and the generic "type is
unsupported/unmapped but has body text -> treat it as a normal chat message"
fallback below picked that up and rendered it as text. Once message_content
stays empty here, the message falls through to the already-existing
unmapped-type handling (excluded from display and from unread/notifications
— see is_countable_message()'s docstring in main.py and
ConversationsPanel._is_displayable_message()'s allowlist).

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
        "type": "e2e_notification",
    }
    msg.update(overrides)
    return msg


class TestBareJidBodyIsNotTreatedAsChatText:
    def test_lid_body_does_not_become_a_conversation_message(self):
        msg = _base_msg(body="150418378248211@lid")

        result = _Stub()._normalize_wpp_message(msg)

        assert result["messageType"] != "conversation"
        assert result["message"] == {}

    def test_phone_jid_body_is_also_excluded(self):
        msg = _base_msg(body="5511999999999@s.whatsapp.net")

        result = _Stub()._normalize_wpp_message(msg)

        assert result["messageType"] != "conversation"
        assert result["message"] == {}

    def test_text_field_variant_is_also_excluded(self):
        msg = _base_msg(text="51226662170731@lid")

        result = _Stub()._normalize_wpp_message(msg)

        assert result["messageType"] != "conversation"
        assert result["message"] == {}

    def test_real_text_content_is_unaffected(self):
        """Sanity check the guard is JID-specific — an unmapped type with
        genuine text still falls back to a normal chat message."""
        msg = _base_msg(type="some_future_wppconnect_type", body="Oi, tudo bem?")

        result = _Stub()._normalize_wpp_message(msg)

        assert result["messageType"] == "conversation"
        assert result["message"] == {"conversation": "Oi, tudo bem?"}

    def test_group_jid_is_also_recognized_as_a_bare_jid(self):
        msg = _base_msg(body="120363409931936700@g.us")

        result = _Stub()._normalize_wpp_message(msg)

        assert result["message"] == {}
