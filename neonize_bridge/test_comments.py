"""Community announcement comments: the cipher (with fixed vectors), the secret in
whatsmeow's database, the storage and the receiving. No WhatsApp; the cipher follows
the reading of msgsecret.go and nothing here was proved against a real account."""
import hashlib
import hmac
import os
import sqlite3
from types import SimpleNamespace as N

import pytest
from neonize.proto.waCommon.WACommon_pb2 import MessageKey
from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import (
    EncCommentMessage, ExtendedTextMessage, Message, ProtocolMessage)

import comments as com
from store import Store

SECRET = bytes(range(32))
IV = bytes(0xA0 + i for i in range(12))
# Computed with Go's crypto/hkdf and crypto/cipher over the logic of
# generateMsgSecretKey (msgsecret.go), for these same arguments.
GO_KEY = "abd952f75d77af491838d816826b68235a81a10de4cb0459e3b97c8813109de6"
GO_ENCRYPTED = "cf1e31a0b5cde872022c37bec232fe25c493af60ec2420661e65f7d24dee5054d8"
GO_KEY_NUMBERS = "125e0e6aa9ac8d9d07fa1eff12dc9b5d17dd5e0410cf0d6544fa7ff00e64ddff"
PLAN = bytes.fromhex("0a0f6f6c612c20636f6d756e6964616465")     # Message(conversation=...)

GROUP = "120363000000000001@g.us"
AUTHOR = "111222333@lid"
MY_LID = "999888777666555@lid"
ME = "5511888880000@s.whatsapp.net"


def hkdf_sha256(ikm, info, length=32):
    """RFC 5869 without salt, written by hand: checks the library."""
    prk = hmac.new(bytes(32), ikm, hashlib.sha256).digest()
    output, block = b"", b""
    counter = 1
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


# -------------------------------------------------------------------- cipher
def test_fixed_vectors_from_go():
    key = com.comment_key(SECRET, "3EB0AABBCCDD1122", "111222333@lid", "444555666@lid")
    assert key.hex() == GO_KEY
    assert com.comment_key(SECRET, "ABC", "5511999990000@s.whatsapp.net",
                           "5511888880000@s.whatsapp.net").hex() == GO_KEY_NUMBERS
    payload, iv = com.encrypt_comment(SECRET, "3EB0AABBCCDD1122", "111222333@lid",
                                      "444555666@lid", PLAN, IV)
    assert (payload.hex(), iv) == (GO_ENCRYPTED, IV)
    assert Message.FromString(PLAN).conversation == "ola, comunidade"


def test_the_key_is_the_rfc_hkdf_with_whatsmeows_info():
    info = b"IDX" + b"1@lid" + b"2@lid" + b"Enc Comment"
    assert com.comment_key(SECRET, "IDX", "1@lid", "2@lid") == hkdf_sha256(SECRET, info)


def test_device_and_agent_are_not_part_of_the_key():
    base = com.comment_key(SECRET, "A", "1@lid", "2@s.whatsapp.net")
    assert com.comment_key(SECRET, "A", "1:7@lid", "2:3@s.whatsapp.net") == base
    assert com.comment_key(SECRET, "A", "1.0:7@lid", "2@c.us") == base
    assert com.without_device("5511:12@s.whatsapp.net") == "5511@s.whatsapp.net"
    assert com.without_device("") == ""


def test_round_trip_and_the_tag_goes_at_the_end():
    payload, iv = com.encrypt_comment(SECRET, "ID1", AUTHOR, MY_LID, b"hi")
    assert len(iv) == 12 and len(payload) == 2 + 16
    assert com.decrypt_comment(SECRET, "ID1", [AUTHOR], [MY_LID], iv, payload) == b"hi"


