"""Who can talk to the bridge: secret, session token, route and Host."""
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth

SECRET = "s" * 64


def test_the_secret_is_created_once_and_read_again(tmp_path):
    first = auth.load_secret(str(tmp_path))
    assert len(first) == 64
    assert auth.load_secret(str(tmp_path)) == first
    assert (tmp_path / auth.SECRET_FILE).read_text(encoding="utf-8") == first


def test_an_empty_secret_file_generates_another(tmp_path):
    (tmp_path / auth.SECRET_FILE).write_text("  \n", encoding="utf-8")
    assert len(auth.load_secret(str(tmp_path))) == 64


def test_session_token_depends_on_the_secret_and_the_name():
    assert auth.session_token(SECRET, "a") == auth.session_token(SECRET, "a")
    assert auth.session_token(SECRET, "a") != auth.session_token(SECRET, "b")
    assert auth.session_token(SECRET, "a") != auth.session_token("t" * 64, "a")


def test_credential_is_only_valid_with_this_sessions_hash():
    right = "account1:" + auth.session_token(SECRET, "account1")
    assert auth.valid_credential(SECRET, right)
    assert not auth.valid_credential(SECRET, "account2:" + auth.session_token(SECRET, "account1"))
    assert not auth.valid_credential("t" * 64, right)


@pytest.mark.parametrize("token", ["", None, "account1", "account1:", ":abc", "account1:abc"])
def test_incomplete_or_wrong_credential_is_refused(token):
    assert not auth.valid_credential(SECRET, token)


def test_valid_secret_refuses_empty_and_different():
    assert auth.valid_secret(SECRET, SECRET)
    assert not auth.valid_secret(SECRET, "")
    assert not auth.valid_secret(SECRET, None)
    assert not auth.valid_secret(SECRET, SECRET + "x")


@pytest.mark.parametrize("host", ["127.0.0.1:6300", "localhost:6300", "LOCALHOST", "[::1]:6300", "127.0.0.1"])
def test_the_machines_own_host_is_accepted(host):
    assert auth.host_allowed(host)


@pytest.mark.parametrize("host", ["", None, "evil.com", "evil.com:6300", "127.0.0.1.evil.com:6300",
                                  "192.168.0.5:6300", "0.0.0.0:6300"])
def test_another_host_is_refused_against_dns_rebinding(host):
    assert not auth.host_allowed(host)


@pytest.mark.parametrize("template,parts,expected", [
    ("/healthz", {}, ("open", "")),
    ("/health", {}, ("open", "")),
    ("/winzapp/identity", {}, ("open", "")),
    ("/metrics", {}, ("open", "")),
    ("/socket.io/", {}, ("open", "")),
    ("/api/{session}/{key}/generate-token", {"session": "account1", "key": "KEY"}, ("key", "KEY")),
    ("/api/{secretkey}/show-all-sessions", {"secretkey": "SECRET"}, ("key", "SECRET")),
    ("/api/{secretkey}/start-all", {"secretkey": "SECRET"}, ("key", "SECRET")),
    ("/api/{secretkey}/shutdown", {"secretkey": "SECRET"}, ("key", "SECRET")),
    ("/api/{tok}/send-message", {"tok": "account1:abc"}, ("session", "account1:abc")),
    ("/api/{tok}/group-info/{groupId}", {"tok": "account1:abc", "groupId": "1@g.us"}, ("session", "account1:abc")),
    ("/api/{tok}/delete-all-chats", {"tok": "account1:abc"}, ("session", "account1:abc")),
    ("/api/{tok}/send-message", {"tok": "/"}, ("session", "/")),
])
def test_what_each_route_requires(template, parts, expected):
    assert auth.requirement(template, parts) == expected


@pytest.mark.parametrize("template", ["/", "/other", "/api/{x}/y", "/api", "/static/{p}"])
def test_unknown_route_is_denied_by_default(template):
    assert auth.requirement(template, {})[0] == "denied"


def test_comparison_does_not_fail_with_non_ascii_characters():
    assert not auth.valid_credential(SECRET, "account1:ééé")
    assert not auth.valid_secret(SECRET, "é" * 64)
    assert not auth.valid_credential(SECRET, ["account1", "x"])
    assert not auth.valid_credential(SECRET, {"a": 1})
    assert not auth.valid_secret(SECRET, ["x"])


