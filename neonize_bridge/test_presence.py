"""Presence: the memory, the events in the client's format and the answers, all without
neonize (the handlers are tested with a fake `neonize.events`)."""
import asyncio
import sys
import types
from types import SimpleNamespace as N

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import profile_privacy
import presence


def jid(user, server="s.whatsapp.net"):
    return N(User=user, Server=server)


# ------------------------------------------------------------------ pure
def test_key_normalizes_number_c_us_and_device():
    assert presence.key("5511999") == "5511999@c.us"
    assert presence.key("5511999@c.us") == "5511999@c.us"
    assert presence.key("5511999:12@s.whatsapp.net") == "5511999@c.us"
    assert presence.key("99@lid") == "99@lid"
    assert presence.key("") == ""
    assert presence.person_keys("99@lid", "5511999@s.whatsapp.net") == [
        "99@lid", "5511999@c.us"]
    assert presence.person_keys("5511999@s.whatsapp.net", "5511999@c.us") == [
        "5511999@c.us"]


def test_activity_state_tells_text_audio_and_pause_apart():
    assert presence.activity_state(1, 1) == "composing"
    assert presence.activity_state(1, 2) == "recording"
    assert presence.activity_state(2, 2) == "paused"
    assert presence.activity_state(0, 0) == ""


def test_zero_or_negative_seen_is_hidden():
    assert presence.seen_from(1700000000) == 1700000000
    assert presence.seen_from(0) is None
    assert presence.seen_from(-62135596800) is None


def test_online_holds_until_it_expires():
    m = presence.Presences()
    m.set_presence(["5511@c.us"], True, None, 1000)
    assert m.read("5511", 1001) == {"state": "available", "isOnline": True, "lastSeen": None}
    assert m.read("5511", 1000 + presence.ONLINE_TTL) is None
    assert m.read("other", 1001) is None


def test_offline_keeps_the_last_seen_and_the_new_online_erases_it():
    m = presence.Presences()
    m.set_presence(["5511@c.us", "99@lid"], False, 1699999000, 1000)
    assert m.read("99@lid", 1010) == {
        "state": "unavailable", "isOnline": False, "lastSeen": 1699999000}
    m.set_presence(["5511@c.us"], True, None, 1020)
    assert m.read("5511@s.whatsapp.net", 1030)["isOnline"] is True


def test_typing_holds_a_few_seconds_and_pause_clears():
    m = presence.Presences()
    m.set_activity("5511@c.us", "5511@c.us", "composing", 1000)
    assert m.read("5511", 1005)["state"] == "composing"
    assert m.read("5511", 1005)["isOnline"] is True
    assert m.read("5511", 1000 + presence.ACTIVITY_TTL) is None
    m.set_activity("5511@c.us", "5511@c.us", "recording", 2000)
    assert m.read("5511", 2001)["state"] == "recording"
    m.set_activity("5511@c.us", "5511@c.us", "paused", 2002)
    assert m.read("5511", 2003) is None


def test_activity_in_a_group_does_not_become_private_presence():
    m = presence.Presences()
    m.set_activity("120@g.us", "5511@c.us", "composing", 1000)
    assert m.read("5511", 1001) is None


def test_memory_has_a_limit_of_people(monkeypatch):
    monkeypatch.setattr(presence, "MAX_PEOPLE", 3)
    m = presence.Presences()
    for i in range(5):
        m.set_presence([f"{i}@c.us"], True, None, 1000 + i)
    assert m.read("0", 1010) is None and m.read("1", 1010) is None
    assert m.read("4", 1010) is not None


def test_presence_event_in_the_clients_format():
    on = presence.presence_event("5511@c.us", True, None, 1700000000.9)
    assert on == {"id": "5511@c.us", "state": "available", "isOnline": True,
                  "t": 1700000000, "isGroup": False, "isUser": True,
                  "snapshotStatus": "ready"}
    off = presence.presence_event("5511@c.us", False, 1699999000, 1700000000)
    assert off["state"] == "unavailable" and off["lastSeen"] == 1699999000
    assert off["snapshotStatus"] == "ready"
    hidden = presence.presence_event("5511@c.us", False, None, 1700000000)
    assert "lastSeen" not in hidden and "snapshotStatus" not in hidden


