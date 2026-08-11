"""Tests for phantom group-participant chat filtering (client/main.py).

Reported live: right after the first sync post-login, members of the user's
groups appeared as individual conversations in the chat list — people the
user never had a 1:1 chat with. The WhatsApp Web store creates a chat entry
for a group participant (their @lid/@c.us) because of the messages they wrote
in groups; list-chats returns that entry, and it only disappeared after an
F5 resync.

Two defenses are added:
  1. MainWindow._last_received_jid(): a non-group chat whose lastReceivedKey
     belongs to a @g.us group is a phantom participant entry — get_remote_chats
     skips it.
  2. The sync_chat_messages membership filter: messages that normalize to a
     different remoteJid than the chat (group messages answered for a
     participant @lid) are not stored as 1:1 history.

MainWindow is a wx.Frame and cannot be instantiated without a running app, so
the logic is exercised as plain functions against stubs — same approach as
tests/test_sender_names.py.
"""

from main import MainWindow


def test_last_received_jid_from_remote_object():
    # Real list-chats payload: remote._serialized is already the bare JID.
    chat = {"lastReceivedKey": {"remote": {"_serialized": "73504238084102@lid"}}}
    assert MainWindow._last_received_jid(chat) == "73504238084102@lid"


def test_last_received_jid_from_serialized_string():
    # Fallback: whole serialized "<fromMe>_<chatId>_<id>" -> chatId is parts[1].
    chat = {"lastReceivedKey": {"_serialized": "false_120363409931936700@g.us_3EB0C4C4_83069516128367@lid"}}
    assert MainWindow._last_received_jid(chat) == "120363409931936700@g.us"


def test_last_received_jid_from_serialized_string_1on1():
    chat = {"lastReceivedKey": {"_serialized": "false_73504238084102@lid_3EB09717AA0AA3649251C2"}}
    assert MainWindow._last_received_jid(chat) == "73504238084102@lid"


def test_last_received_jid_empty_cases():
    assert MainWindow._last_received_jid({"lastReceivedKey": {}}) == ""
    assert MainWindow._last_received_jid({}) == ""
    assert MainWindow._last_received_jid(None) == ""
    assert MainWindow._last_received_jid("nope") == ""


def test_phantom_participant_chat_is_detected():
    # A @lid chat whose last received message came from a group is a phantom
    # participant entry, not a real 1:1 conversation.
    chat = {"lastReceivedKey": {"_serialized": "false_120363409931936700@g.us_3EB0C4C4_83069516128367@lid"}}
    jid = MainWindow._last_received_jid(chat)
    assert jid.endswith("@g.us")
    assert not jid.endswith("@lid")


def test_real_1on1_chat_is_not_marked_phantom():
    chat = {"lastReceivedKey": {"remote": {"_serialized": "73504238084102@lid"}}}
    jid = MainWindow._last_received_jid(chat)
    assert jid.endswith("@lid")
    assert not jid.endswith("@g.us")


class _SyncStub:
    """Carries just what the sync_chat_messages membership filter touches."""

    def _normalize_jid(self, jid):
        return MainWindow._normalize_jid(jid)


def test_membership_filter_drops_group_messages_from_1on1_chat():
    # get-messages for a participant @lid answered with group messages
    # (remoteJid @g.us) — those must not be stored as 1:1 history.
    stub = _SyncStub()
    chat_jid = "83069516128367@lid"
    fetched = [
        {"key": {"remoteJid": "83069516128367@lid", "id": "A1"}, "messageTimestamp": 1},
        {"key": {"remoteJid": "120363409931936700@g.us", "id": "A2"}, "messageTimestamp": 2},
        {"key": {"remoteJid": "83069516128367@s.whatsapp.net", "id": "A3"}, "messageTimestamp": 3},
    ]
    kept = [
        m for m in fetched
        if stub._normalize_jid((m.get("key") or {}).get("remoteJid", "")) == chat_jid
    ]
    assert [m["key"]["id"] for m in kept] == ["A1"]


def test_membership_filter_keeps_phone_chat_messages():
    # A phone chat keeps its own @s.whatsapp.net messages; group messages out.
    stub = _SyncStub()
    chat_jid = "557791074215@s.whatsapp.net"
    fetched = [
        {"key": {"remoteJid": "557791074215@s.whatsapp.net", "id": "B1"}, "messageTimestamp": 1},
        {"key": {"remoteJid": "557791074215@c.us", "id": "B2"}, "messageTimestamp": 2},
        {"key": {"remoteJid": "120363409931936700@g.us", "id": "B3"}, "messageTimestamp": 3},
    ]
    kept = [
        m for m in fetched
        if stub._normalize_jid((m.get("key") or {}).get("remoteJid", "")) == chat_jid
    ]
    assert [m["key"]["id"] for m in kept] == ["B1", "B2"]
