"""Disappearing messages: the timer conversion (pure functions) and the route
with a fake client."""
import asyncio
import time
from datetime import timedelta
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import ephemeral_messages as em

DAY, WEEK, QUARTER = 86400, 7 * 86400, 90 * 86400


def test_boolean_turns_on_for_seven_days_and_off():
    assert em.timer_seconds(True) == WEEK
    assert em.timer_seconds(False) == 0
    assert em.timer_seconds(None) == WEEK
    assert em.timer_seconds("") == WEEK
    assert em.timer_seconds("false") == 0
    assert em.timer_seconds("True") == WEEK


def test_valid_seconds_as_number_or_text():
    for seconds in (0, DAY, WEEK, QUARTER):
        assert em.timer_seconds(seconds) == seconds
        assert em.timer_seconds(str(seconds)) == seconds
    assert em.timer_seconds(float(DAY)) == DAY


def test_duration_wins_over_value():
    assert em.timer_seconds(True, DAY) == DAY
    assert em.timer_seconds(False, QUARTER) == QUARTER
    assert em.timer_seconds(True, "") == WEEK


def test_duration_outside_whatsapps_options_is_refused():
    for bad in (1, 3600, -1, 1.5, "abc", [], {}):
        with pytest.raises(ValueError):
            em.timer_seconds(bad)


def test_timer_goes_in_nanoseconds():
    timer, _ = em.timer_arguments(DAY, 1_700_000_000.0)
    assert timer == 86_400_000_000_000
    assert em.timer_arguments(0, 1.0)[0] == 0
    assert isinstance(timer, int)


def test_timestamp_becomes_now_in_milliseconds_by_neonizes_arithmetic():
    # the arithmetic of neonize's wrapper: int(time.time() + setting_ts.total_seconds() * 1000)
    now = time.time()
    _, delay = em.timer_arguments(DAY, now)
    assert isinstance(delay, timedelta)
    stamp = int(now + delay.total_seconds() * 1000)
    assert abs(stamp - int(now * 1000)) <= 1


def test_apply_timer_calls_neonize_with_an_integer():
    calls = []
    client = N(set_disappearing_timer=lambda *a: calls.append(a))
    em.apply_timer(client, "JID", WEEK, 1_700_000_000.0)
    jid, timer, stamp = calls[0]
    assert jid == "JID" and timer == WEEK * 10 ** 9 and type(timer) is int
    assert isinstance(stamp, timedelta)


def test_ephemeral_property():
    assert em.is_ephemeral_property(" Ephemeral ")
    assert not em.is_ephemeral_property("announce")
    assert not em.is_ephemeral_property(None)


def ask(body, connected=True, failure=False):
    calls = []

    def set_disappearing_timer(jid, timer, stamp):
        if failure:
            raise RuntimeError("refused")
        calls.append((jid, timer))
    s = N(client=N(set_disappearing_timer=set_disappearing_timer) if connected else None,
          status="CONNECTED" if connected else "CLOSED")

    async def in_thread(function, *args):
        return function(*args)

    async def run():
        app = web.Application()
        em.register_routes(
            app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
            error=lambda m, status=500: web.json_response(
                {"status": "error", "message": str(m)}, status=status),
            destination_of=lambda text: text, in_thread=in_thread, now=lambda: 1.0)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/api/t/temporary-messages", json=body)
            return response.status, await response.json()
    status, answer = asyncio.run(run())
    return status, answer, calls


def test_route_turns_on_in_a_chat_and_in_a_group():
    status, body, calls = ask({"phone": "5511", "isGroup": False, "value": True})
    assert status == 200 and body["response"] == {"duration": WEEK}
    assert calls == [("5511@s.whatsapp.net", WEEK * 10 ** 9)]
    _, _, calls = ask({"phone": ["123-456"], "isGroup": True, "value": False})
    assert calls == [("123-456@g.us", 0)]


def test_route_refuses_a_bad_request_and_no_connection():
    assert ask({"value": True})[0] == 400
    assert ask({"phone": "5511", "value": 5})[0] == 400
    status, body, calls = ask({"phone": "5511"}, connected=False)
    assert status == 404 and body["status"] == "Disconnected" and not calls


def test_route_returns_500_when_whatsapp_refuses():
    assert ask({"phone": "5511"}, failure=True)[0] == 500


def ask_property(body, failure=False):
    """group-property of groups_extra, which delegates `ephemeral` to this module."""
    import groups_extra
    calls = []

    def set_disappearing_timer(jid, timer, stamp):
        if failure:
            raise RuntimeError("refused")
        calls.append((jid, timer))
    s = N(client=N(set_disappearing_timer=set_disappearing_timer), status="CONNECTED")

    async def run():
        app = web.Application()
        groups_extra.register_routes(
            app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
            jid_from_text=lambda text: text, jid_text=None, qr_data_url=None)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/api/t/group-property", json=body)
            return response.status, await response.json()
    status, answer = asyncio.run(run())
    return status, answer, calls


def test_group_property_ephemeral_uses_the_same_timer():
    status, _, calls = ask_property(
        {"groupId": "123-456", "property": "ephemeral", "value": DAY})
    assert status == 200 and calls == [("123-456@g.us", DAY * 10 ** 9)]
    _, _, calls = ask_property(
        {"groupId": "123-456@g.us", "property": "ephemeral", "value": False})
    assert calls == [("123-456@g.us", 0)]


def test_group_property_ephemeral_refuses_a_bad_value_and_group():
    assert ask_property({"groupId": "1", "property": "ephemeral", "value": 99})[0] == 400
    assert ask_property({"property": "ephemeral", "value": True})[0] == 400
    assert ask_property({"groupId": "1", "property": "ephemeral"}, failure=True)[0] == 500


def test_group_property_of_another_property_is_still_refused():
    status, _, _ = ask_property({"groupId": "1", "property": "nope", "value": True})
    assert status == 400
