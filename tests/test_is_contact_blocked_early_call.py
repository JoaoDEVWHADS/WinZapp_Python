"""Tests for MainWindow.is_contact_blocked() being called before
prepare_sync() has restored self._blocked_contacts.

Reported live (issue #19): add_chats_to_ui() -> _build_item_text() ->
is_contact_blocked() ran during a re-pairing flow (stale token forcing a
fresh QR/phone-number login) before prepare_sync() reached the point where
it sets self._blocked_contacts from the database, crashing with
AttributeError and leaving the chat list stuck empty.
"""

from main import MainWindow


class _Stub:
    is_contact_blocked = MainWindow.is_contact_blocked
    _bare_phone_digits = staticmethod(MainWindow._bare_phone_digits)


class TestIsContactBlockedBeforeInit:
    def test_returns_false_instead_of_crashing_when_attribute_is_missing(self):
        stub = _Stub()
        assert not hasattr(stub, "_blocked_contacts")

        assert stub.is_contact_blocked("5511999999999@s.whatsapp.net") is False

    def test_still_detects_a_blocked_contact_once_initialized(self):
        stub = _Stub()
        stub._blocked_contacts = {"5511999999999"}

        assert stub.is_contact_blocked("5511999999999@s.whatsapp.net") is True
        assert stub.is_contact_blocked("5511888888888@s.whatsapp.net") is False

    def test_brazilian_8_9_digit_tolerance_still_works(self):
        stub = _Stub()
        # 9-digit form stored, 8-digit form looked up.
        stub._blocked_contacts = {"5511999999999"}
        assert stub.is_contact_blocked("551199999999@s.whatsapp.net") is True
