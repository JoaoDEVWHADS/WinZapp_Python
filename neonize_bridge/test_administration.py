"""Server and session routes: the pure functions and the wiring of the routes,
with fake sessions (no neonize)."""
import asyncio
import base64
import os
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import administration

PNG = b"\x89PNG\r\n\x1a\nfake"


def data_url(text):
    return "data:image/png;base64," + base64.b64encode(PNG).decode()


def test_identity_uses_the_environment_and_protocol_1():
    body = administration.identity(
        {"WINZAPP_INSTALLATION_ID": "inst", "WINZAPP_INSTANCE_ID": "node"}, 42, 41)
    assert body == {"installation_id": "inst", "instance_id": "node",
                    "protocol_version": 1, "pid": 42, "ppid": 41}


def test_identity_without_environment_belongs_to_no_installation():
    body = administration.identity({}, 7)
    assert body["installation_id"] == "" and body["protocol_version"] == 1


def test_openapi_lists_paths_and_methods_without_head_or_socketio():
    doc = administration.openapi_document([
        ("GET", "/api/{tok}/contact/{jid}"), ("HEAD", "/api/{tok}/contact/{jid}"),
        ("POST", "/api/{tok}/send-message"), ("*", "/socket.io/"), ("GET", "/healthz")])
    assert doc["openapi"].startswith("3.")
    assert list(doc["paths"]) == ["/api/{tok}/contact/{jid}", "/api/{tok}/send-message",
                                  "/healthz"]
    contact = doc["paths"]["/api/{tok}/contact/{jid}"]
    assert list(contact) == ["get"]
    assert [p["name"] for p in contact["get"]["parameters"]] == ["tok", "jid"]
    assert "parameters" not in doc["paths"]["/healthz"]["get"]


def test_metrics_count_the_sessions_by_state():
    text = administration.metrics_text(["CONNECTED", "CONNECTED", "QRCODE"], 12.9)
    assert 'winzapp_bridge_sessions{status="CONNECTED"} 2' in text
    assert 'winzapp_bridge_sessions{status="QRCODE"} 1' in text
    assert 'winzapp_bridge_sessions{status="CLOSED"} 0' in text
    assert 'winzapp_bridge_sessions{status="terminalFailure"} 0' in text
    assert "winzapp_bridge_uptime_seconds 12\n" in text
    assert text.endswith("\n")


def test_sessions_on_disk_only_the_paired_ones(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "session.db").write_bytes(b"")
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "session.db").write_bytes(b"")
    (tmp_path / "empty").mkdir()
    (tmp_path / "active.json").write_text("[]")
    assert administration.sessions_on_disk(str(tmp_path)) == ["a", "b"]
    assert administration.sessions_on_disk(str(tmp_path / "does-not-exist")) == []


def test_qrcode_with_a_code_returns_the_png():
    assert administration.qrcode_response(True, "QRCODE", "2@abc", data_url) == ("png", PNG)


def test_qrcode_without_a_code_explains_why():
    kind, body = administration.qrcode_response(False, "CLOSED", None, data_url)
    assert kind == "json" and body["status"] is None and "start-session" in body["message"]
    assert administration.qrcode_response(True, "CONNECTED", None, data_url) == (
        "json", {"status": "CONNECTED", "message": "QRCode is not available..."})


def test_reconnect_answers_200_with_the_live_session_even_while_reconnecting():
    """whatsmeow reconnects on its own: a 400 during the drop made the client,
    after three answers, close and restart a session that was going to recover."""
    ok = (200, {"status": "success", "response": {"ok": True}})
    for status in ("CONNECTED", "INITIALIZING", "QRCODE"):
        assert administration.reconnect_response(status, True) == ok
    for status, alive in (("CONNECTED", False), ("CLOSED", True), ("CLOSED", False),
                          ("notLogged", True), ("terminalFailure", True)):
        http, body = administration.reconnect_response(status, alive)
        assert http == 400 and body["status"] == "error"


class FakeThread:
    def __init__(self, alive=True):
        self.alive = alive

    def is_alive(self):
        return self.alive


class FakeSession:
    def __init__(self, name, status="CLOSED", urlcode=None, connected=True, alive=None):
        self.name, self.status, self.urlcode = name, status, urlcode
        self.thread = None if alive is None else FakeThread(alive)
        self.client = N(is_connected=connected)
        self.started = 0

    def begin(self):
        self.started += 1
        self.thread = FakeThread()


def assemble(tmp_path, fixed=""):
    state = {"sessions": {}, "fixed": fixed}
    active = {}

    def session(req):
        name = state["fixed"] or req.match_info["tok"].split(":", 1)[0]
        return state["sessions"].setdefault(name, FakeSession(name))

    app = web.Application()
    administration.register_routes(
        app.router, session=session, ok=lambda **kw: web.json_response(kw), state=state,
        folder=str(tmp_path), mark_active=lambda n, a: active.__setitem__(n, a),
        qr_data_url=data_url)
    return app, state, active