def test_activity_event_private_and_group():
    p = presence.activity_event("5511@c.us", "5511@c.us", "recording", 5, False)
    assert p == {"id": "5511@c.us", "state": "recording", "t": 5,
                 "isGroup": False, "isUser": True, "isOnline": True}
    pause = presence.activity_event("5511@c.us", "5511@c.us", "paused", 5, False)
    assert "isOnline" not in pause
    g = presence.activity_event("120@g.us", "5511@c.us", "composing", 5, True)
    assert g["isGroup"] is True and g["id"] == "120@g.us"
    assert g["participants"] == [{"id": "5511@c.us", "state": "composing", "shortName": ""}]


def test_answers_the_client_accepts():
    no_data = presence.last_seen_response(None)
    assert no_data == {"response": False, "presence": {"status": "unsupported"}}
    hidden = presence.last_seen_response(
        {"state": "unavailable", "isOnline": False, "lastSeen": None})
    assert hidden["presence"] == {"status": "unsupported"}
    offline = presence.last_seen_response(
        {"state": "unavailable", "isOnline": False, "lastSeen": 1699999000})
    assert offline == {"response": 1699999000, "presence": {
        "status": "ready", "isOnline": False, "lastSeen": 1699999000,
        "state": "unavailable"}}
    online = presence.last_seen_response(
        {"state": "composing", "isOnline": True, "lastSeen": None})
    assert online["presence"] == {"status": "ready", "isOnline": True,
                                  "lastSeen": None, "state": "composing"}
    assert presence.online_response(None) == {
        "response": False, "presence": {"status": "unsupported"}}
    assert presence.online_response(
        {"state": "available", "isOnline": True, "lastSeen": None}) == {"response": True}


# ------------------------------------------------- handlers, without neonize
class _Cli:
    def __init__(self, pairs=None):
        self.handlers = {}
        self.pairs = pairs or {}

    def event(self, kind):
        def bind(f):
            self.handlers[kind] = f
            return f
        return bind

    def get_pn_from_lid(self, j):
        return self.pairs[f"{j.User}@{j.Server}"]

    def get_lid_from_pn(self, j):
        return self.pairs[f"{j.User}@{j.Server}"]


class _Session:
    name = "s1"

    def __init__(self):
        self.sent = []

    def emit(self, event, data):
        self.sent.append((event, data))


def _bind(monkeypatch, pairs=None):
    events = types.ModuleType("neonize.events")
    events.PresenceEv = type("PresenceEv", (), {})
    events.ChatPresenceEv = type("ChatPresenceEv", (), {})
    package = types.ModuleType("neonize")
    package.events = events
    monkeypatch.setitem(sys.modules, "neonize", package)
    monkeypatch.setitem(sys.modules, "neonize.events", events)
    cli, s = _Cli(pairs), _Session()
    presence.register_events(cli, s)
    return cli, s, events


def test_presence_event_stores_and_emits(monkeypatch):
    cli, s, ev = _bind(monkeypatch, {"99@lid": N(User="5511", Server="s.whatsapp.net")})
    cli.handlers[ev.PresenceEv](
        cli, N(From=jid("99", "lid"), Unavailable=False, LastSeen=0))
    name, data = s.sent[0]
    assert name == "onpresencechanged"
    assert data["session"] == "s1" and data["id"] == "5511@c.us"
    assert data["isOnline"] is True
    # the memory answers by number and by LID
    import time
    assert s.presences.read("5511", time.time())["isOnline"] is True
    assert s.presences.read("99@lid", time.time())["isOnline"] is True


