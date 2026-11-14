"""Send routes: the pure functions and the routes that do not need neonize
(body validation and disconnection)."""
import asyncio
import base64
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import chat_sending as cs


def test_coordinates_accepts_numbers_and_text():
    assert cs.coordinates("-23.5", 46.6) == (-23.5, 46.6)


@pytest.mark.parametrize("lat,lng", [("x", 1), (None, 1), (91, 0), (0, 181)])
def test_coordinates_refuses_the_invalid(lat, lng):
    with pytest.raises(ValueError):
        cs.coordinates(lat, lng)


def test_base64_data_with_and_without_prefix():
    b64 = base64.b64encode(b"abc").decode()
    assert cs.base64_data(b64) == (b"abc", "")
    assert cs.base64_data("data:Image/PNG;base64," + b64) == (b"abc", "image/png")
    assert cs.base64_data("data:;base64," + b64) == (b"abc", "")


@pytest.mark.parametrize("text", ["", "###", "data:image/png;base64,"])
def test_base64_data_refuses_the_invalid(text):
    with pytest.raises(ValueError):
        cs.base64_data(text)


def test_file_source_only_accepts_base64_and_data_uri():
    assert cs.file_source(base64.b64encode(b"zz").decode())[0] == b"zz"
    uri = "data:image/webp;base64," + base64.b64encode(b"zz").decode()
    assert cs.file_source(uri) == (b"zz", "image/webp")


@pytest.mark.parametrize("text", [
    "https://a.com/x.webp",
    "http://127.0.0.1:6311/api/x",
    "http://localhost/x",
    "http://169.254.169.254/latest/meta-data/",
    "http://0.0.0.0/",
    "http://[::ffff:127.0.0.1]/",
    "http://[::1]/",
    "http://2130706433/",      # 127.0.0.1 in decimal
    "http://0177.0.0.1/",      # octal
    "http://0x7f.0.0.1/",      # hex
    "  HTTPS://A.COM/X.PNG  ",
    "ftp://a.com/x",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/_x",
])
def test_file_source_refuses_a_url_of_any_scheme(text):
    with pytest.raises(ValueError, match="url sources"):
        cs.file_source(text)


@pytest.mark.parametrize("text", [
    "/etc/passwd", "C:\\Users\\a\\x.png", "\\\\server\\folder\\x.png",
    "../x.png", "file:/etc/passwd", "http:/127.0.0.1/", "x.png"])
def test_file_source_refuses_a_disk_path(text):
    with pytest.raises(ValueError):
        cs.file_source(text)


def test_file_kind_by_mime_or_by_name():
    assert cs.file_kind("image/png") == "image"
    assert cs.file_kind("video/mp4") == "video"
    assert cs.file_kind("audio/ogg; codecs=opus") == "audio"
    assert cs.file_kind("application/pdf") == "document"
    assert cs.file_kind("", "photo.jpg") == "image"
    assert cs.file_kind("", "no-extension") == "document"


def test_with_group():
    assert cs.with_group(["1203"], True) == "1203@g.us"
    assert cs.with_group("1203", False) == "1203"
    assert cs.with_group("55@c.us", True) == "55@c.us"


def ask(path, body, connected):
    s = N(client=object() if connected else None, status="CONNECTED" if connected else "CLOSED")
    calls = []

    async def run():
        app = web.Application()
        cs.register_routes(
            app.router, session=lambda req: s, ok=lambda **kw: web.json_response(kw),
            error=lambda m, status=500: web.json_response(
                {"status": "error", "message": str(m)}, status=status),
            destination_of=lambda phone: calls.append(phone) or phone,
            store_sent=None, send_media=None, quoted_context=None,
            in_thread=None)
        async with TestClient(TestServer(app)) as client:
            response = await client.post(path, json=body)
            return response.status, await response.json()
    return asyncio.run(run()), calls


def test_route_without_a_required_field_is_400():
    (status, body), _ = ask("/api/t/send-location", {"phone": "55"}, True)
    assert status == 400 and body["status"] == "error"


def test_route_with_an_invalid_coordinate_is_400():
    (status, _), _ = ask("/api/t/send-location", {"phone": "55", "lat": 99, "lng": 0}, True)
    assert status == 400


def test_file_route_with_invalid_base64_is_400():
    (status, _), _ = ask("/api/t/send-image", {"phone": "55", "base64": "###"}, True)
    assert status == 400


def test_voice_route_refuses_a_disk_path():
    (status, _), _ = ask("/api/t/send-voice", {"phone": "55", "path": "/etc/passwd"}, True)
    assert status == 400


@pytest.mark.parametrize("route,field", [
    ("send-voice", "path"), ("send-sticker", "path"), ("send-sticker", "base64"),
    ("send-sticker-gif", "path"), ("send-sticker-gif", "base64")])
def test_voice_and_sticker_routes_refuse_a_url_without_downloading(route, field):
    # connected: if the URL got past the validation, the route would reach neonize
    (status, body), _ = ask(
        "/api/t/" + route, {"phone": "55", field: "http://169.254.169.254/latest/"}, True)
    assert status == 400 and "url sources" in body["message"]


def test_route_without_a_connection_answers_404_without_sending():
    (status, body), _ = ask(
        "/api/t/send-location", {"phone": "55", "lat": 1, "lng": 2}, False)
    assert status == 404 and body["status"] == "Disconnected"


def test_isgroup_becomes_a_group_jid_in_the_destination():
    _, calls = ask("/api/t/send-location",
                   {"phone": "1203", "isGroup": True, "lat": 1, "lng": 2}, False)
    assert calls == ["1203@g.us"]


def test_send_link_preview_answers_501_and_never_reaches_neonize():
    """neonize would fetch the page (and the og:image) from the user's machine: SSRF."""
    for connected in (True, False):
        (status, body), calls = ask(
            "/api/t/send-link-preview",
            {"phone": "55", "url": "http://169.254.169.254/latest/"}, connected)
        assert status == 501 and "link previews are not available" in body["message"]
        assert calls == []
