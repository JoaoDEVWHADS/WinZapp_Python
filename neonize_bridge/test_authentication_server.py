"""The real server (create_app) requires the secret: end to end, without WhatsApp."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth
import server


async def _client(folder):
    client = TestClient(TestServer(server.create_app(str(folder))))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_without_the_secret_nothing_passes_and_with_the_generated_token_the_route_answers(tmp_path):
    client = await _client(tmp_path)
    try:
        secret = (tmp_path / auth.SECRET_FILE).read_text(encoding="utf-8")
        assert (await client.get("/healthz")).status == 200
        # what the client's default key (public in the repository) used to get through
        assert (await client.post("/api/account1/wz-local-api-key/generate-token")).status == 401
        assert (await client.get("/api/account1:whatever/status-session")).status == 401
        assert (await client.get("/api/whatever/show-all-sessions")).status == 401

        response = await client.post(f"/api/account1/{secret}/generate-token")
        assert response.status == 200
        body = await response.json()
        assert body["full"] == "account1:" + auth.session_token(secret, "account1")

        assert (await client.get(f"/api/{body['full']}/status-session")).status == 200
        assert (await client.get(f"/api/{secret}/show-all-sessions")).status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_invalid_session_name_does_not_generate_a_token(tmp_path):
    client = await _client(tmp_path)
    try:
        secret = (tmp_path / auth.SECRET_FILE).read_text(encoding="utf-8")
        response = await client.post(f"/api/a b/{secret}/generate-token")
        assert response.status == 400
    finally:
        await client.close()


def test_the_app_is_born_with_the_bridges_body_ceiling(tmp_path):
    app = server.create_app(str(tmp_path))
    assert app._client_max_size == auth.MAX_BODY_SIZE
    # below the 2 GiB of before, but above 100 MiB of media in base64 (~134 MiB)
    assert 134 * 1024**2 < auth.MAX_BODY_SIZE < 2 * 1024**3


@pytest.mark.asyncio
async def test_multipart_in_blocks_goes_past_the_ceiling_and_big_json_does_not():
    """send-file reads the multipart in blocks (`read_chunk`), which
    client_max_size does not count; the body read at once (`req.json()`) counts."""
    from aiohttp import FormData, web

    async def send(req):
        total = 0
        reader = await req.multipart()
        while (part := await reader.next()) is not None:
            while block := await part.read_chunk(1 << 16):
                total += len(block)
        return web.json_response({"bytes": total})

    async def json_(req):
        return web.json_response(await req.json())

    app = web.Application(client_max_size=1024)
    app.router.add_post("/send", send)
    app.router.add_post("/json", json_)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        form = FormData()
        form.add_field("file", b"x" * 200_000, filename="a.bin",
                       content_type="application/octet-stream")
        response = await client.post("/send", data=form)
        assert response.status == 200
        assert (await response.json())["bytes"] == 200_000
        assert (await client.post("/json", json={"x": "y" * 5000})).status == 413
    finally:
        await client.close()


def _url_of(canonical, tok):
    """Fills in the route template: the token with the given value, the rest with 'x'."""
    import re
    return re.sub(r"\{(\w+)\}", lambda m: tok if m.group(1) in ("tok", "session", "secretkey") else "x", canonical)


@pytest.mark.asyncio
async def test_no_real_route_answers_without_credential_nor_with_a_disguised_token(tmp_path):
    """Finding M1 of the review: `%2F` in place of the token made the middleware read another
    path. Sweeps EVERY registered route, in all methods, with several disguises."""
    app = server.create_app(str(tmp_path))
    open_routes = set(auth.OPEN_ROUTES)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        seen = 0
        for resource in app.router.resources():
            canonical = resource.canonical
            if canonical in open_routes:
                continue
            for route in resource:
                if route.method in ("HEAD",):
                    continue
                for tok in ("%2F", "%2f", "x", "%252F", "..", "a%00b", "account1:", ":x"):
                    response = await client.request(
                        route.method if route.method != "*" else "GET", _url_of(canonical, tok))
                    assert response.status in (401, 404, 405), (
                        route.method, canonical, tok, response.status)
                    seen += 1
        assert seen > 500
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_path_with_extra_slashes_does_not_leave_the_route_template(tmp_path):
    client = TestClient(TestServer(server.create_app(str(tmp_path))))
    await client.start_server()
    try:
        for path in ("/api/%2F/meta-ai-terms", "/api//meta-ai-terms", "/api/%2F/typing",
                     "/api/x/../x/meta-ai-terms"):
            response = await client.get(path)
            assert response.status in (401, 404, 405), (path, response.status)
    finally:
        await client.close()
