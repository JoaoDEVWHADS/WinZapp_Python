"""Who sees my Status: the app state mutation WhatsApp Web sends."""
import asyncio
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import app_state_mirror
import status_privacy as sp


@pytest.mark.parametrize("body,expected", [
    ({"setting": "contact", "list": ["5511999998888@c.us"]}, ("contact", [])),
    ({"setting": "deny-list", "list": ["5511999998888@c.us", "123456789012345@lid",
                                       "5511999998888@c.us"]},
     ("deny-list", ["5511999998888@c.us", "123456789012345@lid"])),
    ({"setting": "allow-list"}, ("allow-list", [])),
])
def test_a_valid_request(body, expected):
    assert sp.parse_request(body) == expected


@pytest.mark.parametrize("body", [
    {}, {"setting": "everyone"}, {"setting": "deny-list", "list": "5511@c.us"},
    {"setting": "deny-list", "list": ["5511999998888@s.whatsapp.net"]},
    {"setting": "deny-list", "list": ["120363@g.us"]},
    {"setting": "allow-list", "list": ["5511999998888@c.us"] * (sp.MAX_LIST + 1)}, None,
])
def test_an_invalid_request(body):
    assert sp.parse_request(body) is None


def test_the_modes_are_whatsapps():
    from neonize.proto.waSyncAction.WAWebProtobufSyncAction_pb2 import StatusPrivacyAction
    mode = StatusPrivacyAction.StatusDistributionMode
    assert sp.MODES == {"allow-list": mode.Value("ALLOW_LIST"),
                        "deny-list": mode.Value("DENY_LIST"), "contact": mode.Value("CONTACTS")}
    # WhatsApp Web writes a number as toString({legacy: true}): '@s.whatsapp.net'
    assert sp.privacy_fields("deny-list", ["1@c.us", "2@lid"]) == {
        "mode": 1, "userJID": ["1@s.whatsapp.net", "2@lid"]}


class Client:
    def __init__(self):
        self.patches = []

    def send_app_state(self, patch):
        self.patches.append(patch)


def run(s, body):
    async def main():
        app = web.Application()
        sp.register_routes(app.router, session=lambda req: s)
        async with TestClient(TestServer(app)) as http:
            resp = await http.post("/api/tok/privacy/status", json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


def test_the_mutation_is_sent_to_regular_high_and_answered(tmp_path, monkeypatch):
    from neonize.proto.Neonize_pb2 import PatchInfo
    monkeypatch.setattr(app_state_mirror, "supported", lambda: True)
    s = N(client=Client(), status="CONNECTED", folder=str(tmp_path))
    status, body = run(s, {"setting": "allow-list", "list": ["5511999998888@c.us"]})
    assert (status, body["response"]) == (200, {"setting": "allow-list"})
    (patch,) = s.client.patches
    (mutation,) = patch.Mutations
    assert patch.Type == PatchInfo.REGULAR_HIGH
    assert (list(mutation.Index), mutation.Version) == (["status_privacy"], 7)
    action = mutation.Value.statusPrivacy
    assert (action.mode, list(action.userJID)) == (0, ["5511999998888@s.whatsapp.net"])
    assert sp.setting_of(app_state_mirror.mirror_of(s)) == "allow-list"


def test_disconnected_and_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state_mirror, "supported", lambda: True)
    s = N(client=None, status="CLOSED", folder=str(tmp_path))
    assert run(s, {"setting": "contact"})[1]["code"] == "privacy_unavailable"

    class Refusing:
        def send_app_state(self, patch):
            raise Exception("server said no")
    s = N(client=Refusing(), status="CONNECTED", folder=str(tmp_path))
    assert run(s, {"setting": "contact"}) == (
        502, {"status": "error", "code": "status_privacy_failed"})


def test_the_status_field_the_client_reads():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
    try:
        from core import whatsapp_privacy
    finally:
        sys.path.pop(0)
    field = sp.status_field(1, ["5511999998888@s.whatsapp.net", "123@lid", "1203@g.us",
                                "5511999998888:2@s.whatsapp.net"])
    assert field == {"setting": "deny-list", "list": ["5511999998888@c.us", "123@lid"]}
    read = whatsapp_privacy.parse_status_privacy(field)
    assert (read.setting, read.people) == ("deny-list", ("5511999998888@c.us", "123@lid"))
    assert whatsapp_privacy.parse_status_privacy(sp.status_field(None, ())).setting == "contact"
    assert sp.status_field(9, []) is None


def test_read_status_from_a_complete_copy_only(tmp_path, monkeypatch):
    monkeypatch.setattr(app_state_mirror, "supported", lambda: True)
    s = N(client=Client(), status="CONNECTED", folder=str(tmp_path))
    monkeypatch.setattr(app_state_mirror, "ensure_seeded", lambda s, c, t: False)
    assert sp.read_status(s) is None
    monkeypatch.setattr(app_state_mirror, "ensure_seeded", lambda s, c, t: c == "regular_high")
    assert sp.read_status(s) == {"setting": "contact", "list": []}
    run(s, {"setting": "allow-list", "list": ["5511999998888@c.us"]})
    assert sp.read_status(s) == {"setting": "allow-list", "list": ["5511999998888@c.us"]}
    monkeypatch.setattr(app_state_mirror, "supported", lambda: False)
    assert sp.read_status(s) is None
