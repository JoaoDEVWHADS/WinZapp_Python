"""Tests for MainWindow._is_group_send_restricted().

Regression coverage: opening a WhatsApp "announcement" group (only admins
can send messages) let a non-admin member type and attempt to send a
message that WhatsApp itself would silently reject — there was no local
signal at all that the group was even restricted.

This function is deliberately fail-open: whenever neither the local group
metadata nor the persisted verdict gives a clear answer (no announce flag, no
participants list, the current user not found among participants), it must
return False (message field stays writable) rather than risk locking out a
user who can actually post — see the function's own docstring for the
reasoning.

Two later defects in the same area are pinned here as well:

* the announce flag reached Python only through list-chats' groupMetadata and
  was stored nowhere, while the `chats` table has no group-metadata column at
  all — so `self.chats = self.get_chats()` rehydrated every group without it
  and the composer failed open for the whole of startup, permanently while
  offline. The verdict now rides in system_metadata (`group_send_perms`),
  written by _record_group_send_perms() and consulted here.
* the participant match read `admin`/`isAdmin` and never `isSuperAdmin`.
  WhatsApp Web reports a group's own creator as isAdmin=false,
  isSuperAdmin=true, so WinZapp locked the creator out of their own
  announcement group — the fail-*closed* direction. Upstream WPPConnect's
  getGroupInfo ORs all three fields for exactly this reason.
"""

import pytest

from core.utils import group_setting_notif_value
from main import (
    MainWindow,
    group_participant_admin_flag,
    group_send_permission_from_metadata,
)


class _Stub:
    def __init__(self, my_jid="5511999999999@s.whatsapp.net", my_lid="",
                 group_send_perms=None):
        self.my_jid = my_jid
        self.my_lid = my_lid
        # What prepare_sync() restores from system_metadata; empty on a stub
        # that only exercises the live-metadata path.
        self._group_send_perms = group_send_perms or {}

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

    def test_superadmin_boolean_field_alone_is_recognized(self):
        # The group's creator: WhatsApp Web reports isAdmin=false alongside
        # isSuperAdmin=true, and reading isAdmin alone locked them out of
        # their own announcement group.
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511999999999@s.whatsapp.net",
             "isAdmin": False, "isSuperAdmin": True},
        ])
        assert mw._is_group_send_restricted(chat) is False

    def test_superadmin_with_device_suffix_on_the_participant_id(self):
        # WPPConnect's participant ids routinely carry the ":60" companion
        # suffix; it must not defeat the self-match.
        mw = _Stub(my_jid="5511999999999@s.whatsapp.net")
        chat = _group(announce=True, participants=[
            {"id": "5511999999999:60@s.whatsapp.net", "isSuperAdmin": True},
        ])
        assert mw._is_group_send_restricted(chat) is False


class TestPersistedVerdict:
    """The composer's answer before any list-chats snapshot has landed."""

    _JID = "123456-group@g.us"

    def test_persisted_verdict_restricts_a_chat_with_no_group_metadata(self):
        # Exactly what get_chats() rehydrates at startup: a group dict with no
        # groupMetadata whatsoever. Without the persisted verdict this failed
        # open and showed a writable message field to a non-admin.
        mw = _Stub(group_send_perms={
            self._JID: {"announce": True, "am_admin": False, "t": 1}})
        assert mw._is_group_send_restricted({"remoteJid": self._JID}) is True

    def test_persisted_verdict_leaves_an_admin_writable(self):
        mw = _Stub(group_send_perms={
            self._JID: {"announce": True, "am_admin": True, "t": 1}})
        assert mw._is_group_send_restricted({"remoteJid": self._JID}) is False

    def test_no_metadata_and_no_persisted_verdict_still_fails_open(self):
        mw = _Stub()
        assert mw._is_group_send_restricted({"remoteJid": self._JID}) is False

    def test_live_participants_outrank_a_stale_persisted_verdict(self):
        # Promoted since the verdict was stored: this snapshot says admin, so
        # the composer must open back up.
        mw = _Stub(group_send_perms={
            self._JID: {"announce": True, "am_admin": False, "t": 1}})
        chat = _group(announce=True, jid=self._JID, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": "admin"},
        ])
        assert mw._is_group_send_restricted(chat) is False

    def test_live_announce_reuses_the_persisted_admin_answer(self):
        # list-chats is called with ignoreGroupMetadata, so a group can
        # serialise with announce and no participants at all. The admin half
        # of the answer then has to come from the stored verdict, or the
        # restriction is lost the moment participants stop arriving.
        mw = _Stub(group_send_perms={
            self._JID: {"announce": False, "am_admin": False, "t": 1}})
        chat = {"remoteJid": self._JID, "groupMetadata": {"announce": True}}
        assert mw._is_group_send_restricted(chat) is True

    def test_live_announce_off_outranks_a_restricting_persisted_verdict(self):
        mw = _Stub(group_send_perms={
            self._JID: {"announce": True, "am_admin": False, "t": 1}})
        chat = {"remoteJid": self._JID, "groupMetadata": {"announce": False}}
        assert mw._is_group_send_restricted(chat) is False


