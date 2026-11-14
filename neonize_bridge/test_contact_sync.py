"""The usync "delta" notice of an added or removed contact."""
from types import SimpleNamespace as N

import contact_sync as cs
import raw_queries


def _usync(query):
    (usync,) = query["content"]
    return usync


def test_the_query_is_the_delta_whatsapp_web_sends():
    query = cs.add_query("5511999998888", sid="s1")
    assert (query["namespace"], query["type"]) == ("usync", "get")
    usync = _usync(query)
    assert usync["attrs"] == {"sid": "s1", "index": "0", "last": "true", "mode": "delta",
                              "context": "interactive"}
    protocols, users = usync["content"]
    assert protocols == {"tag": "query", "content": [
        {"tag": "contact", "attrs": {"addressing_mode": "lid"}}, {"tag": "username"}]}
    assert users == {"tag": "list", "content": [
        {"tag": "user", "content": [{"tag": "contact", "content": "5511999998888"}]}]}


def test_a_delete_names_the_lid_when_known_and_always_the_number():
    user = _usync(cs.delete_query("5511@s.whatsapp.net", "99@lid"))["content"][1]["content"][0]
    assert user["attrs"] == {"jid": {"jid": "99@lid"}, "pn_jid": {"jid": "5511@s.whatsapp.net"}}
    user = _usync(cs.delete_query("5511@s.whatsapp.net"))["content"][1]["content"][0]
    assert user["attrs"] == {"pn_jid": {"jid": "5511@s.whatsapp.net"}}


def test_a_refusal_inside_the_result():
    def answer(contact):
        return {"tag": "iq", "content": [{"tag": "usync", "content": [
            {"tag": "result", "content": [contact]}, {"tag": "list"}]}]}
    assert cs.refusal(answer({"tag": "contact"})) == ""
    assert cs.refusal(answer({"tag": "contact", "content": [
        {"tag": "error", "attrs": {"code": "429", "text": "rate-overlimit"}}]})) == "429"
    assert cs.refusal({"tag": "iq"}) == ""


class Client:
    def __init__(self, answer):
        self.answer, self.queries = answer, []

    def send_iq(self, query):
        self.queries.append(query)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_notify_never_raises(monkeypatch):
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))
    query = cs.add_query("1")
    assert cs.notify(Client({"node": {"tag": "iq"}}), query, "save")
    assert not cs.notify(Client({"error": "no", "code": 500}), query, "save")
    assert not cs.notify(Client(RuntimeError("gone")), query, "save")
    assert not cs.notify(N(), query, "save")          # a build without raw queries
