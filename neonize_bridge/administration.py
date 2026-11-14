"""Server and session routes of the bridge: server identity, documentation,
metrics, list and start sessions, QR and the "reconnect the stream" notice.

The response formats are the ones the WinZapp client reads (identity in
core/wpp_update_health.py and core/local_api_port.py; show-all-sessions in
main_window/wpp_server.py; reconnect-socket-stream in main_window/connection.py)
or, where the client does not use the route, those of WPPConnect Server
(api_patches/src/controller/sessionController.ts).

The pure functions are at the top (tested in test_administration.py);
`register_routes` wires the routes to the server. Nothing here imports neonize.

The other upkeep routes live elsewhere: `collect-page-garbage`, `unhealthy`,
`chatwoot` (maintenance.py), `backup-sessions`, `restore-sessions`
(session_backup.py) and `clear-session-data` (cleanup.py).
"""
import asyncio
import base64
import logging
import os
import re
import time
from types import SimpleNamespace

from aiohttp import web

import session_lifecycle

log = logging.getLogger("bridge")

PROTOCOL = 1
KNOWN_STATUSES = ("CLOSED", "INITIALIZING", "QRCODE", "CONNECTED", "notLogged",
                  session_lifecycle.TERMINAL)
SESSION_FILE = "session.db"


def identity(environment, pid, ppid=0) -> dict:
    """Body of GET /winzapp/identity. The client compares `installation_id` with
    its installation's; the bridge is a shared process that the client does not
    start with those variables, so empty = "not this client's Node".

    `pid` and `ppid` (process and parent process) let the client check that whoever
    listens on the port is the bridge it registered itself in `bridge.pid` before
    sending the secret: the parent is included because, on Windows, what the
    client launches (the venv's python.exe, or the packaged .exe) can be a
    launcher that runs the bridge as a child process. They are only process
    numbers, never secrets."""
    return {"installation_id": environment.get("WINZAPP_INSTALLATION_ID", ""),
            "instance_id": environment.get("WINZAPP_INSTANCE_ID", ""),
            "protocol_version": PROTOCOL, "pid": pid, "ppid": ppid}


