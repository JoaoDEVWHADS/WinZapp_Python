"""Tests for MainWindow._is_reply_or_mention_of_me() — the check that lets a
reply to one of my own messages, or an explicit @-mention, break through a
muted chat's notification suppression in on_incoming_message().

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the method under test (plus the small helpers it calls through self) is
bound onto a plain stub — same pattern as tests/test_sender_names.py.
"""

from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for mention/reply detection."""

    _is_self_jid = MainWindow._is_self_jid
    _phone_digits_equivalent = staticmethod(MainWindow._phone_digits_equivalent)
    _is_reply_or_mention_of_me = MainWindow._is_reply_or_mention_of_me

    def __init__(self, my_jid="5511999998888@s.whatsapp.net", chats=None):
        self.my_jid = my_jid
        self.my_lid = ""
        self._lid_to_phone = {}
        self.chats = chats or {}


ME = "5511999998888@s.whatsapp.net"
OTHER = "5511977776666@s.whatsapp.net"
GROUP = "1234567890@g.us"


def _record(msg_id, from_me):
    return {"key": {"id": msg_id, "fromMe": from_me}}


class TestMentions:
    def test_top_level_context_info_mentioning_me(self):
        stub = _Stub(my_jid=ME)
        msg = {
            "contextInfo": {"mentionedJid": [ME]},
            "message": {"conversation": "oi @você"},
        }
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is True

    def test_mention_nested_in_extended_text_message(self):
        stub = _Stub(my_jid=ME)
        msg = {
            "message": {
                "extendedTextMessage": {
                    "text": "oi @você",
                    "contextInfo": {"mentionedJid": [ME]},
                }
            }
        }
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is True

    def test_mentioning_someone_else_is_not_a_mention_of_me(self):
        stub = _Stub(my_jid=ME)
        msg = {"contextInfo": {"mentionedJid": [OTHER]}}
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is False

    def test_no_mentioned_jid_at_all(self):
        stub = _Stub(my_jid=ME)
        msg = {"message": {"conversation": "oi"}}
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is False


class TestRepliesWithAParticipant:
    """Group replies carry contextInfo.participant naming the quoted
    message's author directly — no local history lookup needed."""

    def test_reply_to_my_message_in_a_group(self):
        stub = _Stub(my_jid=ME)
        msg = {"contextInfo": {"quotedMessage": {}, "participant": ME}}
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is True

    def test_reply_to_someone_elses_message_in_a_group(self):
        stub = _Stub(my_jid=ME)
        msg = {"contextInfo": {"quotedMessage": {}, "participant": OTHER}}
        assert stub._is_reply_or_mention_of_me(msg, GROUP) is False


class TestRepliesWithoutAParticipant:
    """1:1 chats: Baileys leaves contextInfo.participant empty, so the quoted
    message's own fromMe flag (looked up from local history by stanzaId) is
    what decides whether the reply is to something I said."""

    def test_reply_to_my_own_message_resolved_via_local_history(self):
        chats = {
            OTHER: {"messages": {"messages": {"records": [_record("ABC", from_me=True)]}}}
        }
        stub = _Stub(my_jid=ME, chats=chats)
        msg = {"contextInfo": {"quotedMessage": {}, "stanzaId": "ABC"}}
        assert stub._is_reply_or_mention_of_me(msg, OTHER) is True

    def test_reply_to_the_other_partys_own_message(self):
        chats = {
            OTHER: {"messages": {"messages": {"records": [_record("ABC", from_me=False)]}}}
        }
        stub = _Stub(my_jid=ME, chats=chats)
        msg = {"contextInfo": {"quotedMessage": {}, "stanzaId": "ABC"}}
        assert stub._is_reply_or_mention_of_me(msg, OTHER) is False

    def test_quoted_message_no_longer_in_local_history(self):
        stub = _Stub(my_jid=ME, chats={})
        msg = {"contextInfo": {"quotedMessage": {}, "stanzaId": "GONE"}}
        assert stub._is_reply_or_mention_of_me(msg, OTHER) is False


class TestNotAReplyAtAll:
    def test_plain_message_with_no_context_info(self):
        stub = _Stub(my_jid=ME)
        msg = {"message": {"conversation": "oi"}}
        assert stub._is_reply_or_mention_of_me(msg, OTHER) is False

    def test_context_info_present_but_not_a_quote_or_mention(self):
        """isForwarded and similar flags share contextInfo with real quotes/
        mentions — must not be mistaken for either."""
        stub = _Stub(my_jid=ME)
        msg = {"contextInfo": {"isForwarded": True}}
        assert stub._is_reply_or_mention_of_me(msg, OTHER) is False
