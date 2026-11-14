"""Who can talk to the bridge's local port.

The bridge keeps the user's WhatsApp session and listens on 127.0.0.1. That is
not enough: a page open in the browser can also reach 127.0.0.1. So:

* the bridge has a secret of its own, generated the first time and kept in
  `<folder>/secret`; the client reads the same file (it plays the role of
  WPPConnect's "secret key");
* `generate-token` only answers to whoever knows the secret, and a session's
  token is an HMAC of the session name with that secret;
* every `/api/<token>/...` route checks that token; the administration routes
  (`show-all-sessions`, `start-all`, `backup-sessions`, `restore-sessions`,
  `clear-session-data`) ask for the secret itself in place of the token;
* the Host header has to be the machine's own (against DNS rebinding).

Pure functions, tested in test_authentication.py. Another site's page does not
know the secret nor can it read the file, and the browser does not let it send
the Authorization header without a preflight that the bridge does not answer;
that is why the bridge can accept, like WPPConnect, `Authorization: Bearer` in
place of the `:hash` of the path.
"""
import hashlib
import hmac
import os
import secrets
import time

from aiohttp import web

SECRET_FILE = "secret"
# Ceiling of a body read at once (JSON: voice and status in base64, text
# fields). 100 MiB of media in base64 come to ~134 MiB; there is margin. The
# send-file does not count: it reads the multipart in blocks straight to disk,
# and that is where the 2 GiB (document) and 1 GiB (media) the client accepts go.
MAX_BODY_SIZE = 160 * 1024**2
ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]")
# Route templates (the resource's `canonical` that the router chose), never the
# raw path: the router matches the still-encoded path and only then decodes the
# values, so `/api/%2F/x` would be read here as `/api///x`.
OPEN_ROUTES = ("/healthz", "/health", "/winzapp/identity", "/api-docs", "/metrics",
               "/unhealthy",                      # 503 only: it never ends the bridge
               "/socket.io/")                     # /socket.io/ is checked in `connect`
TOKEN_TEMPLATE = "/api/{session}/{key}/generate-token"
ADMINISTRATION_TEMPLATES = ("/api/{secretkey}/show-all-sessions",
                            "/api/{secretkey}/start-all",
                            "/api/{secretkey}/shutdown",
                            "/api/{secretkey}/backup-sessions",
                            "/api/{secretkey}/restore-sessions",
                            "/api/{session}/{secretkey}/clear-session-data")
SESSION_PREFIX = "/api/{tok}/"


def _read_secret(path) -> str:
    try:
        with open(path, encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return ""


def load_secret(folder) -> str:
    """The bridge's secret: the one in the file, or a new one (only the owner can read it).

    Two bridges started together (two accounts opening at the same time) cannot
    write different secrets: the file is created exclusively and whoever loses
    the race reads what the winner wrote."""
    path = os.path.join(folder, SECRET_FILE)
    secret = _read_secret(path)
    if secret:
        return secret
    os.makedirs(folder, exist_ok=True)
    for _ in range(40):
        new = secrets.token_hex(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:             # another just created it: wait for it to write
            time.sleep(0.05)
            secret = _read_secret(path)
            if secret:
                return secret
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(new)
        return new
    # an empty file that never got completed: redo it
    new = secrets.token_hex(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(new)
    return new


def session_token(secret: str, name: str) -> str:
    return hmac.new(secret.encode(), name.encode(), hashlib.sha256).hexdigest()


def _equal(a, b) -> bool:
    """Constant-time equality; on bytes, so it does not fail with non-ASCII."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def valid_secret(secret: str, candidate) -> bool:
    return bool(candidate) and isinstance(candidate, str) and _equal(candidate, secret)


def valid_credential(secret: str, token) -> bool:
    """`token` is `<session>:<hash>`; it is valid if the hash is this session's."""
    if not isinstance(token, str):
        return False
    name, separator, received_hash = token.partition(":")
    if not (name and separator and received_hash):
        return False
    return _equal(received_hash, session_token(secret, name))


def credential_from_header(secret: str, name, authorization) -> bool:
    """The `Authorization: Bearer X` that WPPConnect Server accepts (auth.ts) when
    the path carries only the session NAME, without `:hash`: valid if X is the
    bridge's secret or this session's hash. The whole header equal to the secret
    is valid too. The WinZapp client calls it this way in several places
    (check_connection_status, closing the session before pairing, ...). A name
    that already carries `:` never gets here."""
    if not isinstance(authorization, str) or not isinstance(name, str) or not name \
            or ":" in name:
        return False
    header = authorization.strip()
    if valid_secret(secret, header):
        return True
    _, _, value = header.partition(" ")
    value = value.strip()
    if not value:
        return False
    return valid_secret(secret, value) or valid_credential(secret, f"{name}:{value}")


def credential_name(token) -> str:
    """The session name in `<session>:<hash>`; only makes sense after
    `valid_credential`."""
    return str(token or "").partition(":")[0]


def host_allowed(header) -> bool:
    """Host of whoever talks to the machine itself, with or without a port."""
    host = str(header or "").strip().lower()
    if host.startswith("["):                        # [::1]:6300
        host = host.split("]", 1)[0] + "]"
    else:
        host = host.rsplit(":", 1)[0] if ":" in host else host
    return host in ALLOWED_HOSTS


def requirement(template: str, parts) -> tuple:
    """What the route asks for, from the template of the route the router chose
    and the values it already decoded (`match_info`): ("open", ""),
    ("key", <secret>), ("session", <token>) or ("denied", "") for any route
    that is not known (denies by default)."""
    if template in OPEN_ROUTES:
        return ("open", "")
    if template == TOKEN_TEMPLATE:
        return ("key", parts.get("key", ""))
    if template in ADMINISTRATION_TEMPLATES:
        return ("key", parts.get("secretkey", ""))
    if template.startswith(SESSION_PREFIX):
        return ("session", parts.get("tok", ""))
    return ("denied", "")


def create_middleware(secret: str):
    @web.middleware
    async def check(request, handler):
        if not host_allowed(request.headers.get("Host")):
            return web.json_response(
                {"status": "error", "message": "forbidden host"}, status=403)
        resource = request.match_info.route.resource
        if resource is None:                # no route: the router answers 404/405
            return await handler(request)
        kind, value = requirement(resource.canonical, request.match_info)
        session_ok = kind == "session" and (
            valid_credential(secret, value)
            or credential_from_header(secret, value, request.headers.get("Authorization")))
        if kind == "denied" or (kind == "key" and not valid_secret(secret, value)) or (
                kind == "session" and not session_ok):
            return web.json_response(
                {"status": "error", "message": "unauthorized"}, status=401)
        return await handler(request)
    return check
