"""Removing a contact: the REMOVE mutation WhatsApp Web sends."""
import asyncio
from types import SimpleNamespace as N

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import app_state_mirror
import contact_removal as cr


def _has_remove():
    from neonize.proto.Neonize_pb2 import MutationInfo
    return "Remove" in MutationInfo.DESCRIPTOR.fields_by_name


needs_remove = pytest.mark.skipif(not _has_remove(), reason="needs WinZapp's neonize build")


@pytest.mark.parametrize("phone,wid", [
    ("+55 (11) 99999-8888", "5511999998888@c.us"),
    (["5511999998888@c.us"], "5511999998888@c.us"),
    ("123456789012345@lid", "123456789012345@lid"),
    ("120363@g.us", ""), ("12", ""), (None, ""), ([], ""),
])
def test_the_contact_id(phone, wid):
    assert cr.contact_wid(phone) == wid


def test_the_index_is_the_form_whatsapp_web_writes():
    # toString({legacy: true}) of a number is '<digits>@s.whatsapp.net' (checked in the page)
    assert cr.removal_index("5511999998888") == ["contact", "5511999998888@s.whatsapp.net"]


def test_only_a_saved_contact_is_an_address_book_entry():
    assert cr.is_saved(N(Found=True, FullName="Ana", FirstName=""))
    assert not cr.is_saved(N(Found=True, FullName="", FirstName=""))
    assert not cr.is_saved(N(Found=False, FullName="Ana", FirstName="Ana"))
    assert not cr.is_saved(None)


class Contacts:
    def __init__(self, saved):
        self.saved = saved
        self.put = []

    def get_contact(self, jid):
        return N(Found=jid in self.saved, FullName="Ana" if jid in self.saved else "",
                 FirstName="")

    def put_contact_name(self, jid, first, full):
        self.put.append((jid, first, full))


class Client:
    def __init__(self, saved=(), lid_phone="", lid=""):
        self.contact = Contacts(set(saved))
        self.patches = []
        self.lid_phone = lid_phone
        self.lid = lid
        self.sent = []          # what reached WhatsApp, in order

    def send_app_state(self, patch):
        self.patches.append(patch)
        self.sent.append("app state")

    def get_pn_from_lid(self, jid):
        return N(User=self.lid_phone)

    def get_lid_from_pn(self, jid):
        return N(User=self.lid)


class RawClient(Client):
    def __init__(self, *args, answer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.queries = []
        self.answer = answer or {"node": {"tag": "iq"}}

    def send_iq(self, query):
        self.queries.append(query)
        self.sent.append("usync")
        return self.answer


class Db:
    def __init__(self):
        self.names = []

    def set_contact_name(self, jid, name):
        self.names.append((jid, name))


def run(s, body):
    async def main():
        app = web.Application()
        cr.register_routes(app.router, session=lambda req: s, jid_from_text=lambda t: t)
        async with TestClient(TestServer(app)) as http:
            resp = await http.post("/api/tok/remove-contact", json=body)
            return resp.status, await resp.json()
    return asyncio.run(main())


@pytest.fixture
def supported(monkeypatch):
    monkeypatch.setattr(app_state_mirror, "supported", lambda: True)


def session(tmp_path, client):
    return N(client=client, status="CONNECTED", folder=str(tmp_path), db=Db())


def test_a_number_that_is_not_a_contact_sends_nothing(tmp_path, supported):
    s = session(tmp_path, Client())
    assert run(s, {"phone": "5511999998888"}) == (
        400, {"status": "error", "code": "number_is_not_your_contact"})
    assert s.client.patches == []


@needs_remove
def test_a_saved_contact_is_removed_with_a_remove_mutation(tmp_path, supported):
    from neonize.proto.Neonize_pb2 import PatchInfo
    s = session(tmp_path, Client(saved={"5511999998888@s.whatsapp.net"}))
    assert run(s, {"phone": "5511999998888"}) == (
        200, {"status": "success", "response": {"message": "Contact removed"}})
    (patch,) = s.client.patches
    (mutation,) = patch.Mutations
    assert patch.Type == PatchInfo.CRITICAL_UNBLOCK_LOW
    assert list(mutation.Index) == ["contact", "5511999998888@s.whatsapp.net"]
    assert (mutation.Version, mutation.Remove) == (2, True)
    assert s.db.names == [("5511999998888@s.whatsapp.net", "")]


@needs_remove
def test_a_lid_is_removed_through_its_number(tmp_path, supported):
    s = session(tmp_path, Client(saved={"5511999998888@s.whatsapp.net"},
                                 lid_phone="5511999998888"))
    assert run(s, {"phone": "123456789012345@lid"})[0] == 200
    assert list(s.client.patches[0].Mutations[0].Index) == [
        "contact", "5511999998888@s.whatsapp.net"]


@pytest.fixture
def raw(monkeypatch):
    import raw_queries
    monkeypatch.setattr(raw_queries, "available", lambda c: hasattr(c, "send_iq"))


@needs_remove
def test_the_server_is_told_before_the_address_book_changes(tmp_path, supported, raw):
    s = session(tmp_path, RawClient(saved={"5511999998888@s.whatsapp.net"},
                                    lid="123456789012345"))
    assert run(s, {"phone": "5511999998888"})[0] == 200
    assert s.client.sent == ["usync", "app state"]
    user = s.client.queries[0]["content"][0]["content"][1]["content"][0]
    assert user["attrs"] == {"jid": {"jid": "123456789012345@lid"},
                             "pn_jid": {"jid": "5511999998888@s.whatsapp.net"}}
    assert user["content"] == [{"tag": "contact", "attrs": {"type": "delete"}}]


@needs_remove
def test_a_refused_notice_does_not_stop_the_removal(tmp_path, supported, raw):
    s = session(tmp_path, RawClient(saved={"5511999998888@s.whatsapp.net"},
                                    answer={"error": "boom", "code": 500}))
    assert run(s, {"phone": "5511999998888"})[0] == 200
    assert s.client.sent == ["usync", "app state"]


def test_a_lid_without_a_number_is_refused(tmp_path, supported):
    s = session(tmp_path, Client())
    assert run(s, {"phone": "123456789012345@lid"})[1]["code"] == "contact_lid_without_phone"


def test_an_invalid_contact_and_a_closed_session(tmp_path, supported):
    assert run(session(tmp_path, Client()), {"phone": "120363@g.us"})[1]["code"] == (
        "contact_invalid")
    closed = N(client=None, status="CLOSED", folder=str(tmp_path), db=Db())
    assert run(closed, {"phone": "5511999998888"}) == (
        503, {"status": "error", "code": "contact_not_available"})
