"""Tests for _get_quoted_sender() not labelling every unmatched sender as "me".

Reported live: replies showed (and screen readers announced) "respondendo a
Eu" for messages that were replying to the other person. The 1:1 branch ended
in a catch-all:

    if my_phone and p_phone == my_phone:      -> me            (right)
    elif p_phone == r_phone:                  -> contact name  (right)
    else:                                     -> me            (wrong)

Anything that matched neither comparison was announced as the user themselves.
And "matched neither" is not exotic: the chat's remoteJid is often the @lid
form while the quoted participant arrives as a phone JID, so the second
comparison fails on a message that is plainly from the other person.

The fix is two-sided — drop the catch-all so the flow reaches the real name
lookup, and bridge @lid to phone on the chat side before comparing, so the
second branch matches when it should.

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so the method under test runs against a stub — same approach as
tests/test_message_bookmarks.py.
"""

import pytest

from ui.conversations import ConversationsPanel


ME = "5511900000001@s.whatsapp.net"
OTHER = "5511900000002@s.whatsapp.net"
OTHER_LID = "111111111111111@lid"
THIRD = "5511900000003@s.whatsapp.net"


class _FakeI18n:
    def t(self, key):
        return key


class _FakeMainWindow:
    def __init__(self, lid_to_phone=None, contact_name=""):
        self.i18n = _FakeI18n()
        self.my_jid = ME
        self._lid_to_phone = dict(lid_to_phone or {})
        self._contact_name = contact_name

    def self_reference_label(self):
        return "Eu"

    def _resolve_contact_name(self, chat):
        return self._contact_name


class _Stub:
    _get_quoted_sender = ConversationsPanel._get_quoted_sender

    def __init__(self, conversation_jid, lid_to_phone=None, contact_name=""):
        self.main_window = _FakeMainWindow(lid_to_phone, contact_name)
        self.conversation = {"remoteJid": conversation_jid}
        self._sorted_messages = []

    def _get_participant_name(self, jid, *args):
        # Distinctive marker: reaching here means the catch-all is gone and the
        # real name lookup got its chance.
        return f"<lookup:{jid}>"


def _ctx(participant):
    return {"participant": participant, "stanzaId": "QUOTED1"}


def _reply(from_me=False):
    return {"key": {"id": "R1", "fromMe": from_me}}


class TestTheReportedBug:
    def test_a_third_party_is_not_announced_as_me(self):
        """Neither me nor the chat's own JID — the old catch-all called this
        "Eu"; it must go to the real lookup instead."""
        panel = _Stub(conversation_jid=OTHER)

        assert panel._get_quoted_sender(_ctx(THIRD), _reply()) == f"<lookup:{THIRD}>"

    def test_phone_participant_in_a_lid_keyed_chat_is_not_me(self):
        """The everyday shape of the bug: the conversation is keyed by @lid,
        the quoted participant arrives as a phone JID. Same person, and with
        the mapping known it resolves to their name — never to "Eu"."""
        panel = _Stub(
            conversation_jid=OTHER_LID,
            lid_to_phone={OTHER_LID: OTHER},
            contact_name="Fulano",
        )

        assert panel._get_quoted_sender(_ctx(OTHER), _reply()) == "Fulano"

    def test_without_the_mapping_it_still_never_says_me(self):
        """Mapping unknown, so the comparison cannot match — the answer is the
        name lookup, not the user's own label."""
        panel = _Stub(conversation_jid=OTHER_LID)

        assert panel._get_quoted_sender(_ctx(OTHER), _reply()) == f"<lookup:{OTHER}>"