def openapi_document(routes, version="1") -> dict:
    """A minimal OpenAPI 3 (paths and methods only) of the registered routes.
    `routes` is a list of (method, path); HEAD, '*' and socket.io stay out."""
    paths = {}
    for method, path in routes:
        method = method.upper()
        if method in ("HEAD", "*", "OPTIONS") or path.startswith("/socket.io"):
            continue
        operation = {"responses": {"200": {"description": "OK"}}}
        names = re.findall(r"\{(\w+)\}", path)
        if names:
            operation["parameters"] = [
                {"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                for n in names]
        paths.setdefault(path, {})[method.lower()] = operation
    return {"openapi": "3.0.0",
            "info": {"title": "WinZapp Neonize bridge", "version": version},
            "paths": dict(sorted(paths.items()))}


def metrics_text(session_statuses, uptime_seconds) -> str:
    """Metrics in Prometheus's text format: sessions by state and how long the
    bridge has been up."""
    counts = {s: 0 for s in KNOWN_STATUSES}
    for status in session_statuses:
        counts[status] = counts.get(status, 0) + 1
    lines = ["# HELP winzapp_bridge_uptime_seconds Seconds since the bridge started.",
             "# TYPE winzapp_bridge_uptime_seconds gauge",
             "winzapp_bridge_uptime_seconds %d" % max(0, int(uptime_seconds)),
             "# HELP winzapp_bridge_sessions Sessions held by the bridge, by state.",
             "# TYPE winzapp_bridge_sessions gauge"]
    for status, count in counts.items():
        lines.append('winzapp_bridge_sessions{status="%s"} %d' % (status, count))
    return "\n".join(lines) + "\n"


def sessions_on_disk(folder) -> list:
    """Names of the accounts that were already paired (folder with session.db), in order."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted(n for n in names
                  if os.path.isfile(os.path.join(folder, n, SESSION_FILE)))


def png_from_data_url(data_url) -> bytes:
    """'data:image/png;base64,XXXX' -> the PNG bytes."""
    return base64.b64decode(data_url.split(",", 1)[1])


def qrcode_response(started, status, urlcode, qr_data_url_of):
    """GET qrcode-session as WPPConnect answers: the PNG when there is a QR;
    otherwise a 200 JSON saying why there is none. ("png", bytes) or ("json", dict)."""
    if urlcode:
        return "png", png_from_data_url(qr_data_url_of(urlcode))
    if not started:
        return "json", {"status": None, "message": "Session not started. Please, use "
                        "the /start-session route, for initialization your session"}
    return "json", {"status": status, "message": "QRCode is not available..."}


def _exit_server():
    """Ends web.run_app's loop the way Ctrl+C does, so the cleanup hooks run."""
    raise web.GracefulExit()


def reconnect_response(status, thread_alive):
    """POST reconnect-socket-stream: (http, body). The client uses this as a
    nudge: 200 says the session is up; an error, three times in a row, makes it
    restart the session (close + start). whatsmeow reconnects on its own, so there
    is nothing to force here: it only says whether there is a live session. Asking
    the socket (`is_connected`) answered 400 during a normal reconnection and
    made the client tear down a session that was going to recover. Like the real
    route, it only refuses when nothing is up (WPPConnect's dead page)."""
    if thread_alive and status not in session_lifecycle.ENDED:
        return 200, {"status": "success", "response": {"ok": True}}
    return 400, {"status": "error", "message": "The WhatsApp session is not active."}


def register_routes(r, *, session, ok, state, folder, mark_active, qr_data_url):
    """Wire the server and session routes to the aiohttp router `r`."""
    started_at = time.monotonic()

    def registered_routes():
        out = []
        for resource in r.resources():
            for route in resource:
                out.append((route.method, resource.canonical))
        return out

    async def winzapp_identity(req):
        return web.json_response(identity(os.environ, os.getpid(), os.getppid()))

    async def api_docs(req):
        return web.json_response(openapi_document(registered_routes()))

    async def metrics(req):
        text = metrics_text([s.status for s in state["sessions"].values()],
                            time.monotonic() - started_at)
        return web.Response(text=text, content_type="text/plain", charset="utf-8",
                            headers={"X-Content-Type-Options": "nosniff"})

    async def show_all_sessions(req):
        # The bridge's secret was already checked by the middleware (authentication.py).
        return ok(response=sorted(state["sessions"]))

    async def start_all(req):
        names = [state["fixed"]] if state["fixed"] else sessions_on_disk(folder)
        for name in names:
            # session() only reads match_info["tok"]: creates (or finds) the account by name.
            s = session(SimpleNamespace(match_info={"tok": name}))
            # begin() may wait for the old thread: outside the aiohttp loop
            await asyncio.get_running_loop().run_in_executor(None, s.begin)
            mark_active(name, True)
        return web.json_response(
            {"status": "success", "message": "Starting all sessions"}, status=201)

    async def shutdown(req):
        """The client is leaving and no other client uses this bridge: close the
        WhatsApp sessions (their sockets and databases) and exit, instead of being
        killed in the middle of a write. The sessions stay in the active list, so
        the next start resumes them."""
        loop = asyncio.get_running_loop()
        for s in list(state["sessions"].values()):
            try:
                await loop.run_in_executor(None, s.stop)
            except Exception:
                log.exception("shutdown: closing a session failed")
        loop.call_later(0.3, state.get("exit") or _exit_server)
        return web.json_response({"status": "success", "message": "Shutting down"})

    async def qrcode_session(req):
        s = session(req)
        kind, payload = qrcode_response(s.thread is not None, s.status, s.urlcode, qr_data_url)
        if kind == "png":
            return web.Response(body=payload, content_type="image/png")
        return web.json_response(payload)

    async def reconnect_socket_stream(req):
        s = session(req)
        alive = bool(s.thread is not None and s.thread.is_alive())
        http, body = reconnect_response(s.status, alive)
        return web.json_response(body, status=http)

    r.add_get("/winzapp/identity", winzapp_identity)
    r.add_get("/api-docs", api_docs)
    r.add_get("/metrics", metrics)
    r.add_get("/api/{secretkey}/show-all-sessions", show_all_sessions)
    r.add_post("/api/{secretkey}/start-all", start_all)
    r.add_post("/api/{secretkey}/shutdown", shutdown)
    r.add_get("/api/{tok}/qrcode-session", qrcode_session)
    r.add_post("/api/{tok}/reconnect-socket-stream", reconnect_socket_stream)
