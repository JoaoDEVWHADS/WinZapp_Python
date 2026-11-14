"""Upkeep routes: unhealthy, collect-page-garbage, profile/:phone, chatwoot."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace as N

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import maintenance


def test_collect_reports_memory_and_time():
    values = iter([100, 60])
    clock = iter([1.0, 1.25])
    assert maintenance.collect(lambda: next(values), lambda: next(clock)) == {
        "before": 100, "after": 60, "tookMs": 250.0}


def test_the_process_memory_is_a_number_or_none():
    memory = maintenance.process_memory()
    assert memory is None or memory > 0


def test_the_client_reads_a_collection():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
    try:
        from core import page_heap
    finally:
        sys.path.pop(0)
    assert "MB" in page_heap.describe({"before": 2 ** 21, "after": 2 ** 20, "tookMs": 3}, 0)


def webhook(**extra):
    body = {"event": "message_created", "message_type": "outgoing",
            "conversation": {"meta": {"sender": {"phone_number": "+55 11 99999-0000"}},
                             "messages": [{"content": "Olá", "attachments": []}]}}
    body.update(extra)
    return body


def test_chatwoot_plans():
    assert maintenance.chatwoot_plan(webhook()) == {"phone": "5511999990000", "text": "Olá",
                                                    "attachments": []}
    assert maintenance.chatwoot_plan(webhook(event="conversation_resolved")) == {"drop": True}
    assert maintenance.chatwoot_plan(webhook(private=True)) == {"drop": True}
    assert maintenance.chatwoot_plan(webhook(message_type="incoming")) == {"drop": True}
    with_file = webhook(message={"content": "foto", "attachments": [
        {"data_url": "https://chat/rails/x.jpg", "file_type": "image"},
        {"data_url": "file:///etc/passwd", "file_type": "file"}]})
    assert maintenance.chatwoot_plan(with_file)["attachments"] == [
        {"url": "https://chat/rails/x.jpg", "kind": "image"}]


class Client:
    def __init__(self):
        self.sent = []

    def is_on_whatsapp(self, *numbers):
        return [N(IsIn=True, JID=N(User="5511999990000", Server="s.whatsapp.net"),
                  HasField=lambda field: False)]

    def send_message(self, destination, message):
        self.sent.append((destination, message))
        return N(ID="M1")


def run(s, method, path, body=None, raw_path=False):
    async def main():
        app = web.Application()
        maintenance.register_routes(app.router, session=lambda req: s,
                                    ok=lambda **kw: web.json_response(kw),
                                    destination_of=lambda p: p,
                                    store_sent=lambda s, d, r: web.json_response({}),
                                    send_media=None)
        async with TestClient(TestServer(app)) as http:
            resp = await http.request(method, path if raw_path else "/api/tok/" + path, json=body)
            text = await resp.text()
            return resp.status, text
    return asyncio.run(main())


def session():
    return N(client=Client(), status="CONNECTED")


def test_unhealthy_answers_503_and_the_bridge_goes_on():
    assert run(session(), "GET", "/unhealthy", raw_path=True)[0] == 503


def test_collect_page_garbage_route():
    status, text = run(session(), "POST", "collect-page-garbage", {})
    assert status == 200 and '"tookMs"' in text


def test_profile_is_the_number_check():
    status, text = run(session(), "GET", "profile/5511999990000")
    assert status == 200 and '"numberExists": true' in text


def test_chatwoot_sends_the_text():
    s = session()
    status, _ = run(s, "POST", "chatwoot", webhook())
    assert status == 200
    ((destination, message),) = s.client.sent
    assert destination == "5511999990000" and message.conversation == "Olá"
    run(s, "POST", "chatwoot", webhook(event="conversation_status_changed"))
    assert len(s.client.sent) == 1
