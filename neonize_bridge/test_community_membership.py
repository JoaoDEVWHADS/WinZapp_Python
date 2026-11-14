"""Joining a community's group, withdrawing the request, deactivating it."""
import asyncio
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import community_membership as cm
import raw_queries


def test_the_join_is_the_query_whatsapp_web_sends():
    assert cm.join_query("1@g.us", "2@g.us") == {
        "namespace": "w:g2", "type": "set", "to": "1@g.us",
        "content": [{"tag": "join_linked_group",
                     "attrs": {"type": "sub_group", "jid": {"jid": "2@g.us"}}}]}


def test_the_cancel_names_me_as_the_participant_without_a_device():
    assert cm.bare_user("123:7@lid") == "123@lid"
    assert cm.cancel_query("2@g.us", "123@lid") == {
        "namespace": "w:g2", "type": "set", "to": "2@g.us",
        "content": [{"tag": "cancel_membership_requests", "content": [
            {"tag": "participant", "attrs": {"jid": {"jid": "123@lid"}}}]}]}


def test_the_deactivation_deletes_the_parent():
    assert cm.deactivate_query("1@g.us")["content"] == [{"tag": "delete_parent"}]


def test_a_join_answered_with_an_approval_request_is_a_request():
    assert cm.join_state({"tag": "iq"}) == "joined"
    assert cm.join_state({"tag": "iq", "content": [
        {"tag": "membership_approval_request"}]}) == "requested"
    assert cm.join_error_state(304) == "request_pending"
    assert cm.join_error_state(500) == ""
    assert cm.join_failure(404) == "group_unavailable"


def test_a_participant_answered_with_an_error_was_not_withdrawn():
    def answer(attrs):
        return {"tag": "iq", "content": [{"tag": "cancel_membership_requests", "content": [
            {"tag": "participant", "attrs": attrs}]}]}
    assert cm.cancel_withdrawn(answer({"jid": "1@lid"}))
    assert not cm.cancel_withdrawn(answer({"jid": "1@lid", "error": "404"}))


def test_only_a_group_jid_is_taken():
    assert cm.group_jid(" 120363-1@g.us ") == "120363-1@g.us"
    assert cm.group_jid("5511@s.whatsapp.net") == ""
    assert cm.group_jid(None) == ""


class Client:
    def __init__(self, answers):
        self.answers = list(answers)
        self.queries = []

    def send_iq(self, query):
        self.queries.append(query)
        return self.answers.pop(0)


@pytest.fixture(autouse=True)
def raw(monkeypatch):
    monkeypatch.setattr(raw_queries, "available",
                        lambda c: c is not None and hasattr(c, "send_iq"))


def run(s, method, path, body=None):
    async def main():
        app = web.Application()
        cm.register_routes(app.router, session=lambda req: s)
        async with TestClient(TestServer(app)) as http:
            resp = await http.request(method, "/api/tok/" + path, json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


def session(*answers, lid="123:7@lid"):
    return N(client=Client(answers), status="CONNECTED", lid=lid, me="5511@s.whatsapp.net")


JOIN = "community-subgroups/1@g.us/2@g.us/join"
CANCEL = "community-subgroups/1@g.us/2@g.us/cancel-request"


@pytest.mark.parametrize("answer,state", [
    ({"node": {"tag": "iq"}}, "joined"),
    ({"node": {"tag": "iq", "content": [{"tag": "membership_approval_request"}]}}, "requested"),
    ({"error": "info query returned status 304", "code": 304}, "request_pending"),
])
def test_join_answers_the_state(answer, state):
    s = session(answer)
    assert run(s, "POST", JOIN) == (200, {"status": "success", "response": {"state": state}})
    assert s.client.queries[0]["to"] == "1@g.us"


def test_a_refused_join_is_never_retried():
    s = session({"error": "boom", "code": 500})
    status, body = run(s, "POST", JOIN)
    assert (status, body["code"], body["retrySafe"]) == (502, "join_failed", False)
    assert len(s.client.queries) == 1


def test_cancel_sends_my_lid_and_answers_cancelled():
    s = session({"node": {"tag": "iq", "content": [{"tag": "cancel_membership_requests"}]}})
    assert run(s, "POST", CANCEL)[1]["response"] == {"state": "cancelled"}
    query = s.client.queries[0]
    assert query["to"] == "2@g.us"
    assert query["content"][0]["content"][0]["attrs"]["jid"] == {"jid": "123@lid"}


def test_without_a_lid_the_cancel_names_my_number():
    s = session({"node": {"tag": "iq"}}, lid="")
    run(s, "POST", CANCEL)
    assert s.client.queries[0]["content"][0]["content"][0]["attrs"]["jid"] == {
        "jid": "5511@s.whatsapp.net"}


def test_invalid_ids_never_reach_whatsapp():
    s = session()
    status, body = run(s, "POST", "community-subgroups/1@g.us/5511@s.whatsapp.net/join")
    assert (status, body["code"]) == (400, "invalid_request") and s.client.queries == []


@pytest.mark.parametrize("answer,expected", [
    ({"node": {"tag": "iq"}}, (200, None)),
    ({"error": "no", "code": 401}, (403, "not_community_owner")),
    ({"error": "no", "code": 404}, (404, "not_community")),
])
def test_deactivate(answer, expected):
    s = session(answer)
    status, body = run(s, "POST", "deactivate-community", {"id": "1@g.us"})
    assert (status, body.get("code")) == expected
    assert s.client.queries[0]["content"] == [{"tag": "delete_parent"}]


def test_without_raw_queries_everything_answers_unavailable():
    s = N(client=N(), status="CONNECTED", lid="", me="")
    for method, path, body in (("POST", JOIN, None), ("POST", CANCEL, None),
                               ("POST", "deactivate-community", {"id": "1@g.us"})):
        assert run(s, method, path, body)[0] == 501