def test_wrong_sender_or_tampered_payload_does_not_open():
    payload, iv = com.encrypt_comment(SECRET, "ID1", AUTHOR, MY_LID, b"hi")
    with pytest.raises(com.UnreadableComment):
        com.decrypt_comment(SECRET, "ID1", ["1@lid"], [MY_LID], iv, payload)
    with pytest.raises(com.UnreadableComment):
        com.decrypt_comment(SECRET, "ID1", [AUTHOR], [MY_LID], iv, payload[:-1] + bytes([payload[-1] ^ 0xFF]))
    with pytest.raises(com.UnreadableComment):
        com.decrypt_comment(SECRET, "OTHER", [AUTHOR], [MY_LID], iv, payload)
    with pytest.raises(com.UnreadableComment):
        com.decrypt_comment(SECRET, "ID1", [AUTHOR], [MY_LID], b"short", payload)


def test_decrypt_tries_the_other_form_of_the_sender():
    """The comment was encrypted with the sender as a number; the key says LID."""
    payload, iv = com.encrypt_comment(SECRET, "ID1", "5511@s.whatsapp.net", MY_LID, b"x")
    assert com.decrypt_comment(
        SECRET, "ID1", [AUTHOR, "5511@s.whatsapp.net"], [ME, MY_LID], iv, payload) == b"x"


def test_original_sender_from_key():
    f = com.original_sender_from_key
    assert f(True, "anything@lid", "7:3@lid") == "7@lid"           # fromMe: whoever commented
    assert f(False, "8:1@lid", "7@lid") == "8@lid"
    assert f(False, "8@c.us", "7@lid") == "8@s.whatsapp.net"
    assert f(False, "", "7@lid") == ""
    assert f(False, "120363@g.us", "7@lid") == ""


# ------------------------------------------------------------------- secret
def whatsmeow_database(path, secrets=(), mapping=None):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE whatsmeow_message_secrets(our_jid TEXT, chat_jid TEXT, "
                "sender_jid TEXT, message_id TEXT, key BLOB NOT NULL, "
                "PRIMARY KEY(our_jid, chat_jid, sender_jid, message_id))")
    if mapping is not None:
        con.execute("CREATE TABLE whatsmeow_lid_map(lid TEXT PRIMARY KEY, pn TEXT)")
        con.executemany("INSERT INTO whatsmeow_lid_map VALUES (?,?)", mapping)
    con.executemany("INSERT INTO whatsmeow_message_secrets VALUES ('me:1@s.whatsapp.net',?,?,?,?)",
                    secrets)
    con.commit()
    con.close()


def test_secret_read_from_whatsmeows_database(tmp_path):
    path = str(tmp_path / "session.db")
    whatsmeow_database(path, [(GROUP, AUTHOR, "ID1", SECRET)], mapping=[])
    assert com.message_secret(path, GROUP, AUTHOR, "ID1") == (SECRET, AUTHOR)
    assert com.message_secret(path, GROUP, "111222333:5@lid", "ID1") == (SECRET, AUTHOR)
    assert com.message_secret(path, GROUP, AUTHOR, "OTHER") is None
    assert com.message_secret(path, "1@g.us", AUTHOR, "ID1") is None


def test_secret_matches_number_and_lid_through_the_map(tmp_path):
    path = str(tmp_path / "session.db")
    whatsmeow_database(path, [(GROUP, AUTHOR, "ID1", SECRET)],
                       mapping=[("111222333", "5511777770000")])
    found = com.message_secret(path, GROUP, "5511777770000@s.whatsapp.net", "ID1")
    assert found == (SECRET, AUTHOR)       # returns the sender as it was stored


def test_secret_without_the_map_table_still_finds_the_exact_one(tmp_path):
    path = str(tmp_path / "session.db")
    whatsmeow_database(path, [(GROUP, AUTHOR, "ID1", SECRET)], mapping=None)
    assert com.message_secret(path, GROUP, AUTHOR, "ID1") == (SECRET, AUTHOR)


def test_secret_without_a_database_or_a_table_is_nothing_and_does_not_write(tmp_path):
    assert com.message_secret(str(tmp_path / "no.db"), GROUP, AUTHOR, "ID1") is None
    empty = str(tmp_path / "empty.db")
    sqlite3.connect(empty).close()
    assert com.message_secret(empty, GROUP, AUTHOR, "ID1") is None
    path = str(tmp_path / "session.db")
    whatsmeow_database(path, [(GROUP, AUTHOR, "ID1", SECRET)], mapping=[])
    before = open(path, "rb").read()
    com.message_secret(path, GROUP, AUTHOR, "ID1")
    assert open(path, "rb").read() == before


