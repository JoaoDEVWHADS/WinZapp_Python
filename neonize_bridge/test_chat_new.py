"""all-new-messages (cursor per session over the store) and send-status."""
import asyncio
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import chat_new as cn
from store import Store


def msg(id_, from_me=False, kind="chat", status=False, t=100):
    return {"id": {"id": id_, "_serialized": "x_" + id_}, "fromMe": from_me, "type": kind,
            "isStatus": status, "t": t, "body": id_}


def test_only_counts_what_other_people_sent():
    assert cn.is_new_received(msg("a"))
    assert not cn.is_new_received(msg("a", from_me=True))
    assert not cn.is_new_received(msg("a", status=True))
    assert not cn.is_new_received(msg("a", kind="revoked"))


def test_new_and_cursor_passes_through_all_the_rows_read():
    rows = [(5, msg("a")), (6, msg("b", from_me=True)), (7, msg("c"))]
    new, cursor = cn.new_and_cursor(rows, 4)
    assert [m["id"]["id"] for m in new] == ["a", "c"] and cursor == 7
    assert cn.new_and_cursor([(8, msg("d", from_me=True))], 7) == ([], 8)
    assert cn.new_and_cursor([], 7) == ([], 7)


def test_status_text():
    assert cn.status_text({"message": "hi"}) == "hi"
    assert cn.status_text({"text": "hi"}) == "hi"
    for bad in ({}, {"message": "  "}, {"message": 3}, [], None):
        with pytest.raises(ValueError):
            cn.status_text(bad)


def test_store_returns_only_what_came_after_the_cursor(tmp_path):
    db = Store(str(tmp_path / "x.db"))
    assert cn.last_rowid(db) == 0
    db.message("a@s.whatsapp.net", msg("m1"))
    start = cn.last_rowid(db)
    db.message("b@s.whatsapp.net", msg("m2"))
    db.message("a@s.whatsapp.net", msg("m3"))
    assert [m["id"]["id"] for _, m in cn.stored_after(db, start)] == ["m2", "m3"]
    assert [m["id"]["id"] for _, m in cn.stored_after(db, start, limit=1)] == ["m2"]
    assert cn.stored_after(db, cn.last_rowid(db)) == []


def server(tmp_path):
    db = Store(str(tmp_path / "x.db"))
    s = N(name="s1", db=db)
    published = []

    async def publish_status(req, build):
        published.append(build("S", "DESTINATION", await req.json()))
        return web.json_response({"status": "success"})

    def text_status(session, destination, body):
        return (session, destination, body)
    app = web.Application()
    cn.register_routes(app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
                       error=lambda m, status=500: web.json_response(
                           {"status": "error", "message": str(m)}, status=status),
                       publish_status=publish_status, text_status=text_status)
    return db, app, published


def test_all_new_messages_first_call_marks_the_start(tmp_path):
    db, app, _ = server(tmp_path)
    db.message("a@s.whatsapp.net", msg("old"))

    async def run():
        async with TestClient(TestServer(app)) as c:
            first = await (await c.get("/api/t/all-new-messages")).json()
            db.message("a@s.whatsapp.net", msg("new1"))
            db.message("a@s.whatsapp.net", msg("mine", from_me=True))
            db.message("b@s.whatsapp.net", msg("new2"))
            second = await (await c.get("/api/t/all-new-messages")).json()
            third = await (await c.get("/api/t/all-new-messages")).json()
            db.message("a@s.whatsapp.net", msg("new3"))
            fourth = await (await c.get("/api/t/all-new-messages")).json()
            return first, second, third, fourth
    first, second, third, fourth = asyncio.run(run())
    assert first["response"] == []
    assert [m["id"]["id"] for m in second["response"]] == ["new1", "new2"]
    assert third["response"] == []
    assert [m["id"]["id"] for m in fourth["response"]] == ["new3"]


def test_send_status_publishes_the_text(tmp_path):
    _, app, published = server(tmp_path)

    async def run():
        async with TestClient(TestServer(app)) as c:
            bad = await c.post("/api/t/send-status", json={"message": ""})
            good = await c.post("/api/t/send-status", json={"message": "hi", "options": {"font": 2}})
            return bad.status, good.status
    bad, good = asyncio.run(run())
    assert (bad, good) == (400, 200)
    assert published == [("S", "DESTINATION", {"text": "hi", "options": {"font": 2}})]
