"""Tests for the JID resolution used by the outgoing-message paths.

These cover the "WinZapp says sent, nothing arrives on the phone" bug: private
sends were addressed to the legacy ``<phone>@c.us`` JID even for chats WhatsApp
has moved to LID addressing.  WhatsApp Web happily creates the message there and
hands back a real ``3EB0…`` id — so the HTTP call looks successful — but the
server never acks it (``ack`` stays 0/CLOCK) and it reaches neither the phone nor
the recipient.  Groups were unaffected, since ``@g.us`` is canonical everywhere.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so
the methods under test are exercised as plain functions against a small stub
that carries just the attributes they touch.
"""

import pytest

from main import MainWindow


# Fictional identifiers only — same shape as the real ones (14-digit @lid,
# 12-digit BR phone, 18-digit @g.us starting with 120363), no real account.
LID = "10000000000001@lid"
PHONE_NET = "551199999999@s.whatsapp.net"
PHONE_CUS = "551199999999@c.us"
GROUP = "120363000000000001@g.us"


class _Stub:
    """Minimal stand-in for MainWindow for the JID resolvers."""

    def __init__(self, lid_to_phone=None, phone_to_lid=None):
        self._lid_to_phone = dict(lid_to_phone or {})
        self._phone_to_lid = dict(phone_to_lid or {})

    _resolve_jid_for_chat_state = MainWindow._resolve_jid_for_chat_state
    _resolve_jid_for_send = MainWindow._resolve_jid_for_send
    _legacy_phone_for_send = MainWindow._legacy_phone_for_send
    _resolve_jid_for_msg_key = MainWindow._resolve_jid_for_msg_key


@pytest.fixture
def mapped():
    """A stub that knows the @lid <-> phone pair for one private chat."""
    return _Stub(lid_to_phone={LID: PHONE_NET}, phone_to_lid={PHONE_NET: LID})


@pytest.fixture
def unmapped():
    return _Stub()


class TestResolveJidForSend:
    def test_phone_jid_resolves_to_lid_when_mapped(self, mapped):
        assert mapped._resolve_jid_for_send(PHONE_NET) == LID

    def test_legacy_cus_jid_also_resolves_to_lid(self, mapped):
        # The cache is keyed on @s.whatsapp.net, so @c.us input must be
        # normalized before the lookup or the mapping is missed.
        assert mapped._resolve_jid_for_send(PHONE_CUS) == LID

    def test_lid_jid_is_kept(self, mapped):
        assert mapped._resolve_jid_for_send(LID) == LID

    def test_falls_back_to_cus_without_a_mapping(self, unmapped):
        assert unmapped._resolve_jid_for_send(PHONE_NET) == PHONE_CUS

    def test_group_jid_is_untouched(self, mapped):
        assert mapped._resolve_jid_for_send(GROUP) == GROUP

    def test_broadcast_jid_is_untouched(self, mapped):
        assert mapped._resolve_jid_for_send("status@broadcast") == "status@broadcast"

    def test_empty_jid_is_passed_through(self, mapped):
        assert mapped._resolve_jid_for_send("") == ""

    def test_matches_chat_state_policy(self, mapped):
        # Sending and typing/presence must agree on the destination: the two
        # disagreeing is what let messages be typed into the @lid chat and sent
        # to the legacy @c.us one.
        for jid in (PHONE_NET, PHONE_CUS, LID, GROUP):
            assert mapped._resolve_jid_for_send(jid) == mapped._resolve_jid_for_chat_state(jid)


class TestLegacyPhoneForSend:
    def test_lid_maps_back_to_cus(self, mapped):
        assert mapped._legacy_phone_for_send(LID) == PHONE_CUS

    def test_unmapped_lid_has_no_fallback(self, unmapped):
        # Without a phone number there is nothing to retry on, and the caller
        # must not invent one from the @lid digits.
        assert unmapped._legacy_phone_for_send(LID) == ""

    def test_phone_jid_normalizes_to_cus(self, mapped):
        assert mapped._legacy_phone_for_send(PHONE_NET) == PHONE_CUS

    def test_group_has_no_fallback(self, mapped):
        assert mapped._legacy_phone_for_send(GROUP) == ""

    def test_broadcast_has_no_fallback(self, mapped):
        assert mapped._legacy_phone_for_send("status@broadcast") == ""

    def test_empty_jid_has_no_fallback(self, mapped):
        assert mapped._legacy_phone_for_send("") == ""

    def test_fallback_differs_from_primary_destination(self, mapped):
        # The retry has to actually change the address, otherwise it just
        # re-sends the same failing request.
        primary = mapped._resolve_jid_for_send(PHONE_NET)
        assert mapped._legacy_phone_for_send(primary) != primary


class TestResolveJidForMsgKey:
    """The message-key/get-messages path must stay on the phone form."""

    def test_lid_becomes_cus(self, mapped):
        assert mapped._resolve_jid_for_msg_key(LID) == PHONE_CUS

    def test_phone_jid_becomes_cus(self, mapped):
        assert mapped._resolve_jid_for_msg_key(PHONE_NET) == PHONE_CUS

    def test_unmapped_lid_is_kept(self, unmapped):
        assert unmapped._resolve_jid_for_msg_key(LID) == LID

    def test_group_jid_is_untouched(self, mapped):
        assert mapped._resolve_jid_for_msg_key(GROUP) == GROUP

    def test_does_not_follow_the_send_policy(self, mapped):
        # Guards against someone "simplifying" the two resolvers into one:
        # flipping this one to @lid changes serialized message ids.
        assert mapped._resolve_jid_for_msg_key(PHONE_NET) != mapped._resolve_jid_for_send(PHONE_NET)