def with_client(app, script):
    async def run():
        async with TestClient(TestServer(app)) as client:
            return await script(client)
    return asyncio.run(run())


def test_identity_docs_and_metrics_routes(tmp_path):
    app, state, _ = assemble(tmp_path)
    state["sessions"]["x"] = FakeSession("x", "CONNECTED")

    async def script(c):
        identity = await (await c.get("/winzapp/identity")).json()
        docs = await (await c.get("/api-docs")).json()
        metrics = await (await c.get("/metrics")).text()
        return identity, docs, metrics

    identity, docs, metrics = with_client(app, script)
    assert identity["protocol_version"] == 1
    # the client checks these two against `bridge.pid` before sending the secret
    assert identity["pid"] == os.getpid() and identity["ppid"] == os.getppid()
    assert "secret" not in identity
    assert "/winzapp/identity" in docs["paths"]
    assert "/api/{tok}/qrcode-session" in docs["paths"]
    assert 'winzapp_bridge_sessions{status="CONNECTED"} 1' in metrics


def test_show_all_sessions_lists_the_names_in_memory(tmp_path):
    app, state, _ = assemble(tmp_path)
    state["sessions"].update({"b": FakeSession("b"), "a": FakeSession("a")})

    async def script(c):
        return await (await c.get("/api/secret/show-all-sessions")).json()

    assert with_client(app, script) == {"response": ["a", "b"]}


def test_start_all_starts_the_accounts_on_disk_and_marks_them_active(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "session.db").write_bytes(b"")
    app, state, active = assemble(tmp_path)

    async def script(c):
        response = await c.post("/api/secret/start-all")
        return response.status, await response.json()

    status, body = with_client(app, script)
    assert status == 201 and body == {"status": "success", "message": "Starting all sessions"}
    assert {n: s.started for n, s in state["sessions"].items()} == {"a": 1, "b": 1}
    assert active == {"a": True, "b": True}


def test_start_all_in_single_account_mode_starts_only_that_one(tmp_path):
    app, state, active = assemble(tmp_path, fixed="test")

    async def script(c):
        return (await c.post("/api/secret/start-all")).status

    assert with_client(app, script) == 201
    assert list(state["sessions"]) == ["test"] and active == {"test": True}


def test_qrcode_session_png_and_json(tmp_path):
    app, state, _ = assemble(tmp_path)
    state["sessions"]["with"] = FakeSession("with", "QRCODE", urlcode="2@abc")
    state["sessions"]["with"].thread = FakeThread()

    async def script(c):
        png = await c.get("/api/with:tok/qrcode-session")
        png_body = await png.read()
        without = await c.get("/api/new:tok/qrcode-session")
        return png.content_type, png_body, await without.json()

    kind, body, without = with_client(app, script)
    assert kind == "image/png" and body == PNG
    assert without["status"] is None


def test_reconnect_socket_stream_looks_at_the_thread_not_the_socket(tmp_path):
    app, state, _ = assemble(tmp_path)
    state["sessions"]["alive"] = FakeSession("alive", "CONNECTED", connected=True, alive=True)
    # socket momentarily down, session standing: whatsmeow reconnects, it is not an error
    state["sessions"]["dropped"] = FakeSession("dropped", "CONNECTED", connected=False, alive=True)

    async def script(c):
        alive = await c.post("/api/alive:tok/reconnect-socket-stream")
        dropped = await c.post("/api/dropped:tok/reconnect-socket-stream")
        stopped = await c.post("/api/stopped:tok/reconnect-socket-stream")
        return alive.status, dropped.status, stopped.status

    assert with_client(app, script) == (200, 200, 400)


def test_shutdown_stops_the_sessions_keeps_them_active_and_asks_the_server_to_exit(tmp_path):
    app, state, active = assemble(tmp_path)
    exits = []
    state["exit"] = lambda: exits.append("exit")
    stopped = []
    for name in ("a", "b"):
        session = FakeSession(name)
        session.stop = lambda n=name: stopped.append(n)
        state["sessions"][name] = session

    async def script(c):
        import asyncio as _asyncio
        response = await c.post("/api/secret/shutdown")
        await _asyncio.sleep(0.5)
        return response.status, await response.json()

    status, body = with_client(app, script)
    assert status == 200 and body["status"] == "success"
    assert sorted(stopped) == ["a", "b"] and exits == ["exit"]
    assert active == {}          # they are not marked inactive: the next start resumes them


def test_the_real_exit_ends_the_server_the_way_ctrl_c_does():
    with pytest.raises(web.GracefulExit):
        administration._exit_server()