# --------------------------------------------------------- content and formats
def test_comment_text():
    assert com.comment_text(Message(conversation="a")) == "a"
    assert com.comment_text(Message(extendedTextMessage=ExtendedTextMessage(text="b"))) == "b"
    media = Message()
    media.imageMessage.caption = "caption"
    assert com.comment_text(media) == "caption"
    assert com.comment_text(Message()) == ""


def test_comment_message_is_what_whatsmeow_builds():
    m = com.comment_message(GROUP, False, "111222333:4@lid", "ID1", b"payload", IV)
    enc = m.encCommentMessage
    assert enc.targetMessageKey.remoteJID == GROUP and enc.targetMessageKey.ID == "ID1"
    assert enc.targetMessageKey.participant == AUTHOR and not enc.targetMessageKey.fromMe
    assert (enc.encPayload, enc.encIV) == (b"payload", IV)


def test_comment_to_wpp_and_events():
    row = {"id": "C1", "chat": GROUP, "author": "1@lid", "ts": 50, "type": "comment",
           "body": "oi", "from_me": 0}
    assert com.comment_to_wpp(row, "false_g_P_1@lid", "Ana") == {
        "id": "C1", "parentMsgId": "false_g_P_1@lid", "chatId": GROUP, "author": "1@lid",
        "authorName": "Ana", "fromMe": False, "timestamp": 50, "type": "comment", "body": "oi"}
    assert com.comment_to_wpp({**row, "type": "ciphertext"}, "s")["body"] == ""
    assert com.count_event("c", "false_g_P", GROUP, 3) == {
        "session": "c", "id": "false_g_P", "chatId": GROUP, "replyCount": 3}
    preview = com.preview_event("c", GROUP, {**row, "from_me": 1})
    assert preview == {"session": "c", "kind": "preview", "chatId": GROUP, "preview": {
        "type": "comment", "msgKey": f"true_{GROUP}_C1", "sender": "1@lid", "timestamp": 50}}
    assert com.preview_event("c", GROUP, None)["preview"] is None


# ---------------------------------------------------------------- storage
def test_old_database_gets_the_table_without_losing_anything(tmp_path):
    path = str(tmp_path / "bridge.db")
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE chats(jid TEXT PRIMARY KEY, name TEXT DEFAULT '', ts INTEGER "
                "DEFAULT 0, unread INTEGER DEFAULT 0, archived INTEGER DEFAULT 0, "
                "pinned INTEGER DEFAULT 0, muted INTEGER DEFAULT 0)")
    old.execute("INSERT INTO chats(jid, name) VALUES ('1@g.us', 'Announcements')")
    old.commit()
    old.close()
    db = Store(path)
    assert db.chats()[0]["name"] == "Announcements"
    assert db.comments_of("1@g.us", "P") == []
    db.close()
    Store(path).close()       # opening again does not break


def test_comments_stored_counted_and_deleted(tmp_path):
    db = Store(str(tmp_path / "bridge.db"))
    db.store_comment("C1", "P", GROUP, "1@lid", 10, "comment", "oi", False, "false_g_P_1@lid")
    db.store_comment("C2", "P", GROUP, "2@lid", 20, "ciphertext", "", False, "false_g_P_1@lid")
    db.store_comment("C3", "Q", GROUP, "2@lid", 30, "comment", "another", True, "s")
    db.store_comment("C1", "P", GROUP, "1@lid", 10, "comment", "REPEATED", False, "x")
    assert [c["id"] for c in db.comments_of(GROUP, "P")] == ["C1", "C2"]
    assert db.comments_of(GROUP, "P")[0]["body"] == "oi"      # the repeated one does not replace
    assert db.count_comments(GROUP, "P") == 2               # the unreadable one counts
    assert db.comment_counts() == {"P": 2, "Q": 1}
    assert db.last_comment(GROUP)["id"] == "C3"
    # the unreadable one becomes readable when the same comment arrives again and opens
    db.store_comment("C2", "P", GROUP, "2@lid", 20, "comment", "now reads", False, "s")
    assert db.comments_of(GROUP, "P")[1]["body"] == "now reads"
    assert db.revoke_comment(GROUP, "C3") == ("Q", "s")
    assert db.revoke_comment(GROUP, "C3") is None           # already deleted
    assert db.revoke_comment(GROUP, "NO") is None
    assert db.count_comments(GROUP, "Q") == 0
    assert db.last_comment(GROUP)["id"] == "C2"
    assert db.comments_of(GROUP, "Q")[0]["type"] == "revoked"
    db.close()


