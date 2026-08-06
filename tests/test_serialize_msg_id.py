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