def test_typing_event_private_and_in_a_group(monkeypatch):
    cli, s, ev = _bind(monkeypatch)
    cli.get_lid_from_pn = lambda j: (_ for _ in ()).throw(RuntimeError("no pair"))
    source = N(IsFromMe=False, IsGroup=False, Chat=jid("5511"), Sender=jid("5511"))
    cli.handlers[ev.ChatPresenceEv](cli, N(MessageSource=source, State=1, Media=2))
    assert s.sent[0][1]["state"] == "recording" and s.sent[0][1]["id"] == "5511@c.us"
    group = N(IsFromMe=False, IsGroup=True, Chat=jid("120", "g.us"), Sender=jid("5522"))
    cli.handlers[ev.ChatPresenceEv](cli, N(MessageSource=group, State=1, Media=1))
    data = s.sent[1][1]
    assert data["isGroup"] and data["id"] == "120@g.us"
    assert data["participants"][0] == {"id": "5522@c.us", "state": "composing", "shortName": ""}
    mine = N(IsFromMe=True, IsGroup=False, Chat=jid("5511"), Sender=jid("5511"))
    cli.handlers[ev.ChatPresenceEv](cli, N(MessageSource=mine, State=1, Media=1))
    assert len(s.sent) == 2


# ------------------------------------------------------------ routes
def _app(memory):
    app = web.Application()
    session = N(client=None, status="CLOSED", me="", presences=memory)
    ok = lambda **kw: web.json_response(kw)
    profile_privacy.register_routes(app.router, session=lambda req: session, ok=ok,
                                    jid_from_text=lambda t: t, jid_text=lambda j: str(j))
    presence.register_routes(app.router, session=lambda req: session, ok=ok)
    return app


def _get(memory, path):
    async def scenario():
        async with TestClient(TestServer(_app(memory))) as c:
            r = await c.get(path)
            return r.status, await r.json()
    return asyncio.run(scenario())


def test_routes_answer_from_memory(monkeypatch):
    import time
    memory = presence.Presences()
    memory.set_presence(["5511@c.us"], False, 1699999000, time.time())
    memory.set_presence(["5522@c.us"], True, None, time.time())
    status, body = _get(memory, "/api/tok/last-seen/5511@c.us")
    assert status == 200 and body["presence"]["lastSeen"] == 1699999000
    assert body["presence"]["status"] == "ready"
    _, body = _get(memory, "/api/tok/last-seen/5999")
    assert body["presence"] == {"status": "unsupported"}
    assert _get(memory, "/api/tok/chat-is-online/5522")[1]["response"] is True
    assert _get(memory, "/api/tok/chat-is-online/5511")[1]["response"] is False
    assert _get(memory, "/api/tok/chat-is-online/120-4@g.us")[0] == 400


def test_without_memory_the_routes_say_unsupported():
    assert _get(None, "/api/tok/last-seen/5511")[1]["presence"] == {"status": "unsupported"}
    assert _get(None, "/api/tok/chat-is-online/5511")[1]["response"] is False


def test_read_finds_the_person_stored_with_or_without_the_ninth_digit():
    memory = presence.Presences()
    memory.set_presence(["551199990000@c.us"], True, None, 1000)       # without the 9th digit
    assert memory.read("5511999990000@c.us", 1001)["isOnline"] is True
    memory.set_activity("5511988880000@c.us", "5511988880000@c.us", "composing", 1000)
    assert memory.read("551188880000", 1001)["state"] == "composing"       # with the 9th digit stored
    assert memory.read("5511777770000", 1001) is None


def test_equivalent_keys_do_not_invent_a_form_for_lid_or_landline():
    assert presence.equivalent_keys("5511999990000@c.us") == [
        "5511999990000@c.us", "551199990000@c.us"]
    assert presence.equivalent_keys("5511999990000@lid") == ["5511999990000@lid"]
    assert presence.equivalent_keys("551133334444@c.us") == ["551133334444@c.us"]
    assert presence.equivalent_keys("") == []
