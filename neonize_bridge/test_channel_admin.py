"""Editing and deleting a channel through WhatsApp Web's MEX mutations."""
import asyncio
import base64
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import channel_admin as ca
import raw_queries


def jpeg(data):
    return b"JPEG:" + data


def test_only_what_was_sent_is_changed():
    assert ca.edit_updates({"name": " News "}, jpeg) == {"name": "News", "settings": None}
    assert ca.edit_updates({"description": ""}, jpeg) == {"description": "", "settings": None}


def test_a_picture_goes_as_base64_of_a_jpeg_and_null_removes_it():
    picture = base64.b64encode(b"png").decode()
    updates = ca.edit_updates({"picture": "data:image/png;base64," + picture}, jpeg)
    assert base64.b64decode(updates["picture"]) == b"JPEG:png"
    assert ca.edit_updates({"picture": None}, jpeg)["picture"] == ""


@pytest.mark.parametrize("body", [{}, {"name": "  "}, None, {"other": 1}])
def test_nothing_to_change_is_refused(body):
    with pytest.raises(ValueError):
        ca.edit_updates(body, jpeg)


def test_a_picture_that_is_not_base64_is_refused():
    with pytest.raises(ValueError):
        ca.edit_updates({"picture": "not base64!"}, jpeg)


def test_the_edited_channel_is_answered_like_wa_js():
    answer = {"id": "1@newsletter", "state": {"type": "ACTIVE"},
              "thread_metadata": {"name": {"text": "News"}, "description": {"text": "d"},
                                  "invite": "AbC", "creation_time": "1700000000"}}
    assert ca.edited_channel(answer, "1@newsletter") == {
        "idJid": "1@newsletter", "inviteCode": "AbC",
        "inviteLink": "https://whatsapp.com/channel/AbC", "name": "News", "state": "ACTIVE",
        "description": "d", "timestamp": 1700000000}


class Client:
    def __init__(self, answer):
        self.answer = answer
        self.queries = []

    def send_iq(self, query):
        raise AssertionError("a channel is edited through MEX")

    def send_mex(self, query_id, variables):
        self.queries.append((query_id, variables))
        return self.answer


@pytest.fixture(autouse=True)
def raw(monkeypatch):
    monkeypatch.setattr(raw_queries, "available",
                        lambda c: c is not None and hasattr(c, "send_iq"))


def run(s, method, path, body=None):
    async def main():
        app = web.Application()
        ca.register_routes(app.router, session=lambda req: s)
        async with TestClient(TestServer(app)) as http:
            resp = await http.request(method, "/api/tok/" + path, json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


def test_edit_runs_the_update_mutation():
    s = N(client=Client({"data": {ca.UPDATE_FIELD: {"id": "1@newsletter"}}}),
          status="CONNECTED")
    status, body = run(s, "PUT", "newsletter/1", {"name": "News"})
    assert status == 201 and body["idJid"] == "1@newsletter"
    assert s.client.queries == [(ca.UPDATE_QUERY, {
        "newsletter_id": "1@newsletter", "updates": {"name": "News", "settings": None}})]


def test_delete_runs_the_delete_mutation():
    s = N(client=Client({"data": {ca.DELETE_FIELD: {"id": "1@newsletter"}}}),
          status="CONNECTED")
    assert run(s, "DELETE", "newsletter/1@newsletter") == (201, True)
    assert s.client.queries == [(ca.DELETE_QUERY, {"newsletter_id": "1@newsletter"})]


def test_a_graphql_error_is_not_a_success():
    s = N(client=Client({"data": {ca.DELETE_FIELD: None}, "error": "graphql error"}),
          status="CONNECTED")
    status, body = run(s, "DELETE", "newsletter/1")
    assert status == 502 and body["status"] == "error"


def test_only_a_channel_id_is_taken():
    s = N(client=Client({}), status="CONNECTED")
    assert run(s, "DELETE", "newsletter/5511@s.whatsapp.net")[0] == 400
    assert s.client.queries == []
