"""A contact card names the contact by phone, never by the digits of a LID.

Audit F4 (extra item): send_contact_attachment() built contactsId from the
user part of contact_info["remoteJid"], so a contact known only as
``<digits>@lid`` went out as ``<lid digits>@c.us``, the digits of a linked-device
id posing as a phone number (CLAUDE.md, JID handling).
"""
import types

import pytest

from main import MainWindow
from main_window.sending import contact_card_id
from tests.god_modules import patch_main_global

LID = "184467440737095@lid"
PHONE = "5511987654321@s.whatsapp.net"


@pytest.mark.parametrize("jid, bridge, expected", [
    ("5511987654321@s.whatsapp.net", {}, "5511987654321@c.us"),
    ("5511987654321@c.us", {}, "5511987654321@c.us"),
    ("5511987654321", {}, "5511987654321@c.us"),
    ("5511987654321:60@s.whatsapp.net", {}, "5511987654321@c.us"),
    (LID, {LID: PHONE}, "5511987654321@c.us"),
    # no phone known: the LID travels whole, never as @c.us
    (LID, {}, "184467440737095@lid"),
    (LID, None, "184467440737095@lid"),
    ("", {}, "@c.us"),
])
def test_the_contact_id(jid, bridge, expected):
    assert contact_card_id(jid, bridge) == expected


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"status": "success", "response": {"id": "true_x_ABC", "ack": 1}}


def _send(monkeypatch, contact_jid, bridge):
    posted = []
    patch_main_global(monkeypatch, "api_post",
                      lambda url, **kwargs: posted.append(kwargs["json"]) or _Response())
    window = types.SimpleNamespace(
        wpp_server="http://127.0.0.1", wpp_port=6300, token="s:h", _lid_to_phone=bridge,
        _resolve_jid_for_send=lambda jid: jid, i18n=types.SimpleNamespace(t=lambda k: k))
    MainWindow.send_contact_attachment(
        window, "5511900000000@s.whatsapp.net", {"pushName": "Ana", "remoteJid": contact_jid})
    return posted[0]


def test_the_card_of_a_lid_contact_carries_its_phone(monkeypatch):
    assert _send(monkeypatch, LID, {LID: PHONE})["contactsId"] == ["5511987654321@c.us"]


def test_the_card_of_a_lid_without_a_known_phone_sends_the_lid(monkeypatch):
    assert _send(monkeypatch, LID, {})["contactsId"] == ["184467440737095@lid"]
