"""Raw info queries and MEX queries through WinZapp's neonize build."""
from types import SimpleNamespace as N

import pytest

import raw_queries as rq


def test_nodes_and_jid_attributes():
    assert rq.node("a") == {"tag": "a"}
    assert rq.node("a", {"jid": rq.jid("1@g.us")}, [rq.node("b")]) == {
        "tag": "a", "attrs": {"jid": {"jid": "1@g.us"}}, "content": [{"tag": "b"}]}


def test_children_of_a_node():
    parent = {"tag": "iq", "content": [{"tag": "a"}, {"tag": "b", "attrs": {"x": "1"}}, "x"]}
    assert rq.children(parent) == [{"tag": "a"}, {"tag": "b", "attrs": {"x": "1"}}]
    assert rq.child(parent, "b") == {"tag": "b", "attrs": {"x": "1"}}
    assert rq.child(parent, "c") is None
    assert rq.children({"tag": "iq", "content": {"bytes": "AA=="}}) == []
    assert rq.children(None) == []


def test_an_answer_with_an_error_carries_the_server_code():
    with pytest.raises(rq.QueryError) as caught:
        rq.answer_node({"error": "info query returned status 304", "code": 304,
                        "text": "already requested"})
    assert caught.value.code == 304 and str(caught.value) == "already requested"
    assert rq.answer_node({"node": {"tag": "iq"}}) == {"tag": "iq"}
    with pytest.raises(rq.QueryError):
        rq.answer_node({})


def test_a_mex_answer_needs_its_field_and_no_error():
    assert rq.answer_data({"data": {"x": {"id": 1}}}, "x") == {"id": 1}
    for answer in ({"data": {"x": None}}, {"data": {"x": {}}, "error": "graphql error"},
                   {"error": "timeout"}, None):
        with pytest.raises(rq.QueryError):
            rq.answer_data(answer, "x")


def test_a_client_without_raw_queries_is_refused_before_any_call():
    assert not rq.available(None)
    assert not rq.available(N())
    with pytest.raises(rq.QueryError):
        rq.send_iq(N(), {"namespace": "w:g2", "type": "set"})
