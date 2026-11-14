"""/message-comments/:messageId on the real server (create_app), with a fake
neonize client. No WhatsApp; sending was never proved against a real account."""
import os
from types import SimpleNamespace as N

import pytest
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth
import comments as com
import server
from test_comments import (AUTHOR, ME, MY_LID, GROUP, SECRET, whatsmeow_database,
                           encrypted_comment, event_of)

SERIAL = f"false_{GROUP}_P_{AUTHOR}"


class FakeClient:
    def __init__(self, announcement=True):
        self.announcement = announcement
        self.queries = 0
        self.sent = []
        self.send_failure = None
        self.query_failure = None

    def get_group_info(self, jid):
        self.queries += 1
        if self.query_failure:
            raise self.query_failure
        return N(GroupIsDefaultSub=N(IsDefaultSubGroup=self.announcement))

    def send_message(self, jid, message):
        if self.send_failure:
            raise self.send_failure
        self.sent.append((f"{jid.User}@{jid.Server}", message))
        return N(ID="NEW1")


@pytest.fixture
def sessions(monkeypatch):
    created = []

    class Registered(server.Session):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            created.append(self)
    monkeypatch.setattr(server, "Session", Registered)
    return created


async def _bridge(folder, sessions, connected=True, announcement=True, secrets=True):
    http = TestClient(TestServer(server.create_app(str(folder))))
    await http.start_server()
    secret = (folder / auth.SECRET_FILE).read_text(encoding="utf-8")
    token = f"account:{auth.session_token(secret, 'account')}"
    assert (await http.get(f"/api/{token}/status-session")).status == 200
    s = sessions[0]
    fake = FakeClient(announcement)
    s.client = fake
    s.status = "CONNECTED" if connected else "CLOSED"
    s.me, s.lid = ME, MY_LID
    whatsmeow_database(os.path.join(s.folder, "session.db"),
                       [(GROUP, AUTHOR, "P", SECRET)] if secrets else [], mapping=[])
    return http, f"/api/{token}/message-comments/", s, fake


@pytest.mark.asyncio
async def test_empty_list_and_then_the_received_comments(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        response = await http.get(api + SERIAL)
        assert response.status == 200
        assert await response.json() == {"status": "success", "response": []}
        o, e = event_of(encrypted_comment("ola", who="444555666@lid"), msg_id="C1",
                        who="444555666@lid")
        assert com.receive(s, GROUP, o, e)
        body = await (await http.get(api + SERIAL)).json()
        assert body["response"] == [{
            "id": "C1", "parentMsgId": SERIAL, "chatId": GROUP, "author": "444555666@lid",
            "authorName": "Ana", "fromMe": False, "timestamp": 1700000000,
            "type": "comment", "body": "ola"}]
        # what core/community_comments.py::parse_comments checks
        row = body["response"][0]
        assert row["parentMsgId"] == SERIAL and row["chatId"] == SERIAL.split("_", 2)[1]
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_ordinary_group_and_private_chat_answer_400(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions, announcement=False)
    try:
        r = await http.get(api + SERIAL)
        assert r.status == 400 and (await r.json())["code"] == "not_community_announcement"
        r = await http.get(api + "false_5511999990000@c.us_ID1")
        assert r.status == 400 and (await r.json())["code"] == "not_community_announcement"
        r = await http.post(api + SERIAL, json={"text": "oi"})
        assert r.status == 400 and (await r.json())["code"] == "not_community_announcement"
        assert fake.sent == []
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_whatsapps_answer_about_the_group_is_kept(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        await http.get(api + SERIAL)
        await http.get(api + SERIAL)
        assert fake.queries == 1
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_without_a_connection_or_without_knowing_the_group_is_503_and_a_bad_id_is_400(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions, connected=False)
    try:
        r = await http.get(api + SERIAL)
        assert r.status == 503 and (await r.json())["code"] == "comments_unavailable"
        s.status = "CONNECTED"
        fake.query_failure = RuntimeError("timeout")
        r = await http.get(api + SERIAL)
        assert r.status == 503 and (await r.json())["code"] == "comments_unavailable"
        for bad in ("x", "true_abc", f"maybe_{GROUP}_P"):
            r = await http.get(api + bad)
            assert r.status == 400 and (await r.json())["code"] == "invalid_comment_request"
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_commenting_encrypts_sends_stores_and_announces(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        r = await http.post(api + SERIAL, json={"text": "my comment"})
        assert r.status == 201
        assert await r.json() == {"status": "success", "response": {"messageSendResult": "OK"}}
        (jid, message), = fake.sent
        assert jid == GROUP
        enc = message.encCommentMessage
        key = enc.targetMessageKey
        assert (key.remoteJID, key.participant, key.fromMe, key.ID) == (
            GROUP, AUTHOR, False, "P")
        # whoever reads with the same secret, as the account (LID), gets the text
        opened = com.decrypt_comment(SECRET, "P", [AUTHOR], [MY_LID],
                                     bytes(enc.encIV), bytes(enc.encPayload))
        from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
        assert Message.FromString(opened).conversation == "my comment"
        # the server does not return the own comment to this device: it stays stored
        body = await (await http.get(api + SERIAL)).json()
        row, = body["response"]
        assert (row["id"], row["body"], row["fromMe"]) == ("NEW1", "my comment", True)
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_commenting_without_a_secret_sends_nothing(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions, secrets=False)
    try:
        r = await http.post(api + SERIAL, json={"text": "oi"})
        assert r.status == 503
        assert (await r.json())["code"] == "comment_secret_unavailable"
        assert fake.sent == []
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_failure_when_sending_is_unconfirmed_and_does_not_store(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        fake.send_failure = RuntimeError("timeout")
        r = await http.post(api + SERIAL, json={"text": "oi"})
        assert r.status == 502
        assert (await r.json()) == {"status": "error", "code": "comment_unconfirmed",
                                    "retrySafe": False}
        assert s.db.comments_of(GROUP, "P") == []
    finally:
        await http.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [{}, {"text": "  "}, {"text": 3}, None])
async def test_comment_without_text_is_400(tmp_path, sessions, body):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        r = await http.post(api + SERIAL, json=body)
        assert r.status == 400 and (await r.json())["code"] == "invalid_comment_request"
        assert fake.sent == []
    finally:
        await http.close()


@pytest.mark.asyncio
async def test_commenting_on_my_own_message_uses_the_stored_secret_and_sender(tmp_path, sessions):
    http, api, s, fake = await _bridge(tmp_path, sessions)
    try:
        os.remove(os.path.join(s.folder, "session.db"))
        whatsmeow_database(os.path.join(s.folder, "session.db"),
                           [(GROUP, MY_LID, "MINE", SECRET)], mapping=[])
        r = await http.post(api + f"true_{GROUP}_MINE", json={"text": "and me"})
        assert r.status == 201
        enc = fake.sent[0][1].encCommentMessage
        assert enc.targetMessageKey.fromMe is True
        assert enc.targetMessageKey.participant == MY_LID
        assert com.decrypt_comment(SECRET, "MINE", [MY_LID], [MY_LID],
                                   bytes(enc.encIV), bytes(enc.encPayload))
    finally:
        await http.close()