class TestGroupParticipantAdminFlag:
    """The module-level participant scan, tested without any stub at all."""

    def test_returns_none_when_the_list_cannot_answer(self):
        assert group_participant_admin_flag([], "5511999999999", "", lambda a, b: a == b) is None
        assert group_participant_admin_flag(None, "5511999999999", "", lambda a, b: a == b) is None
        assert group_participant_admin_flag(
            [{"id": "5511911111111@s.whatsapp.net", "admin": "admin"}],
            "5511999999999", "", lambda a, b: a == b,
        ) is None

    def test_serialized_participant_id_shape_is_accepted(self):
        # Some WPPConnect versions serialise the id as {"_serialized": ...}.
        assert group_participant_admin_flag(
            [{"id": {"_serialized": "5511999999999@s.whatsapp.net"}, "isSuperAdmin": True}],
            "5511999999999", "", lambda a, b: a == b,
        ) is True

    def test_plain_member_answers_false(self):
        assert group_participant_admin_flag(
            [{"id": "5511999999999@s.whatsapp.net", "admin": None}],
            "5511999999999", "", lambda a, b: a == b,
        ) is False


class TestVerdictFromMetadata:
    def test_undecidable_when_announce_is_not_stated(self):
        assert group_send_permission_from_metadata(
            {"remoteJid": "g@g.us"}, "5511999999999", "", lambda a, b: a == b) is None

    def test_undecidable_when_announce_is_on_and_admin_status_unknown(self):
        # Never guessed: a guess written into the persisted verdict becomes
        # authoritative on the next launch.
        assert group_send_permission_from_metadata(
            {"remoteJid": "g@g.us", "groupMetadata": {"announce": True}},
            "5511999999999", "", lambda a, b: a == b,
        ) is None

    def test_known_am_admin_fills_the_gap(self):
        assert group_send_permission_from_metadata(
            {"remoteJid": "g@g.us", "groupMetadata": {"announce": True}},
            "5511999999999", "", lambda a, b: a == b, known_am_admin=False,
        ) == {"announce": True, "am_admin": False}

    def test_announce_off_decides_without_participants(self):
        assert group_send_permission_from_metadata(
            {"remoteJid": "g@g.us", "groupMetadata": {"announce": False}},
            "5511999999999", "", lambda a, b: a == b,
        ) == {"announce": False, "am_admin": False}


class _FakeDb:
    def __init__(self):
        self.metadata = {}

    def set_metadata_json(self, key, value):
        self.metadata[key] = value


class _RecorderStub(_Stub):
    """Carries what the recording/notification funnels touch on top of _Stub.

    conversations_panel stays None on purpose: the wx.CallAfter that refreshes
    the open composer needs a running wx.App, and the panel side of that is
    covered by tests/test_composer_permissions.py instead.
    """

    _record_group_send_perms = MainWindow._record_group_send_perms
    _persist_group_send_perms = MainWindow._persist_group_send_perms
    _apply_group_settings_change = MainWindow._apply_group_settings_change
    _GROUP_ANNOUNCE_NOTIF_SUBTYPES = MainWindow._GROUP_ANNOUNCE_NOTIF_SUBTYPES
    _GROUP_RESTRICT_NOTIF_SUBTYPES = MainWindow._GROUP_RESTRICT_NOTIF_SUBTYPES

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.db = _FakeDb()
        self.conversations_panel = None


_JID = "123456-group@g.us"


def _notif_msg(subtype, value=None, body=""):
    return {
        "key": {"remoteJid": _JID, "fromMe": False, "id": "N1"},
        "messageType": "groupNotification",
        "message": {"groupNotification": {"subtype": subtype, "value": value, "body": body}},
        "messageTimestamp": 1700000000,
    }


