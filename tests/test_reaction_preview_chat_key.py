"""A reaction updates the preview of the conversation however it is addressed.

Reported (Neonize): a reaction to the user's message showed in the chat
list's preview in one conversation and not in another. A reaction reaches
on_new_message() before the @lid/phone resolution every other message goes
through; a private chat's reaction arrives as its @lid, and a chat stored
under the number was not found."""
import time

from core.reaction_echo import stored_reaction_chat
from main import MainWindow
from tests.test_archived_chat_sound_tts import _StubMainWindow

PHONE = "5531988887777@s.whatsapp.net"
LID = "123456789012345@lid"


def test_the_stored_key_is_found_under_every_spelling():
    chats = {PHONE: {}}
    assert stored_reaction_chat(chats, LID, {LID: PHONE}, {}) == PHONE
    assert stored_reaction_chat(chats, PHONE, {}, {}) == PHONE
    assert stored_reaction_chat(chats, "5531988887777@c.us", {}, {}) == PHONE
    # stored under the LID, reaction addressed to the number
    assert stored_reaction_chat({LID: {}}, PHONE, {}, {PHONE: LID}) == LID
    # Brazil's ninth digit
    assert stored_reaction_chat({"553188887777@s.whatsapp.net": {}}, PHONE, {}, {}) == \
        "553188887777@s.whatsapp.net"


def test_an_unknown_chat_keeps_its_own_address():
    assert stored_reaction_chat({}, LID, {}, {}) == LID
    assert stored_reaction_chat({"1203@g.us": {}}, "1203@g.us") == "1203@g.us"


def _reaction(chat_jid):
    return {
        "key": {"remoteJid": chat_jid, "fromMe": False, "id": "RX1"},
        "messageType": "reactionMessage",
        "message": {"reactionMessage": {"text": "❤️",
                                        "key": {"id": "MINE1", "fromMe": True,
                                                "remoteJid": chat_jid}}},
        "pushName": "",
        "messageTimestamp": int(time.time()),
    }


def test_a_reaction_addressed_to_the_lid_updates_the_chat_stored_under_the_number():
    stub = _StubMainWindow()
    stub._track_last_reaction = MainWindow._track_last_reaction.__get__(stub)
    stub.chats = {PHONE: {"remoteJid": PHONE, "messages": []}}
    stub._lid_to_phone = {LID: PHONE}
    stub._phone_to_lid = {PHONE: LID}

    stub.on_new_message(_reaction(LID))

    assert stub.chats[PHONE]["_last_reaction"]["emoji"] == "❤️"
    assert stub.chats[PHONE]["_last_reaction"]["target_id"] == "MINE1"
    assert LID not in stub.chats
