"""Removing a contact from the address book (`POST remove-contact {phone}`).

What WhatsApp Web does (read over CDP on 2026-10-26: WAWebDeleteContactAction
-> WAWebContactEditSync.sendContactDelete -> WAWebContactSync): first a usync
"delta" query telling the server the contact is gone (contact_sync.py), then
a REMOVE mutation in `critical_unblock_low`, index
["contact", "<digits>@s.whatsapp.net"] (`toString({legacy: true})`, which
WhatsApp Web turns into @s.whatsapp.net: checked in the page), version 2, an
empty ContactAction. save-contact writes the same index.

A REMOVE needs the entry to exist (whatsmeow hashes it against the previous
SET), so a number that is not a saved contact is refused before anything is
sent. The body and the answers follow WinZapp's WPPConnect route
(contactSaveController.ts): `phone` is digits or '<digits>@lid';
`{"response": {"message": "Contact removed"}}`, or a fixed `code`. A neonize
build without REMOVE mutations answers 501 "contact_operation_unsupported", as
before. Not run against a real account.
"""
import asyncio
import logging
import re

from aiohttp import web

import app_state_mirror
import contact_sync

log = logging.getLogger("bridge")

COLLECTION = "critical_unblock_low"
INDEX = "contact"
VERSION = 2
_WID = re.compile(r"\d{7,20}@(c\.us|lid)\Z")
STATUS = {"contact_invalid": 400, "contact_lid_without_phone": 400,
          "number_is_not_your_contact": 400, "contact_not_available": 503,
          "contact_operation_unsupported": 501, "contact_operation_failed": 502}


def contact_wid(phone) -> str:
    """The contact id out of `phone` (digits, or a whole id), '' when it is not one."""
    first = phone[0] if isinstance(phone, list) and phone else phone
    raw = str(first if first is not None else "").strip()
    wid = raw if "@" in raw else re.sub(r"\D", "", raw) + "@c.us"
    return wid if _WID.fullmatch(wid) else ""


def removal_index(digits) -> list:
    return [INDEX, f"{digits}@s.whatsapp.net"]


def is_saved(contact) -> bool:
    """Is neonize's ContactInfo an address book entry (it has a saved name)?"""
    return bool(contact is not None and getattr(contact, "Found", False)
                and (getattr(contact, "FullName", "") or getattr(contact, "FirstName", "")))


def register_routes(r, *, session, jid_from_text):
    """Wire the route to the aiohttp router `r`."""

    def failure(code):
        return web.json_response({"status": "error", "code": code}, status=STATUS[code])

    def saved(s, phone):
        try:
            return is_saved(s.client.contact.get_contact(jid_from_text(phone)))
        except Exception:
            return False

    def lid_of(s, phone):
        try:
            lid = s.client.get_lid_from_pn(jid_from_text(phone))
        except Exception:
            return ""
        user = getattr(lid, "User", "")
        return f"{user}@lid" if user else ""

    def remove(s, digits):
        from neonize.proto.waSyncAction.WAWebProtobufSyncAction_pb2 import (
            ContactAction, SyncActionValue)
        phone = f"{digits}@s.whatsapp.net"
        if not saved(s, phone):
            return "number_is_not_your_contact"
        contact_sync.notify(s.client, contact_sync.delete_query(phone, lid_of(s, phone)),
                            "removal")
        value = SyncActionValue(contactAction=ContactAction())
        app_state_mirror.send(s, COLLECTION, [(removal_index(digits), VERSION, value, True)])
        s.db.set_contact_name(phone, "")
        try:
            s.client.contact.put_contact_name(jid_from_text(phone), "", "")
        except Exception:
            log.warning("remove-contact: neonize's contact store not updated")
        return ""

    async def remove_contact(req):
        s = session(req)
        try:
            body = await req.json()
        except ValueError:
            body = {}
        wid = contact_wid((body or {}).get("phone") if isinstance(body, dict) else None)
        if not wid:
            return failure("contact_invalid")
        if not app_state_mirror.supported():
            return failure("contact_operation_unsupported")
        if s.client is None or s.status != "CONNECTED":
            return failure("contact_not_available")
        loop = asyncio.get_running_loop()
        digits = wid.partition("@")[0]
        if wid.endswith("@lid"):
            try:
                digits = (await loop.run_in_executor(
                    None, s.client.get_pn_from_lid, jid_from_text(wid))).User
            except Exception:
                digits = ""
            if not digits:
                return failure("contact_lid_without_phone")
        try:
            code = await loop.run_in_executor(None, remove, s, digits)
        except Exception:
            log.exception("remove-contact")
            return failure("contact_operation_failed")
        if code:
            return failure(code)
        return web.json_response({"status": "success",
                                  "response": {"message": "Contact removed"}})

    r.add_post("/api/{tok}/remove-contact", remove_contact)