class TestRecordGroupSendPerms:
    def test_records_a_decidable_verdict(self):
        mw = _RecorderStub()
        chat = _group(announce=True, jid=_JID, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": None},
        ])
        verdict = mw._record_group_send_perms(_JID, chat)
        assert verdict["announce"] is True and verdict["am_admin"] is False
        assert mw._group_send_perms[_JID]["t"] > 0

    def test_an_unchanged_verdict_does_not_rewrite_the_timestamp(self):
        # The periodic list-chats refresh runs every 60s; rewriting here would
        # be one DB write per group per minute for no new information.
        mw = _RecorderStub()
        chat = _group(announce=True, jid=_JID, participants=[
            {"id": "5511999999999@s.whatsapp.net", "admin": None},
        ])
        first = dict(mw._record_group_send_perms(_JID, chat))
        again = mw._record_group_send_perms(_JID, chat)
        assert again["t"] == first["t"]

    def test_an_undecidable_snapshot_records_nothing(self):
        mw = _RecorderStub()
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": True}}
        assert mw._record_group_send_perms(_JID, chat) is None
        assert mw._group_send_perms == {}

    def test_persist_writes_through_the_db_metadata_store(self):
        mw = _RecorderStub(group_send_perms={
            _JID: {"announce": True, "am_admin": False, "t": 5}})
        mw._persist_group_send_perms()
        assert mw.db.metadata["group_send_perms"][_JID]["announce"] is True


class TestLiveSettingsNotification:
    """An announce toggle arriving over the socket, not through list-chats."""

    def test_announce_on_updates_group_metadata_and_the_verdict(self):
        mw = _RecorderStub(group_send_perms={
            _JID: {"announce": False, "am_admin": False, "t": 1}})
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": False}}
        mw._apply_group_settings_change(_JID, chat, _notif_msg("announce", value="on"))
        assert chat["groupMetadata"]["announce"] is True
        assert mw._group_send_perms[_JID]["announce"] is True
        assert mw.db.metadata["group_send_perms"][_JID]["announce"] is True

    def test_announce_off_reopens_the_verdict(self):
        mw = _RecorderStub(group_send_perms={
            _JID: {"announce": True, "am_admin": False, "t": 1}})
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": True}}
        mw._apply_group_settings_change(_JID, chat, _notif_msg("announce", value="off"))
        assert mw._group_send_perms[_JID]["announce"] is False

    def test_a_notification_with_no_stated_value_changes_nothing(self):
        # Guessing "on" here would lock the composer off a payload that never
        # said so — the fail-closed direction.
        mw = _RecorderStub(group_send_perms={
            _JID: {"announce": False, "am_admin": False, "t": 1}})
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": False}}
        mw._apply_group_settings_change(_JID, chat, _notif_msg("announce"))
        assert chat["groupMetadata"]["announce"] is False
        assert mw._group_send_perms[_JID]["announce"] is False

    def test_restrict_subtype_touches_restrict_and_leaves_announce_alone(self):
        # "restrict" is who may edit the group's info, not who may send.
        mw = _RecorderStub()
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": False}}
        mw._apply_group_settings_change(_JID, chat, _notif_msg("locked", value="on"))
        assert chat["groupMetadata"]["restrict"] is True
        assert chat["groupMetadata"]["announce"] is False

    def test_unrelated_subtypes_are_ignored(self):
        mw = _RecorderStub()
        chat = {"remoteJid": _JID, "groupMetadata": {"announce": False}}
        mw._apply_group_settings_change(_JID, chat, _notif_msg("subject", body="Novo nome"))
        assert chat["groupMetadata"] == {"announce": False}
        assert mw._group_send_perms == {}

    def test_a_private_chat_is_never_touched(self):
        mw = _RecorderStub()
        jid = "5511988888888@s.whatsapp.net"
        chat = {"remoteJid": jid}
        mw._apply_group_settings_change(jid, chat, _notif_msg("announce", value="on"))
        assert "groupMetadata" not in chat


class TestGroupSettingNotifValue:
    """The value field of a group-settings notification, as WPPConnect spells
    it across versions. Strictly tri-state, unlike parse_bool_flag(""), which
    answers False for a payload that said nothing at all."""

    @pytest.mark.parametrize("raw", ["on", "announcement", "locked", True, 1, "true"])
    def test_on_shapes(self, raw):
        assert group_setting_notif_value({"value": raw}) is True

    @pytest.mark.parametrize("raw", ["off", "unlocked", False, 0, "false"])
    def test_off_shapes(self, raw):
        assert group_setting_notif_value({"value": raw}) is False

    def test_falls_back_to_the_notification_body(self):
        assert group_setting_notif_value({"body": "on"}) is True

    def test_nothing_stated_is_none(self):
        assert group_setting_notif_value({}) is None
        assert group_setting_notif_value({"body": "   "}) is None
        assert group_setting_notif_value(None) is None
