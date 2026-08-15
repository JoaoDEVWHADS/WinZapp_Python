"""Tests for contactMessage/contactsArrayMessage preview text, shared by
format_notification_body() (core/notification_manager.py), MainWindow's own
message-preview builder, and ConversationsPanel._get_message_content().

Reported live: a contact card forwarded without a displayName (only a raw
vCard blob) showed an empty or garbled preview instead of falling back to
parsing the vCard's FN: line; contactsArrayMessage (multiple contacts shared
at once) fell through to the default "unsupported" preview entirely.
"""

from core.notification_manager import format_notification_body


class _FakeI18n:
    _STRINGS = {
        "decimal_separator": ".",
        "contact_message": "Contact: {name}",
        "contacts_count": "{count} contacts",
        "unknown_contact": "Unnamed contact",
        "notif_unsupported": "[unsupported]",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


def _msg(message_type, inner):
    return {"messageType": message_type, "message": {message_type: inner}}


class TestContactMessagePreview:
    def test_uses_display_name_when_present(self):
        msg = _msg("contactMessage", {"displayName": "Alice", "vcard": ""})

        assert format_notification_body(msg, None, _FakeI18n()) == "Contact: Alice"

    def test_falls_back_to_vcard_fn_when_display_name_missing(self):
        vcard = "BEGIN:VCARD\nVERSION:3.0\nFN:Bob Builder\nEND:VCARD"
        msg = _msg("contactMessage", {"displayName": "", "vcard": vcard})

        assert format_notification_body(msg, None, _FakeI18n()) == "Contact: Bob Builder"

    def test_falls_back_to_vcard_fn_when_display_name_is_itself_a_vcard_blob(self):
        vcard = "BEGIN:VCARD\nVERSION:3.0\nFN:Carol\nEND:VCARD"
        msg = _msg("contactMessage", {"displayName": vcard, "vcard": ""})

        assert format_notification_body(msg, None, _FakeI18n()) == "Contact: Carol"

    def test_unknown_when_neither_display_name_nor_vcard_fn_available(self):
        msg = _msg("contactMessage", {"displayName": "", "vcard": ""})

        assert format_notification_body(msg, None, _FakeI18n()) == "Contact: Unnamed contact"


class TestContactsArrayMessagePreview:
    def test_shows_the_contact_count(self):
        msg = _msg("contactsArrayMessage", {"contacts": [{"displayName": "A"}, {"displayName": "B"}]})

        assert format_notification_body(msg, None, _FakeI18n()) == "2 contacts"

    def test_empty_contacts_list_shows_zero(self):
        msg = _msg("contactsArrayMessage", {"contacts": []})

        assert format_notification_body(msg, None, _FakeI18n()) == "0 contacts"
