"""Tests for MainWindow._is_group_send_restricted().

Regression coverage: opening a WhatsApp "announcement" group (only admins
can send messages) let a non-admin member type and attempt to send a
message that WhatsApp itself would silently reject — there was no local
signal at all that the group was even restricted.

This function is deliberately fail-open: whenever the local group metadata
doesn't give a clear answer (no announce flag, no participants list, the
current user not found among participants), it must return False (message
field stays writable) rather than risk locking out a user who can actually
post — see the function's own docstring for the reasoning.
"""

import pytest

from main import MainWindow


class _Stub:
    def __init__(self, my_jid="5511999999999@s.whatsapp.net", my_lid=""):
        self.my_jid = my_jid
        self.my_lid = my_lid

    _is_group_send_restricted = MainWindow._is_group_send_restricted
    _phone_digits_equivalent  = staticmethod(MainWindow._phone_digits_equivalent)


def _group(announce=True, participants=None, jid="123456-group@g.us"):
    return {
        "remoteJid": jid,
        "groupMetadata": {
            "announce": announce,
            "participants": participants or [],
        },
    }


class TestNotAGroup:
    def test_a_private_chat_is_never_restricted(self):
        mw = _Stub()
        chat = {"remoteJid": "5511988888888@s.whatsapp.net"}
        assert mw._is_group_send_restricted(chat) is False


class TestAnnounceFlag:
    def test_announce_off_is_never_restricted(self):
        mw = _Stub()
        chat = _group(announce=False, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": None},
        ])
        assert mw._is_group_send_restricted(chat) is False

    def test_missing_announce_flag_is_not_restricted(self):
        mw = _Stub()
        chat = {"remoteJid": "123456-group@g.us", "groupMetadata": {"participants": []}}
        assert mw._is_group_send_restricted(chat) is False


class TestFailsOpenWithoutParticipantData:
    def test_announce_on_but_no_participants_list_fails_open(self):
        mw = _Stub()
        chat = _group(announce=True, participants=[])
        assert mw._is_group_send_restricted(chat) is False

    def test_current_user_not_found_in_participants_fails_open(self):
        mw = _Stub()
        chat = _group(announce=True, participants=[
            {"id": "5511911111111@s.whatsapp.net", "admin": "admin"},
        ])
        assert mw._is_group_send_restricted(chat) is False


class TestAdminStatus:
    def test_non_admin_member_is_restricted(self):
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511911111111@s.whatsapp.net", "admin": "superadmin"},
            {"id": "5511999999999@s.whatsapp.net", "admin": None},
        ])
        assert mw._is_group_send_restricted(chat) is True

    def test_admin_member_is_not_restricted(self):
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": "admin"},
        ])
        assert mw._is_group_send_restricted(chat) is False

    def test_superadmin_member_is_not_restricted(self):
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": "superadmin"},
        ])
        assert mw._is_group_send_restricted(chat) is False

    def test_matches_via_lid_when_phone_jid_not_the_participant_id(self):
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net", my_lid="1234567890@lid")
        chat = _group(announce=True, participants=[
            {"id": "1234567890@lid", "admin": None},
        ])
        assert mw._is_group_send_restricted(chat) is True

    def test_isadmin_boolean_field_is_also_recognized(self):
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511999999999@s.whatsapp.net", "isAdmin": True},
        ])
        assert mw._is_group_send_restricted(chat) is False
