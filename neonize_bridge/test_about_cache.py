"""profile-status/:phone asks WhatsApp once per person and backs off (about_cache.py)."""
import asyncio
from types import SimpleNamespace as N

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import about_cache as ac
import profile_privacy


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_the_status_code_comes_out_of_whatsmeow_s_error():
    assert ac.failure_code("failed to send usync query: info query returned status 429: "
                           "rate-overlimit") == "429"
    assert ac.failure_code("info query returned 500: internal-server-error") == "500"
    assert ac.failure_code("timed out") == ""
    assert ac.failure_code(None) == ""


def test_an_about_is_kept_and_then_asked_again():
    clock = Clock()
    cache = ac.AboutCache(clock)
    assert cache.lookup("1@s.whatsapp.net") is None
    cache.remember("1@s.whatsapp.net", "Hey")
    assert cache.lookup("1@s.whatsapp.net") == ("Hey", "")
    clock.now += ac.ABOUT_TTL
    assert cache.lookup("1@s.whatsapp.net") is None


def test_a_refusal_is_kept_for_less_and_a_429_pauses_everyone():
    clock = Clock()
    cache = ac.AboutCache(clock)
    cache.failed("1@s.whatsapp.net", "info query returned status 404: not-found")
    assert cache.lookup("1@s.whatsapp.net")[0] is None
    assert not cache.paused()
    cache.failed("2@s.whatsapp.net", "info query returned status 429: rate-overlimit")
    assert cache.paused()
    clock.now += ac.RATE_PAUSE
    assert not cache.paused()
    clock.now += ac.FAILURE_TTL
    assert cache.lookup("1@s.whatsapp.net") is None


def test_the_cache_stays_bounded():
    clock = Clock()
    cache = ac.AboutCache(clock)
    for n in range(ac.MAX_ENTRIES + 10):
        cache.remember(f"{n}@s.whatsapp.net", "")
    assert len(cache._entries) == ac.MAX_ENTRIES
    assert cache.lookup(f"{ac.MAX_ENTRIES + 9}@s.whatsapp.net") == ("", "")


class Client:
    def __init__(self, answers):
        self.answers = list(answers)
        self.asked = 0

    def get_user_info(self, jid):
        self.asked += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {f"{jid.User}@{jid.Server}": N(Status=answer)}


def ask(s, *phones):
    def jid(text):
        user, _, server = text.partition("@")
        return N(User=user, Server=server)

    async def main():
        app = web.Application()
        profile_privacy.register_routes(
            app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
            jid_from_text=jid, jid_text=lambda j: f"{j.User}@{j.Server}")
        out = []
        async with TestClient(TestServer(app)) as http:
            for phone in phones:
                resp = await http.get(f"/api/tok/profile-status/{phone}")
                out.append((resp.status, await resp.json()))
        return out
    return asyncio.run(main())


def session(*answers):
    return N(client=Client(answers), status="CONNECTED")


def test_the_route_asks_whatsapp_once_per_person(monkeypatch):
    monkeypatch.setattr(profile_privacy, "about_of", lambda infos: next(iter(infos.values())).Status)
    s = session("Hey")
    first, second = ask(s, "5511@c.us", "5511@c.us")
    assert first == second == (200, {"status": "success",
                                     "response": {"id": "5511@c.us", "status": "Hey"}})
    assert s.client.asked == 1


def test_after_a_429_the_route_waits_instead_of_asking(monkeypatch):
    monkeypatch.setattr(profile_privacy, "about_of", lambda infos: "")
    s = session(Exception("info query returned status 429: rate-overlimit"))
    (refused, refused_again, paused) = ask(s, "5511@c.us", "5511@c.us", "5522@c.us")
    assert refused[0] == 500 and refused_again[0] == 500
    assert paused == (503, {"status": "error", "code": "rate_limited"})
    assert s.client.asked == 1