def test_two_bridges_creating_the_secret_together_end_up_with_the_same_one(tmp_path):
    import threading
    folder = str(tmp_path / "data")
    results = []

    def create():
        results.append(auth.load_secret(folder))
    threads = [threading.Thread(target=create) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 12 and len(set(results)) == 1
    assert results[0] == (tmp_path / "data" / auth.SECRET_FILE).read_text(encoding="utf-8")


async def _client():
    async def ok(req):
        return web.json_response({"ok": True})
    app = web.Application(middlewares=[auth.create_middleware(SECRET)])
    app.router.add_get("/healthz", ok)
    app.router.add_get("/api/{tok}/status-session", ok)
    app.router.add_post("/api/{session}/{key}/generate-token", ok)
    app.router.add_get("/api/{secretkey}/show-all-sessions", ok)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_middleware_only_lets_through_whoever_has_a_credential():
    client = await _client()
    try:
        good = "account1:" + auth.session_token(SECRET, "account1")
        assert (await client.get("/healthz")).status == 200
        assert (await client.get(f"/api/{good}/status-session")).status == 200
        assert (await client.get("/api/account1:wrong/status-session")).status == 401
        assert (await client.get("/api/account1/status-session")).status == 401
        assert (await client.post("/api/account1/wrong-key/generate-token")).status == 401
        assert (await client.post(f"/api/account1/{SECRET}/generate-token")).status == 200
        assert (await client.get("/api/nothing/show-all-sessions")).status == 401
        assert (await client.get(f"/api/{SECRET}/show-all-sessions")).status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_middleware_refuses_an_outside_host_even_with_a_credential():
    client = await _client()
    try:
        good = "account1:" + auth.session_token(SECRET, "account1")
        response = await client.get(f"/api/{good}/status-session", headers={"Host": "evil.com:6300"})
        assert response.status == 403
        response = await client.get("/healthz", headers={"Host": "evil.com"})
        assert response.status == 403
    finally:
        await client.close()


def test_credential_name_is_the_tokens_prefix():
    assert auth.credential_name("account1:abc") == "account1"
    assert auth.credential_name("no-separator") == "no-separator"
    assert auth.credential_name(None) == ""


def test_bearer_is_valid_with_the_secret_or_the_session_hash_as_in_wppconnect():
    digest = auth.session_token(SECRET, "account1")
    by_header = auth.credential_from_header
    assert by_header(SECRET, "account1", f"Bearer {SECRET}")
    assert by_header(SECRET, "account1", f"Bearer {digest}")
    assert by_header(SECRET, "account1", SECRET)              # the whole header, without "Bearer"
    assert by_header(SECRET, "account1", f"bearer  {digest} ")
    # the hash of ANOTHER session, junk, empty and wrong types are not valid
    assert not by_header(SECRET, "account1", f"Bearer {auth.session_token(SECRET, 'account2')}")
    assert not by_header(SECRET, "account1", "Bearer wrong")
    assert not by_header(SECRET, "account1", "Bearer ")
    assert not by_header(SECRET, "account1", "")
    assert not by_header(SECRET, "account1", None)
    assert not by_header(SECRET, "", f"Bearer {SECRET}")
    assert not by_header(SECRET, None, f"Bearer {SECRET}")
    # a name that already carries ":" is only valid through the path's own hash
    assert not by_header(SECRET, "account1:x", f"Bearer {SECRET}")


@pytest.mark.asyncio
async def test_middleware_accepts_bearer_when_the_path_only_carries_the_name():
    """The client calls with the session name without `:hash` in several places
    (check_connection_status at startup, closing the session before pairing)."""
    client = await _client()
    try:
        digest = auth.session_token(SECRET, "account1")
        for header in (f"Bearer {SECRET}", f"Bearer {digest}"):
            response = await client.get("/api/account1/status-session",
                                        headers={"Authorization": header})
            assert response.status == 200, header
        for header in ("Bearer wrong", f"Bearer {auth.session_token(SECRET, 'other')}"):
            response = await client.get("/api/account1/status-session",
                                        headers={"Authorization": header})
            assert response.status == 401, header
        # without a header it still refuses; and the header does not open the key routes
        assert (await client.get("/api/account1/status-session")).status == 401
        response = await client.post("/api/account1/wrong-key/generate-token",
                                     headers={"Authorization": f"Bearer {SECRET}"})
        assert response.status == 401
        # with ":hash" in the path the header does not replace the path's credential
        response = await client.get("/api/account1:wrong/status-session",
                                    headers={"Authorization": f"Bearer {SECRET}"})
        assert response.status == 401
    finally:
        await client.close()
