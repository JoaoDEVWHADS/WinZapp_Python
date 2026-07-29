"""Tests for notification content-building — format_notification_body() and
format_notification_title()'s group-name resolution.

Regression coverage for two bugs found in the same broader audit that fixed
is_countable_message() (tests/test_countable_message.py) and
_is_bad_contact_name() (tests/test_bad_contact_name.py):

1. format_notification_body() had no case for several message types
   is_countable_message() already treats as real, notification-worthy
   content (polls, buttons, lists, templates, interactive messages/replies,
   liveLocationMessage) — they all fell through to "Mensagem incompatível"
   even though ConversationsPanel._get_message_content() already knew how
   to describe every one of them in the open conversation.

2. format_notification_title()'s group branch called
   MainWindow._resolve_contact_name(chat), whose own docstring says
   "Groups are skipped" (always returns None for a group) — dead code —
   and never called _group_name_from_chat_dict(), which the chat list
   itself already relies on for WPPConnect's raw chat shape (a group's
   real name nested under groupMetadata.subject, not a flat "name" key).
   A notification could say "Grupo sem nome" for a group the chat list
   displayed correctly, in the exact stale-metadata window right after a
   fresh pairing.
"""

import pytest

from core.notification_manager import format_notification_body, format_notification_title


class _FakeI18n:
    """Returns a recognizable template per key so assertions can check
    exactly which branch fired, without depending on real translations."""

    _STRINGS = {
        "notif_unsupported": "[unsupported]",
        "notif_location": "[location]",
        "notif_poll": "[poll:{name}]",
        "notif_poll_no_name": "[poll-no-name]",
        "notif_template": "[template]",
        "interactive_message": "[interactive]",
        "interactive_reply": "[interactive-reply]",
        "list_reply": "[list-reply]",
        "options": "options",
        "unknown_group": "[unknown-group]",
        "unnamed_participant": "[unnamed-participant]",
        "notif_in_group": "{participant} em {group}",
        "notif_replied_to_you": "",
        "notif_mentioned_you": "",
        "notif_mentioned_all": "",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


def _msg(message_type, message=None, **extra):
    m = {"messageType": message_type, "message": message or {}, "key": {}}
    m.update(extra)
    return m


class TestFormatNotificationBodyCoversRealContentTypes:
    """Every type is_countable_message() treats as real content must
    produce SOMETHING other than the generic "unsupported" fallback."""

    def test_poll_with_a_name(self):
        msg = _msg("pollCreationMessage", {"pollCreationMessage": {"name": "Pizza ou sushi?"}})
        body = format_notification_body(msg, None, _FakeI18n())
        assert body == "[poll:Pizza ou sushi?]"

    def test_poll_without_a_name(self):
        msg = _msg("pollCreationMessage", {"pollCreationMessage": {}})
        body = format_notification_body(msg, None, _FakeI18n())
        assert body == "[poll-no-name]"

    @pytest.mark.parametrize("poll_type", [
        "pollCreationMessageV2", "pollCreationMessageV3",
    ])
    def test_poll_variants(self, poll_type):
        msg = _msg(poll_type, {poll_type: {"name": "Enquete"}})
        body = format_notification_body(msg, None, _FakeI18n())
        assert body == "[poll:Enquete]"

    def test_live_location_reuses_location_text(self):
        msg = _msg("liveLocationMessage")
        assert format_notification_body(msg, None, _FakeI18n()) == "[location]"

    def test_buttons_message_shows_its_content_text(self):
        msg = _msg("buttonsMessage", {"buttonsMessage": {"contentText": "Escolha uma opção"}})
        assert format_notification_body(msg, None, _FakeI18n()) == "Escolha uma opção"

    def test_buttons_message_with_no_text_falls_back(self):
        msg = _msg("buttonsMessage", {"buttonsMessage": {}})
        assert format_notification_body(msg, None, _FakeI18n()) == "[interactive]"

    def test_list_message_shows_its_title(self):
        msg = _msg("listMessage", {"listMessage": {"title": "Cardápio"}})
        assert format_notification_body(msg, None, _FakeI18n()) == "Cardápio"

    def test_template_message(self):
        msg = _msg("templateMessage")
        assert format_notification_body(msg, None, _FakeI18n()) == "[template]"

    def test_interactive_message_shows_body_text(self):
        msg = _msg("interactiveMessage", {"interactiveMessage": {"body": {"text": "Olá!"}}})
        assert format_notification_body(msg, None, _FakeI18n()) == "Olá!"

    def test_buttons_response_message(self):
        msg = _msg("buttonsResponseMessage", {"buttonsResponseMessage": {"selectedDisplayText": "Sim"}})
        assert format_notification_body(msg, None, _FakeI18n()) == "Sim"

    def test_buttons_response_with_no_text_falls_back(self):
        msg = _msg("buttonsResponseMessage", {"buttonsResponseMessage": {}})
        assert format_notification_body(msg, None, _FakeI18n()) == "[interactive-reply]"

    def test_list_response_message(self):
        msg = _msg("listResponseMessage", {"listResponseMessage": {"title": "Opção 2"}})
        assert format_notification_body(msg, None, _FakeI18n()) == "Opção 2"

    def test_list_response_falls_back_to_row_id_then_generic(self):
        msg = _msg("listResponseMessage", {"listResponseMessage": {
            "singleSelectReply": {"selectedRowId": "row-2"}
        }})
        assert format_notification_body(msg, None, _FakeI18n()) == "row-2"

        empty = _msg("listResponseMessage", {"listResponseMessage": {}})
        assert format_notification_body(empty, None, _FakeI18n()) == "[list-reply]"


class TestFormatNotificationTitleGroupName:
    def test_uses_chat_name_when_present(self):
        class _MW:
            chats = {"g@g.us": {"remoteJid": "g@g.us", "name": "Família"}}

            @staticmethod
            def _group_name_from_chat_dict(chat):
                return ""  # should not even be needed here

        msg = _msg("conversation", key={"remoteJid": "g@g.us"})
        title = format_notification_title(msg, _MW(), _FakeI18n())
        assert "Família" in title

    def test_falls_back_to_group_name_from_chat_dict_when_name_is_missing(self):
        """The actual bug: WPPConnect's raw chat shape nests the real name
        under groupMetadata.subject, not a flat "name" key."""
        class _MW:
            chats = {"g@g.us": {"remoteJid": "g@g.us", "groupMetadata": {"subject": "Turma 2026"}}}

            @staticmethod
            def _group_name_from_chat_dict(chat):
                return (chat.get("groupMetadata") or {}).get("subject", "")

        msg = _msg("conversation", key={"remoteJid": "g@g.us"})
        title = format_notification_title(msg, _MW(), _FakeI18n())
        assert "Turma 2026" in title

    def test_unknown_group_only_when_nothing_resolves(self):
        class _MW:
            chats = {}

            @staticmethod
            def _group_name_from_chat_dict(chat):
                return ""

        msg = _msg("conversation", key={"remoteJid": "g@g.us"})
        title = format_notification_title(msg, _MW(), _FakeI18n())
        assert "[unknown-group]" in title
