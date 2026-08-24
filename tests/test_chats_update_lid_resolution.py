"""Tests for MainWindow._resolve_chat_for_event() — bridging the @lid and
phone identities of a chat when a chats-update event arrives.

WhatsApp keys these events by whichever identity its own Store holds the
chat under. On @lid-enabled accounts that is the linked-device id, while
WinZapp normalizes conversations to the phone JID (_normalize_jid leaves
@lid untouched on purpose). on_chat_unread_update() and
on_chat_archive_update() looked the event up by that JID alone and returned
silently when it found nothing — so a chat read on the phone kept its badge
lit and nothing was written to log.log to say the event had even arrived.

on_chat_pin_update() already did this bridging inline, which is the reason
a pin made on the phone showed up in WinZapp while a read made in the same
session did not.

MainWindow is a wx.Frame and cannot be instantiated without a running
wx.App, so the method is exercised bound onto a plain stub — same approach
as tests/test_phone_side_sync.py and tests/test_sender_names.py.
"""

from main import MainWindow


PHONE = "5511999999999@s.whatsapp.net"
LID = "133041125077153@lid"
GROUP = "120363000000000000@g.us"


class _Stub:
    _normalize_jid = staticmethod(MainWindow._normalize_jid)
    _resolve_chat_for_event = MainWindow._resolve_chat_for_event

    def __init__(self, chats, lid_to_phone=None, phone_to_lid=None):
        self.chats = chats
        if lid_to_phone is not None:
            self._lid_to_phone = lid_to_phone
        if phone_to_lid is not None:
            self._phone_to_lid = phone_to_lid


def _chat(jid):
    return {"remoteJid": jid, "unreadCount": 2}


class TestDirectHits:
    def test_a_jid_stored_as_is(self):
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat})

        assert stub._resolve_chat_for_event(PHONE) == (PHONE, chat)

    def test_a_legacy_c_us_jid_normalizes_to_the_stored_phone_jid(self):
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat})

        assert stub._resolve_chat_for_event("5511999999999@c.us") == (PHONE, chat)

    def test_a_device_suffix_is_stripped(self):
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat})

        assert stub._resolve_chat_for_event("5511999999999:60@c.us") == (PHONE, chat)

    def test_a_group_jid(self):
        chat = _chat(GROUP)
        stub = _Stub({GROUP: chat})

        assert stub._resolve_chat_for_event(GROUP) == (GROUP, chat)


class TestTheLidBridge:
    def test_an_event_keyed_by_lid_finds_the_chat_stored_under_the_phone_jid(self):
        """The reported failure: the event arrives as @lid, the conversation
        lives under @s.whatsapp.net, and the handler used to give up."""
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat}, lid_to_phone={LID: PHONE})

        assert stub._resolve_chat_for_event(LID) == (PHONE, chat)

    def test_the_returned_key_is_where_the_chat_actually_lives(self):
        """Callers write back under this key (_locally_read_at,
        _schedule_save(dirty_jid=...)), so returning the event's own @lid
        would scatter the bookkeeping across two identities."""
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat}, lid_to_phone={LID: PHONE})

        key, _ = stub._resolve_chat_for_event(LID)

        assert key == PHONE
        assert key != LID

    def test_a_lid_mapped_to_a_legacy_c_us_jid_is_normalized_too(self):
        chat = _chat(PHONE)
        stub = _Stub({PHONE: chat}, lid_to_phone={LID: "5511999999999@c.us"})

        assert stub._resolve_chat_for_event(LID) == (PHONE, chat)

    def test_an_event_keyed_by_phone_finds_a_chat_stored_under_lid(self):
        """The mirror case — a chat WinZapp never managed to bridge to a
        phone number is stored under its @lid."""
        chat = _chat(LID)
        stub = _Stub({LID: chat}, phone_to_lid={PHONE: LID})

        assert stub._resolve_chat_for_event(PHONE) == (LID, chat)


class TestMisses:
    def test_an_unknown_jid_returns_no_chat(self):
        stub = _Stub({PHONE: _chat(PHONE)})

        key, chat = stub._resolve_chat_for_event("5511000000000@s.whatsapp.net")

        assert chat is None
        assert key == "5511000000000@s.whatsapp.net"

    def test_a_lid_that_maps_to_a_chat_we_do_not_have(self):
        stub = _Stub({}, lid_to_phone={LID: PHONE})

        assert stub._resolve_chat_for_event(LID) == (LID, None)

    def test_missing_mapping_caches_are_not_fatal(self):
        """The caches are created lazily — every other call site reads them
        through getattr(..., {}) for this reason."""
        stub = _Stub({})

        assert stub._resolve_chat_for_event(LID) == (LID, None)

    def test_an_empty_jid(self):
        stub = _Stub({PHONE: _chat(PHONE)})

        assert stub._resolve_chat_for_event("") == ("", None)
