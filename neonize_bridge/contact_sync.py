"""The usync "delta" query that tells WhatsApp's server a contact was added to
or removed from the address book, sent before the app state mutation as
WhatsApp Web does (read over CDP on 2026-10-26: WAWebContactSyncUtils.
constructUsyncDeltaQuery, WAWebUsync, WAWebUsyncContact, WAWebUsyncUser):

    <iq xmlns="usync" type="get" to="s.whatsapp.net">
      <usync sid=.. index="0" last="true" mode="delta" context="interactive">
        <query><contact addressing_mode="lid"/><username/></query>
        <list>
          <user><contact>5511999998888</contact></user>        (add: digits only)
          <user jid=LID pn_jid=PN><contact type="delete"/></user>  (delete)
        </list>
      </usync>
    </iq>

A delete names the person's LID when it is known (`jid`) and always the
number (`pn_jid`, '<digits>@s.whatsapp.net').

It is best effort here: WhatsApp Web stops the save when the server refuses
it, but the address book itself is the app state entry, and a refusal of this
notice must not lose a save that worked before the bridge sent it. A refusal
is logged; a neonize build without raw queries skips it.
"""
import logging
import secrets

import raw_queries as rq

log = logging.getLogger("bridge")


def _user_add(digits) -> dict:
    return rq.node("user", None, [rq.node("contact", None, str(digits))])


def _user_delete(phone_jid, lid="") -> dict:
    attrs = {"pn_jid": rq.jid(phone_jid)}
    if lid:
        attrs = {"jid": rq.jid(lid), **attrs}
    return rq.node("user", attrs, [rq.node("contact", {"type": "delete"})])


def delta_query(users, sid=None) -> dict:
    """The usync delta query for these <user> nodes."""
    return {"namespace": "usync", "type": "get", "content": [rq.node("usync", {
        "sid": sid or secrets.token_hex(8), "index": "0", "last": "true",
        "mode": "delta", "context": "interactive"}, [
            rq.node("query", None, [rq.node("contact", {"addressing_mode": "lid"}),
                                    rq.node("username")]),
            rq.node("list", None, list(users))])]}


def add_query(digits, sid=None) -> dict:
    return delta_query([_user_add(digits)], sid)


def delete_query(phone_jid, lid="", sid=None) -> dict:
    return delta_query([_user_delete(phone_jid, lid)], sid)


def refusal(response) -> str:
    """The error the server put in the <contact> result, or ''."""
    usync = rq.child(response, "usync")
    result = rq.child(usync, "result") if usync else None
    contact = rq.child(result, "contact") if result else None
    error = rq.child(contact, "error") if contact else None
    return ((error.get("attrs") or {}).get("code") or "?") if error else ""


def notify(client, query, what) -> bool:
    """Sends the notice; True when the server took it. Never raises. Runs on a thread."""
    if not rq.available(client):
        return False
    try:
        code = refusal(rq.send_iq(client, query))
    except Exception as error:
        log.warning("contact %s: usync notice not sent (%s)", what,
                    getattr(error, "code", 0) or type(error).__name__)
        return False
    if code:
        log.warning("contact %s: usync notice refused (%s)", what, code)
        return False
    return True
