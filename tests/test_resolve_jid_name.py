"""Tests for MainWindow._resolve_jid_name — the participant-name resolver
behind the typing/recording indicator (chat-list label and the spoken
"<name> está digitando..." announcement).

Reported live: after deleting a session and re-pairing, every group's typing
indicator showed the GROUP's own name instead of the participant who was
actually typing (e.g. "WinZapp | desenvolvedores e testers está
digitando..."). Root cause: some presence.update payloads key the group-wide
event by the group's own @g.us id rather than a specific participant id.
_resolve_jid_name(group_jid) used to fall through to self.chats.get(group_jid)
— which legitimately holds the group's own chat entry — and returned the
group's name as if it were a person's. A participant JID is never a group
JID, so that candidate must be skipped rather than resolved via self.chats.
"""

from main import MainWindow


class _I18n:
    TRANSLATIONS = {
        "unnamed_participant": "unnamed participant",
    }

    def t(self, key):
        return self.TRANSLATIONS.get(key, key)


class _Stub:
    _resolve_jid_name = MainWindow._resolve_jid_name
    _get_contact_tolerant = MainWindow._get_contact_tolerant

    def __init__(self):
        self.i18n = _I18n()
        self.contacts = {}
        self.chats = {}
        self._phone_to_lid = {}
        self._lid_to_phone = {}
        self._presence_pushname_map = {}


class TestGroupJidNeverResolvesToTheGroupsOwnName:
    def test_a_presence_event_keyed_by_the_group_itself_does_not_return_the_group_name(self):
        stub = _Stub()
        group_jid = "12345-6789@g.us"
        stub.chats[group_jid] = {"remoteJid": group_jid, "name": "WinZapp | desenvolvedores e testers"}

        name = stub._resolve_jid_name(group_jid)

        assert name != "WinZapp | desenvolvedores e testers"
        assert name == "unnamed participant"

    def test_a_real_participant_in_the_same_group_still_resolves_normally(self):
        stub = _Stub()
        group_jid = "12345-6789@g.us"
        participant_jid = "5511999999999@s.whatsapp.net"
        stub.chats[group_jid] = {"remoteJid": group_jid, "name": "WinZapp | desenvolvedores e testers"}
        stub.contacts[participant_jid] = {"name": "Fulano"}

        name = stub._resolve_jid_name(participant_jid)

        assert name == "Fulano"

    def test_an_at_lid_participant_still_falls_back_to_the_placeholder(self):
        """Same reasoning, different pre-existing case: no @lid->phone
        mapping yet, so raw digits would be meaningless read aloud."""
        stub = _Stub()

        name = stub._resolve_jid_name("987654321@lid")

        assert name == "unnamed participant"