def test_messages_response_carries_the_replycount(tmp_path):
    db = Store(str(tmp_path / "bridge.db"))
    db.store_comment("C1", "P", GROUP, "1@lid", 10, "comment", "oi", False, "s")
    output = db.for_response([{"id": {"id": "P"}, "t": 1}, {"id": {"id": "Z"}, "t": 2}])
    assert output[0]["replyCount"] == 1 and "replyCount" not in output[1]
    db.close()


# ------------------------------------------------------------------- receiving
class FakeSession:
    def __init__(self, folder):
        self.folder = str(folder)
        self.name = "account"
        self.me, self.lid = ME, MY_LID
        self.db = Store(str(folder / "bridge.db"))
        self.events = []

    def emit(self, event, data):
        self.events.append((event, data))


def event_of(message, msg_id="C1", who=AUTHOR, from_me=False, ts=1700000000):
    user, _, server = who.partition("@")
    return (N(Sender=N(User=user, Server=server), IsFromMe=from_me),
            N(Message=message, Info=N(ID=msg_id, Timestamp=ts, Pushname="Ana")))


def encrypted_comment(text, parent_id="P", who=AUTHOR, parent_of=AUTHOR, from_me_in_key=False,
                      encrypt_as=None):
    payload, iv = com.encrypt_comment(SECRET, parent_id, parent_of, encrypt_as or who,
                                      com.serialize_text(text))
    return Message(encCommentMessage=EncCommentMessage(
        targetMessageKey=MessageKey(remoteJID=GROUP, participant=parent_of, fromMe=from_me_in_key,
                                    ID=parent_id),
        encPayload=payload, encIV=iv))


@pytest.fixture
def session(tmp_path):
    s = FakeSession(tmp_path)
    whatsmeow_database(str(tmp_path / "session.db"), [(GROUP, AUTHOR, "P", SECRET)], mapping=[])
    yield s
    s.db.close()


def test_received_comment_is_decrypted_stored_and_announced(session):
    o, e = event_of(encrypted_comment("ola", who="444555666@lid"), who="444555666@lid")
    assert com.receive(session, GROUP, o, e) is True
    row = session.db.comments_of(GROUP, "P")[0]
    assert (row["id"], row["type"], row["body"], row["author"], row["ts"]) == (
        "C1", "comment", "ola", "444555666@lid", 1700000000)
    assert row["from_me"] == 0
    serial = f"false_{GROUP}_P_{AUTHOR}"
    assert session.events[0] == ("announcement-replies", {
        "session": "account", "id": serial, "chatId": GROUP, "replyCount": 1})
    assert session.events[1][1]["preview"] == {
        "type": "comment", "msgKey": f"false_{GROUP}_C1_444555666@lid",
        "sender": "444555666@lid", "timestamp": 1700000000}
    assert session.db.contact_of("444555666@lid") == {"pushname": "Ana"}


def test_comment_from_the_own_account_on_another_device(session):
    """IsFromMe: whoever comments is the account; the device may use the number instead of the LID."""
    msg = encrypted_comment("mine", who=MY_LID)
    o, e = event_of(msg, who=ME, from_me=True)
    assert com.receive(session, GROUP, o, e) is True
    row = session.db.comments_of(GROUP, "P")[0]
    assert row["type"] == "comment" and row["body"] == "mine" and row["from_me"] == 1


