"""Tests for MainWindow._serialize_msg_id()'s handling of status@broadcast.

Bug: status updates ("Status" tab) never played their video/audio and the
like button always failed with a generic error. Both operations build a
serialized WhatsApp message id via _serialize_msg_id() and send it to
WPPConnect (get-media-by-message / react-message). WhatsApp/Baileys treats
status@broadcast as a shared "chat" the same way it treats a group: looking
up one specific status requires the actual poster's JID as a trailing
`_<participant>` segment, exactly like looking up one specific group message
does. The participant-appending branch only checked `chat.endswith("@g.us")`,
so every status id came out as the 2-segment `<fromMe>_status@broadcast_<id>`
instead of the required 3-segment form — which never matched anything in
WPPConnect's Store, so both requests silently/loudly failed.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test is exercised as a plain function against a small
stub — same approach as tests/test_message_bookmarks.py.
"""

from main import MainWindow


class _Stub:
    _serialize_msg_id = MainWindow._serialize_msg_id

    def __init__(self, phone_to_lid=None, my_jid="", my_lid=""):
        self._phone_to_lid = phone_to_lid or {}
        self.my_jid = my_jid
        self.my_lid = my_lid


class TestSerializeStatusBroadcastId:
    def test_someone_elses_status_includes_the_participant(self):
        s = _Stub()
        key = {
            "id": "ABCDEF",
            "fromMe": False,
            "remoteJid": "status@broadcast",
            "participant": "5521999999999@s.whatsapp.net",
        }
        result = s._serialize_msg_id("status@broadcast", key)
        assert result == "false_status@broadcast_ABCDEF_5521999999999@c.us"

    def test_own_status_uses_my_jid_as_participant(self):
        s = _Stub(my_jid="5521888888888@s.whatsapp.net")
        key = {"id": "XYZ", "fromMe": True, "remoteJid": "status@broadcast"}
        result = s._serialize_msg_id("status@broadcast", key)
        assert result == "true_status@broadcast_XYZ_5521888888888@c.us"

    def test_prefers_cached_lid_for_the_participant(self):
        s = _Stub(phone_to_lid={"5521999999999@s.whatsapp.net": "111222333@lid"})
        key = {
            "id": "ABCDEF",
            "fromMe": False,
            "remoteJid": "status@broadcast",
            "participant": "5521999999999@s.whatsapp.net",
        }
        result = s._serialize_msg_id("status@broadcast", key)
        assert result == "false_status@broadcast_ABCDEF_111222333@lid"

    def test_group_messages_are_unaffected(self):
        s = _Stub()
        key = {
            "id": "GID1",
            "fromMe": False,
            "remoteJid": "12036312345@g.us",
            "participant": "5521999999999@s.whatsapp.net",
        }
        result = s._serialize_msg_id("12036312345@g.us", key)
        assert result == "false_12036312345@g.us_GID1_5521999999999@c.us"

    def test_1on1_messages_still_have_no_participant(self):
        s = _Stub()
        key = {"id": "M1", "fromMe": False, "remoteJid": "5521999999999@s.whatsapp.net"}
        result = s._serialize_msg_id("5521999999999@s.whatsapp.net", key)
        assert result == "false_5521999999999@c.us_M1"


class TestSerialize1on1IdPrefersLid:
    """Regression test: quoting your own message in a private (1-on-1) chat
    always failed ("não foi possível citar a mensagem"), private chats only
    — groups worked fine. Root cause: send_text_message() et al. resolve the
    actual send destination to @lid whenever the contact is cached (see
    MainWindow._resolve_jid_for_send()'s docstring) — WhatsApp Web indexes
    every message of a @lid-addressed chat, including our own outgoing ones,
    under that @lid. But the "chat" segment of a quoted-id built from a
    locally-stored own message (self.conversation["remoteJid"], captured at
    compose time) stayed in whatever phone/@c.us form the chat happened to
    be keyed under — never resolved to @lid — so it stopped matching
    WhatsApp Web's Store and the quote silently failed. A message just
    RECEIVED from the other party doesn't hit this: its remoteJid, reported
    live for an already-@lid chat, already arrives in @lid form.
    """

    def test_own_message_prefers_the_cached_lid(self):
        s = _Stub(phone_to_lid={"5521999999999@s.whatsapp.net": "111222333@lid"})
        key = {"id": "OWN1", "fromMe": True, "remoteJid": "5521999999999@s.whatsapp.net"}
        result = s._serialize_msg_id("5521999999999@s.whatsapp.net", key)
        assert result == "true_111222333@lid_OWN1"

    def test_received_message_also_prefers_the_cached_lid(self):
        s = _Stub(phone_to_lid={"5521999999999@s.whatsapp.net": "111222333@lid"})
        key = {"id": "RECV1", "fromMe": False, "remoteJid": "5521999999999@s.whatsapp.net"}
        result = s._serialize_msg_id("5521999999999@s.whatsapp.net", key)
        assert result == "false_111222333@lid_RECV1"

    def test_falls_back_to_c_us_when_no_lid_is_cached(self):
        s = _Stub()
        key = {"id": "OWN2", "fromMe": True, "remoteJid": "5521999999999@s.whatsapp.net"}
        result = s._serialize_msg_id("5521999999999@s.whatsapp.net", key)
        assert result == "true_5521999999999@c.us_OWN2"

    def test_already_lid_addressed_chat_is_left_alone(self):
        s = _Stub()
        key = {"id": "OWN3", "fromMe": True, "remoteJid": "111222333@lid"}
        result = s._serialize_msg_id("111222333@lid", key)
        assert result == "true_111222333@lid_OWN3"