class TestWhatMustKeepWorking:
    def test_quoting_my_own_message_still_says_me(self):
        panel = _Stub(conversation_jid=OTHER)

        assert panel._get_quoted_sender(_ctx(ME), _reply()) == "Eu"

    def test_my_own_message_with_a_device_suffix_still_says_me(self):
        panel = _Stub(conversation_jid=OTHER)
        me_dev = ME.replace("@", ":12@")

        assert panel._get_quoted_sender(_ctx(me_dev), _reply()) == "Eu"

    def test_quoting_the_other_party_gives_their_name(self):
        panel = _Stub(conversation_jid=OTHER, contact_name="Fulano")

        assert panel._get_quoted_sender(_ctx(OTHER), _reply()) == "Fulano"

    def test_a_lid_participant_is_bridged_to_the_phone_jid(self):
        panel = _Stub(
            conversation_jid=OTHER,
            lid_to_phone={OTHER_LID: OTHER},
            contact_name="Fulano",
        )

        assert panel._get_quoted_sender(_ctx(OTHER_LID), _reply()) == "Fulano"

    def test_in_a_group_a_third_party_goes_to_the_name_lookup(self):
        """Groups never took the 1:1 branch at all — the catch-all could not
        reach them, and that must stay true."""
        panel = _Stub(conversation_jid="120363000000000001@g.us")

        assert panel._get_quoted_sender(_ctx(THIRD), _reply()) == f"<lookup:{THIRD}>"

    def test_a_group_participant_who_is_me_still_says_me(self):
        panel = _Stub(conversation_jid="120363000000000001@g.us")

        assert panel._get_quoted_sender(_ctx(ME), _reply()) == "Eu"


def _ctx_no_participant(stanza_id="QUOTED1"):
    return {"participant": "", "stanzaId": stanza_id}


def _quoted_msg(msg_id="QUOTED1", from_me=False, participant=""):
    key = {"id": msg_id, "fromMe": from_me}
    if participant:
        key["participant"] = participant
    return {"key": key}


class TestGroupReplyWithNoParticipantInContextInfo:
    """Reported live: a group reply rendered as "respondendo a Eu" (and was
    announced that way), but "go to quoted message" landed on a THIRD
    member's message, not the user's own. contextInfo.participant was empty
    on that reply — a known-unreliable field from this same API layer (see
    _get_context_info()'s docstring) — and the old fallback assumed that
    only ever happens in 1:1 chats, where "no participant" unambiguously
    means "the other party". Applied to a group it silently guessed "me"
    instead of admitting it does not actually know.
    """

    def test_resolves_via_the_quoted_messages_own_recorded_sender(self):
        """The quoted message IS loaded locally (same as "go to quoted
        message" would find) — its own key.participant is the source of
        truth, not a guess."""
        panel = _Stub(conversation_jid="120363000000000001@g.us")
        panel._sorted_messages = [_quoted_msg(participant=THIRD)]

        result = panel._get_quoted_sender(_ctx_no_participant(), _reply())

        assert result == f"<lookup:{THIRD}>"

    def test_never_defaults_to_me_when_the_quoted_sender_is_a_third_party(self):
        panel = _Stub(conversation_jid="120363000000000001@g.us")
        panel._sorted_messages = [_quoted_msg(participant=THIRD)]

        assert panel._get_quoted_sender(_ctx_no_participant(), _reply()) != "Eu"

    def test_quoting_my_own_message_still_says_me(self):
        panel = _Stub(conversation_jid="120363000000000001@g.us")
        panel._sorted_messages = [_quoted_msg(from_me=True)]

        assert panel._get_quoted_sender(_ctx_no_participant(), _reply()) == "Eu"

    def test_quoted_message_not_loaded_locally_says_unknown_not_me(self):
        """No participant AND the quoted message isn't in _sorted_messages —
        genuinely unresolvable, must not guess "Eu"."""
        panel = _Stub(conversation_jid="120363000000000001@g.us")
        panel._sorted_messages = []

        assert panel._get_quoted_sender(_ctx_no_participant(), _reply()) == "unnamed_participant"

    def test_quoted_message_loaded_but_with_no_sender_on_record_says_unknown(self):
        panel = _Stub(conversation_jid="120363000000000001@g.us")
        panel._sorted_messages = [_quoted_msg(participant="")]

        assert panel._get_quoted_sender(_ctx_no_participant(), _reply()) == "unnamed_participant"

    def test_a_1to1_reply_with_no_participant_is_unaffected(self):
        """1:1 chats keep the pre-existing behavior: no participant there is
        the normal Baileys shape, not missing data. The reply itself came
        from the other party (fromMe=False), so per the existing 1:1
        assumption they must be replying to the user."""
        panel = _Stub(conversation_jid=OTHER, contact_name="Fulano")

        result = panel._get_quoted_sender(_ctx_no_participant(), _reply(from_me=False))

        assert result == "Eu"
