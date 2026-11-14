"""Video messages without ffprobe: the message built, and send-file of a video
for real (create_app) against a fake client with no build_video_message. Runs
no ffmpeg: the thumbnail probe is replaced."""
from types import SimpleNamespace as N

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

import authentication as auth
import media_probe
import server
import video_message as vm
from test_media_probe import mp4

UPLOAD = N(url="https://mmg/v", DirectPath="/v/v", MediaKey=b"k", FileEncSHA256=b"e",
           FileSHA256=b"s", FileLength=9)


class Client:
    """upload, send_message and the mention parsers neonize's build uses."""

    def __init__(self):
        self.uploads, self.sent = [], []

    def upload(self, binary, media_type=None):
        self.uploads.append(binary)
        return UPLOAD

    def send_message(self, destination, message):
        self.sent.append((destination, message))
        return N(ID="NEW1", Timestamp=1_700_000_000, Message=message)

    def _parse_mention(self, text=None, are_lids=False):
        return ["5511999990000@s.whatsapp.net"] if text and "@5511999990000" in text else []

    def _parse_group_mention(self, text=None):
        return []


def test_the_duration_comes_from_the_mp4_not_from_ffmpeg():
    client = Client()
    m = vm.build(client, mp4(600, 600 * 31), "oi @5511999990000",
                 mimetype_of=lambda d: "video/mp4", probe=lambda f: (b"JPEG", 99.0))
    v = m.videoMessage
    assert v.seconds == 31 and v.JPEGThumbnail == b"JPEG"
    assert (v.URL, v.directPath, v.fileLength, v.mimetype) == ("https://mmg/v", "/v/v", 9, "video/mp4")
    assert v.thumbnailDirectPath == "/v/v"
    assert v.caption == "oi @5511999990000"
    assert list(v.contextInfo.mentionedJID) == ["5511999990000@s.whatsapp.net"]


def test_a_container_it_cannot_read_takes_ffmpegs_duration(tmp_path):
    path = tmp_path / "a.webm"
    path.write_bytes(b"\x1aE\xdf\xa3webm")
    probed = []

    def probe(file):
        probed.append(file)
        return b"JPEG", 4.6
    client = Client()
    m = vm.build(client, str(path), None, mimetype_of=lambda d: "video/webm", probe=probe)
    assert probed == [str(path)]
    assert client.uploads == [b"\x1aE\xdf\xa3webm"]
    assert m.videoMessage.seconds == 5 and not m.videoMessage.caption


def test_without_a_thumbnail_or_a_duration_the_video_still_goes():
    m = vm.build(Client(), b"????", None, mimetype_of=lambda d: None,
                 probe=lambda f: (b"", None))
    v = m.videoMessage
    assert v.seconds == 0 and v.JPEGThumbnail == b"" and v.mimetype == "video/mp4"


@pytest.fixture
def sessions(monkeypatch):
    created = []

    class Registered(server.Session):
        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            created.append(self)
    monkeypatch.setattr(server, "Session", Registered)
    return created


@pytest.mark.asyncio
async def test_send_file_of_a_video_goes_out_without_ffprobe(tmp_path, sessions, monkeypatch):
    monkeypatch.setattr(media_probe, "mimetype", lambda data: "video/mp4")
    monkeypatch.setattr(media_probe, "thumbnail_and_seconds", lambda file: (b"JPEG", None))
    http = TestClient(TestServer(server.create_app(str(tmp_path))))
    await http.start_server()
    try:
        secret = (tmp_path / auth.SECRET_FILE).read_text(encoding="utf-8")
        token = f"account1:{auth.session_token(secret, 'account1')}"
        await http.get(f"/api/{token}/status-session")
        client = Client()
        s = sessions[0]
        s.client, s.status, s.me = client, "CONNECTED", "5500000000@s.whatsapp.net"
        video = mp4(1000, 8000)
        form = FormData()
        form.add_field("phone", "5511999990000@c.us")
        form.add_field("type", "video")
        form.add_field("caption", "olha")
        form.add_field("file", video, filename="v.mp4", content_type="video/mp4")
        response = await http.post(f"/api/{token}/send-file", data=form)
        assert response.status == 200
        assert (await response.json())["status"] == "success"
        assert client.uploads == [video]
        sent = client.sent[0][1].videoMessage
        assert sent.seconds == 8 and sent.JPEGThumbnail == b"JPEG" and sent.caption == "olha"
    finally:
        await http.close()