def test_commented_message_that_is_mine_uses_the_keys_fromme(session):
    """The announcement is mine (fromMe in the key) and I commented myself: the original sender is me."""
    os.remove(os.path.join(session.folder, "session.db"))
    whatsmeow_database(os.path.join(session.folder, "session.db"),
                       [(GROUP, MY_LID, "P", SECRET)], mapping=[])
    msg = encrypted_comment("me", parent_of=MY_LID, who=MY_LID, from_me_in_key=True)
    o, e = event_of(msg, who=MY_LID, from_me=True)
    assert com.receive(session, GROUP, o, e) is True
    assert session.db.comments_of(GROUP, "P")[0]["body"] == "me"
    assert session.events[0][1]["id"].startswith(f"true_{GROUP}_P")


def test_without_a_secret_or_with_a_wrong_one_becomes_ciphertext(session, tmp_path):
    o, e = event_of(encrypted_comment("x", parent_id="NO_SECRET"), msg_id="C9")
    assert com.receive(session, GROUP, o, e) is True
    assert session.db.comments_of(GROUP, "NO_SECRET")[0]["type"] == "ciphertext"
    # the secret exists, but the comment was encrypted with another (tampered)
    msg = encrypted_comment("x")
    payload = msg.encCommentMessage.encPayload
    # flip the last byte (XOR always changes it; setting it to a fixed value would
    # leave the payload intact one time in 256)
    msg.encCommentMessage.encPayload = payload[:-1] + bytes([payload[-1] ^ 0xFF])
    o, e = event_of(msg, msg_id="C10")
    com.receive(session, GROUP, o, e)
    row = session.db.comments_of(GROUP, "P")[0]
    assert row["type"] == "ciphertext" and row["body"] == ""
    assert session.events[-2][1]["replyCount"] == 1     # the unreadable one counts


def test_comment_outside_a_group_is_ignored(session):
    o, e = event_of(encrypted_comment("x"))
    assert com.receive(session, "5511@s.whatsapp.net", o, e) is True
    assert session.events == []


def test_deleting_a_comment_lowers_the_count_and_the_preview(session):
    o, e = event_of(encrypted_comment("one"), msg_id="C1")
    com.receive(session, GROUP, o, e)
    o, e = event_of(encrypted_comment("two"), msg_id="C2", ts=1700000100)
    com.receive(session, GROUP, o, e)
    session.events.clear()
    notice = Message(protocolMessage=ProtocolMessage(
        type=ProtocolMessage.REVOKE, key=MessageKey(remoteJID=GROUP, ID="C2")))
    o, e = event_of(notice, msg_id="R1")
    assert com.receive(session, GROUP, o, e) is True
    assert session.db.comments_of(GROUP, "P")[1]["type"] == "revoked"
    assert session.events[0][1]["replyCount"] == 1
    assert session.events[1][1]["preview"]["msgKey"].split("_")[2] == "C1"


def test_only_the_author_deletes_their_own_comment(session):
    o, e = event_of(encrypted_comment("mine"), msg_id="C1")
    com.receive(session, GROUP, o, e)
    session.events.clear()
    notice = Message(protocolMessage=ProtocolMessage(
        type=ProtocolMessage.REVOKE, key=MessageKey(remoteJID=GROUP, ID="C1")))
    o, e = event_of(notice, msg_id="R1", who="5599888877777@s.whatsapp.net")
    assert com.receive(session, GROUP, o, e) is True        # consumed, does not become a message
    assert session.db.comments_of(GROUP, "P")[0]["type"] != "revoked"
    assert session.events == []


def test_deleting_an_ordinary_message_is_not_a_comment(session):
    notice = Message(protocolMessage=ProtocolMessage(
        type=ProtocolMessage.REVOKE, key=MessageKey(remoteJID=GROUP, ID="ANY")))
    o, e = event_of(notice)
    assert com.receive(session, GROUP, o, e) is False
    o, e = event_of(Message(conversation="oi"))
    assert com.receive(session, GROUP, o, e) is False
    assert session.events == []
