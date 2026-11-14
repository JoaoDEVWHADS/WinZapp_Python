"""Each socket only receives the events of its own session (room = the token's name),
with a real socketio.AsyncServer and AsyncClient, without WhatsApp."""
import asyncio

import pytest
import socketio
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth
import server


@pytest.fixture
def sessions(monkeypatch):
    """The Sessions the server creates (their __init__ does not use neonize)."""
    created = []

    class Registered(server.Session):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            created.append(self)
    monkeypatch.setattr(server, "Session", Registered)
    return created


async def _bridge(folder, fixed=""):
    client = TestClient(TestServer(server.create_app(str(folder), fixed)))
    await client.start_server()
    secret = (folder / auth.SECRET_FILE).read_text(encoding="utf-8")
    return client, secret


async def _socket(client, token, stated_session=None):
    """A Socket.IO client like WinZapp's: auth with token and session."""
    received = []
    sio = socketio.AsyncClient()
    sio.on("status-find", lambda data: received.append(data))
    await sio.connect(str(client.make_url("/")), socketio_path="socket.io",
                      auth={"token": token, "session": stated_session or token.split(":")[0]},
                      headers={"apikey": token})
    return sio, received


async def _wait(condition, timeout=5):
    for _ in range(int(timeout / 0.02)):
        if condition():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("the event did not arrive")


def _token(secret, name):
    return f"{name}:{auth.session_token(secret, name)}"


@pytest.mark.asyncio
async def test_session_event_only_reaches_its_own_socket(tmp_path, sessions):
    client, secret = await _bridge(tmp_path)
    sio_a = sio_b = None
    try:
        tok_a, tok_b = _token(secret, "a"), _token(secret, "b")
        # b says in the auth that it is session "a": the room comes from the token, not from what the client writes
        sio_a, received_a = await _socket(client, tok_a)
        sio_b, received_b = await _socket(client, tok_b, stated_session="a")
        for tok in (tok_a, tok_b):
            assert (await client.get(f"/api/{tok}/status-session")).status == 200
        by_name = {s.name: s for s in sessions}

        by_name["a"].emit("status-find", {"session": "a", "status": "inChat"})
        by_name["b"].emit("status-find", {"session": "b", "status": "notLogged"})
        await _wait(lambda: received_a and received_b)
        await asyncio.sleep(0.1)    # time for a wrongful send to show up

        assert [d["session"] for d in received_a] == ["a"]
        assert [d["session"] for d in received_b] == ["b"]
        assert received_a[0] == {"session": "a", "status": "inChat"}   # payload intact
    finally:
        for sio in (sio_a, sio_b):
            if sio is not None:
                await sio.disconnect()
        await client.close()


@pytest.mark.asyncio
async def test_single_session_the_event_reaches_the_socket_of_the_tokens_name(tmp_path, sessions):
    """With --single-session the Session is born with the fixed name and takes on the token's."""
    client, secret = await _bridge(tmp_path, fixed="fixed")
    sio = None
    try:
        tok = _token(secret, "account1")
        sio, received = await _socket(client, tok)
        assert (await client.get(f"/api/{tok}/status-session")).status == 200
        assert [s.name for s in sessions] == ["account1"]

        sessions[0].emit("status-find", {"session": sessions[0].name, "status": "inChat"})
        await _wait(lambda: received)
        assert received == [{"session": "account1", "status": "inChat"}]
    finally:
        if sio is not None:
            await sio.disconnect()
        await client.close()


@pytest.mark.asyncio
async def test_socket_without_a_valid_credential_is_refused(tmp_path, sessions):
    client, _ = await _bridge(tmp_path)
    try:
        sio = socketio.AsyncClient()
        with pytest.raises(socketio.exceptions.ConnectionError):
            await sio.connect(str(client.make_url("/")), socketio_path="socket.io",
                              auth={"token": "a:wrong", "session": "a"})
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("auth", [
    ["token"], "token", 7, {"token": ["a:b"]}, {"token": 7}, {"token": "é:éé"},
    {"token": ""}, {}, None])
async def test_malformed_credential_refuses_the_connection_without_bringing_anything_down(tmp_path, sessions, auth):
    """Finding M2: an exception in connect left the socket connected without a credential."""
    client, secret = await _bridge(tmp_path)
    sio = socketio.AsyncClient()
    try:
        with pytest.raises(socketio.exceptions.ConnectionError):
            await sio.connect(str(client.make_url("/")), socketio_path="socket.io",
                              auth=auth, headers={"apikey": "éé"})
        assert not sio.connected
        await asyncio.sleep(0.1)
        sio_server = client.server.app["sio"]
        assert list(sio_server.manager.get_participants("/", None)) == []
    finally:
        await sio.disconnect()
        await client.close()


def test_the_server_does_not_turn_on_the_access_log():
    """Finding H1: the access log records every URL, and the secret and the phones go in it."""
    assert server.SERVER_OPTIONS["access_log"] is None
    assert server.SERVER_OPTIONS["host"] == "127.0.0.1"


@pytest.mark.asyncio
async def test_no_log_carries_the_secret_nor_the_phone_of_a_request(tmp_path, caplog):
    import logging
    import aiohttp
    from aiohttp import web
    app = server.create_app(str(tmp_path))
    runner = web.AppRunner(app, access_log=server.SERVER_OPTIONS["access_log"])
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    secret = (tmp_path / auth.SECRET_FILE).read_text(encoding="utf-8")
    try:
        with caplog.at_level(logging.DEBUG):
            async with aiohttp.ClientSession() as http:
                base = f"http://127.0.0.1:{port}"
                await http.post(f"{base}/api/account1/{secret}/generate-token")
                token = f"account1:{auth.session_token(secret, 'account1')}"
                await http.get(f"{base}/api/{token}/get-messages/5511999998888@c.us?count=2")
    finally:
        await runner.cleanup()
    text = caplog.text
    assert secret not in text and auth.session_token(secret, "account1") not in text
    assert "5511999998888" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("packet", [
    '40["x"]', '40"x"', '407', '40{"token":["a"]}', '40{"token":7}', '40{"token":"é:éé"}'])
async def test_raw_connect_with_a_malformed_credential_leaves_no_registered_socket(
        tmp_path, sessions, packet):
    """Finding M2 as the review reproduced it: a polling handshake and a malformed
    CONNECT packet. The socket cannot stay connected to the server."""
    import json
    client, secret = await _bridge(tmp_path)
    try:
        response = await client.get("/socket.io/?EIO=4&transport=polling")
        sid = json.loads((await response.text())[1:])["sid"]
        await client.post(f"/socket.io/?EIO=4&transport=polling&sid={sid}",
                          data=packet.encode("utf-8"))
        await asyncio.sleep(0.3)
        sio_server = client.server.app["sio"]
        assert list(sio_server.manager.get_participants("/", None)) == []
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_socket_that_leaves_is_logged_with_the_reason(tmp_path, sessions, caplog):
    """A client that keeps resynchronizing is diagnosed from why its socket dropped."""
    import logging
    client, secret = await _bridge(tmp_path)
    try:
        with caplog.at_level(logging.INFO, logger="bridge"):
            sio, _received = await _socket(client, _token(secret, "account1"))
            await sio.disconnect()
            await _wait(lambda: any("socket disconnected" in r.getMessage()
                                    for r in caplog.records))
        line = next(r.getMessage() for r in caplog.records
                    if "socket disconnected" in r.getMessage())
        assert line != "socket disconnected (no reason given)"
    finally:
        await client.close()
