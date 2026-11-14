"""Editing and deleting a channel I own (`PUT` / `DELETE newsletter/:id`),
through the MEX (GraphQL) mutations WhatsApp Web runs, read over CDP on
2026-10-26:

- WAWebMexUpdateNewsletterJobMutation, id 24250201037901610, variables
  {newsletter_id, updates: {name, description, picture, settings}}, answer
  `xwa2_newsletter_update` (whatsmeow still knows an older id, 7150902998257522);
- WAWebMexDeleteNewsletterJobMutation, id 30062808666639665, variables
  {newsletter_id}, answer `xwa2_newsletter_delete_v2`.

A field left out of `updates` is not changed (WhatsApp Web sends only what was
edited); `picture` is the base64 of a JPEG of at most 640 px, "" removes it
(wa-js: `picture: null`). The answers follow WPPConnect's: 201 with the channel
(edit) or `true` (delete). A neonize build without raw queries answers 501
"newsletter_unsupported", as before. Not run against a real account.
"""
import asyncio
import base64
import logging

from aiohttp import web

import raw_queries as rq
from channels import channel_id, image_from_text

log = logging.getLogger("bridge")

UPDATE_QUERY = "24250201037901610"
DELETE_QUERY = "30062808666639665"
UPDATE_FIELD = "xwa2_newsletter_update"
DELETE_FIELD = "xwa2_newsletter_delete_v2"


def edit_updates(body, to_jpeg) -> dict:
    """`updates` of the edit from the route's body ({name, description,
    picture}). `to_jpeg(bytes) -> bytes`. Raises ValueError when nothing would
    change or the picture is not an image in base64."""
    body = body if isinstance(body, dict) else {}
    updates = {}
    for field in ("name", "description"):
        value = body.get(field)
        if isinstance(value, str) and (value.strip() or field == "description"):
            updates[field] = value.strip() if field == "name" else value
    if "picture" in body:
        picture = body["picture"]
        if picture is None or picture == "":
            updates["picture"] = ""
        else:
            data = image_from_text(picture)
            if not data:
                raise ValueError("picture must be base64")
            updates["picture"] = base64.b64encode(to_jpeg(data)).decode("ascii")
    if not updates:
        raise ValueError("nothing to change: send name, description or picture")
    updates["settings"] = None
    return updates


def edited_channel(answer, channel) -> dict:
    """The edit's answer as wa-js's editNewsletter returns it."""
    thread = (answer or {}).get("thread_metadata") or {}
    invite = thread.get("invite") or ""
    return {"idJid": answer.get("id") or channel,
            "inviteCode": invite,
            "inviteLink": f"https://whatsapp.com/channel/{invite}" if invite else "",
            "name": (thread.get("name") or {}).get("text", ""),
            "state": ((answer.get("state") or {}).get("type") or ""),
            "description": (thread.get("description") or {}).get("text", ""),
            "timestamp": int(thread.get("creation_time") or 0)}


def register_routes(r, *, session):
    """Wire the routes to the aiohttp router `r`."""
    from groups_extra import photo_to_jpeg

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def error(message, status, code="newsletter_failed"):
        return web.json_response({"status": "error", "code": code, "message": str(message)},
                                 status=status)

    def ready(s):
        return s.client is not None and s.status == "CONNECTED"

    async def edit(req):
        s = session(req)
        channel = channel_id(req.match_info["id"])
        if not channel:
            return error("not a newsletter id", 400)
        if not rq.available(s.client):
            return error("neonize cannot edit a channel", 501, "newsletter_unsupported")
        if not ready(s):
            return error("Disconnected", 400)
        try:
            body = await req.json()
        except ValueError:
            body = {}
        try:
            updates = edit_updates(body, photo_to_jpeg)
        except (ValueError, OSError) as e:
            return error(e, 400, "invalid_newsletter_edit")
        try:
            answer = await execute(rq.send_mex, s.client, UPDATE_QUERY,
                                   {"newsletter_id": channel, "updates": updates}, UPDATE_FIELD)
        except rq.QueryError as e:
            log.warning("newsletter edit refused: %s", e)
            return error("WhatsApp did not edit the channel", 502)
        return web.json_response(edited_channel(answer, channel), status=201)

    async def delete(req):
        s = session(req)
        channel = channel_id(req.match_info["id"])
        if not channel:
            return error("not a newsletter id", 400)
        if not rq.available(s.client):
            return error("neonize cannot delete a channel", 501, "newsletter_unsupported")
        if not ready(s):
            return error("Disconnected", 400)
        try:
            await execute(rq.send_mex, s.client, DELETE_QUERY,
                          {"newsletter_id": channel}, DELETE_FIELD)
        except rq.QueryError as e:
            log.warning("newsletter delete refused: %s", e)
            return error("WhatsApp did not delete the channel", 502)
        return web.json_response(True, status=201)

    r.add_put("/api/{tok}/newsletter/{id}", edit)
    r.add_delete("/api/{tok}/newsletter/{id}", delete)
