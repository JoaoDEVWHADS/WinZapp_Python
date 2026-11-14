"""Group routes that were missing from groups.py: list groups and members,
invitation link, group photo and the settings (only admins send / only admins edit).

None of them is called by the WinZapp client today (grep in client/ finds
nothing), so the response formats follow what WPPConnect Server returns
({status, response}) and the ids come out as WhatsApp Web writes them (@c.us).

The pure functions are at the top (tested in test_groups_extra.py);
`register_routes` wires the routes to the server. No `neonize` nor `aiohttp` at
the top: both only come in inside `register_routes`, so the pure functions can
be tested without them.
"""
import asyncio
import base64
import binascii
import io
import logging
import time

import ephemeral_messages
import msgmap

log = logging.getLogger("bridge")

MAX_PHOTO_SIDE = 640       # WhatsApp Web crops the group photo to 640x640

# WPPConnect property (group-property) -> what neonize knows how to change.
# `ephemeral` has a branch of its own in group_property (ephemeral_messages.py).
# `no_frequently_forwarded` and the member approval/adding modes are not
# included: neonize 0.5.2 has no confirmed call for them.
PROPERTIES = {"announce": "announce", "announcement": "announce",
              "restrict": "locked", "locked": "locked"}


def group_jid(text) -> str:
    """'123-456' / '123-456@g.us' -> '123-456@g.us'. Other servers pass through."""
    text = str(text or "").strip()
    return text if "@" in text else text + "@g.us"


def groups_from_body(body) -> list:
    """The groups the request names: `groupId` or `phone` (text or list)."""
    raw = body.get("groupId")
    if raw in (None, ""):
        raw = body.get("phone")
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = [raw]
    return [group_jid(x) for x in items if x not in (None, "")]


def as_boolean(value, default=True) -> bool:
    """true/false from the JSON or the multipart ('true', 'false', '1', '0')."""
    if value is None or value == "":
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def jid_text_of(jid) -> str:
    """neonize JID -> 'user@server' (empty if there is none)."""
    if jid is None or not getattr(jid, "User", ""):
        return ""
    return "%s@%s" % (jid.User, jid.Server)


def wid_of(text) -> dict:
    """'5511@s.whatsapp.net' -> {server, user, _serialized} (WhatsApp Web's Wid)."""
    serial = msgmap.jid_wpp(text)
    user, _, server = serial.partition("@")
    return {"server": server, "user": user, "_serialized": serial}


def participant_jid(p) -> str:
    """The id that identifies the person: the number when known, else JID, else LID."""
    return (jid_text_of(p.PhoneNumber) or jid_text_of(p.JID)
            or jid_text_of(p.LID))


_MASK = "∙•·*"


def is_masked_number(text) -> bool:
    """'+55∙∙∙∙∙∙∙∙76': what WhatsApp gives as the DisplayName of a member whose
    number is hidden. It is not a name, and the client would file it as one."""
    text = str(text or "")
    if not any(m in text for m in _MASK):
        return False
    rest = "".join(ch for ch in text if ch not in _MASK + "+-() ")
    return rest.isdigit()


def participant_to_wpp(p) -> dict:
    """GroupParticipant -> a row of group-members."""
    row = {"id": wid_of(participant_jid(p)),
           "isAdmin": bool(p.IsAdmin or p.IsSuperAdmin),
           "isSuperAdmin": bool(p.IsSuperAdmin)}
    lid = jid_text_of(p.LID)
    if lid:
        row["lid"] = wid_of(lid)
    if p.DisplayName and not is_masked_number(p.DisplayName):
        row["name"] = p.DisplayName
    return row


def members_to_wpp(info) -> list:
    return [participant_to_wpp(p) for p in info.Participants]


def member_ids(info) -> list:
    return [wid_of(participant_jid(p)) for p in info.Participants]


def administrator_ids(info) -> list:
    return [wid_of(participant_jid(p)) for p in info.Participants
            if p.IsAdmin or p.IsSuperAdmin]


def group_to_chat(info) -> dict:
    """GroupInfo -> a row of all-groups (a group chat with its metadata)."""
    jid = jid_text_of(info.JID)
    owner = jid_text_of(info.OwnerPN) or jid_text_of(info.OwnerJID)
    return {
        "id": wid_of(jid), "name": info.GroupName.Name, "isGroup": True,
        "groupMetadata": {
            "id": wid_of(jid), "subject": info.GroupName.Name,
            "desc": info.GroupTopic.Topic, "owner": wid_of(owner) if owner else None,
            "creation": msgmap.seconds(info.GroupCreated),
            "announce": bool(info.GroupAnnounce.IsAnnounce),
            "restrict": bool(info.GroupLocked.isLocked),
            "participants": members_to_wpp(info)}}


def property_action(property_):
    """'announce' / 'restrict' (and aliases) -> 'announce' / 'locked'; None if
    neonize does not know how to change that property."""
    return PROPERTIES.get(str(property_ or "").strip().lower())


def image_from_body(fields):
    """Bytes of the photo coming from the JSON or the multipart fields: `base64` or
    `path` as plain base64 or data URI. A file path on disk is not read, on
    purpose. Empty if nothing came; ValueError if it is not base64."""
    raw = fields.get("base64") or fields.get("path") or ""
    if not isinstance(raw, str) or not raw.strip():
        return b""
    try:
        return base64.b64decode(raw.strip().split(",", 1)[-1], validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("the photo is not base64")


def photo_to_jpeg(data: bytes) -> bytes:
    """WhatsApp only accepts JPEG as a group photo: converts (PNG, WebP...) and
    shrinks the longer side to 640. An already small JPEG passes without
    recompression."""
    from PIL import Image
    image = Image.open(io.BytesIO(data))
    if image.format == "JPEG" and max(image.size) <= MAX_PHOTO_SIDE:
        return data
    image = image.convert("RGB")
    image.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


def register_routes(r, *, session, ok, jid_from_text, jid_text, qr_data_url):
    """Wire the routes to the aiohttp router `r`. Same arguments as
    groups.register_routes (not all of them are used here)."""
    from aiohttp import web
    from groups import not_administrator

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    def error(message, status=500):
        return web.json_response({"status": "error", "message": str(message)}, status=status)

    def connected(s):
        return s.client is not None and s.status == "CONNECTED"

    def failure(e, name):
        if not_administrator(e):
            return error("not an administrator", 403)
        log.exception(name)
        return error(e)

    async def group_info(req, name):
        """(info, None) or (None, error response)."""
        s = session(req)
        if not connected(s):
            return None, error("Disconnected", 400)
        try:
            return await execute(s.client.get_group_info,
                                 jid_from_text(group_jid(req.match_info["groupId"]))), None
        except Exception as e:
            log.info("%s: %s", name, type(e).__name__)
            return None, error(e, 404)

    async def all_groups(req):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        try:
            groups = await execute(s.client.get_joined_groups)
        except Exception as e:
            log.exception("all-groups")
            return error(e)
        return ok(status="success", response=[group_to_chat(g) for g in groups])

    async def group_members(req):
        info, failed = await group_info(req, "group-members")
        return failed or ok(status="success", response=members_to_wpp(info))

    async def group_members_ids(req):
        info, failed = await group_info(req, "group-members-ids")
        return failed or ok(status="success", response=member_ids(info))

    async def group_admins(req):
        info, failed = await group_info(req, "group-admins")
        return failed or ok(status="success", response=administrator_ids(info))

    async def group_link(req, revoke):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        try:
            link = await execute(s.client.get_group_invite_link,
                                 jid_from_text(group_jid(req.match_info["groupId"])), revoke)
        except Exception as e:
            return failure(e, "group-invite-link")
        return ok(status="success", response=link)

    async def group_invite_link(req):
        return await group_link(req, False)

    async def group_revoke_link(req):
        return await group_link(req, True)

    async def adjust(req, name, field, action=None):
        """Turns a permission on/off in all the groups of the request. `action` is
        'announce' or 'locked'; without it comes from the `property` field (group-property)."""
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        body = await req.json()
        action = action or property_action(body.get("property"))
        if action is None:
            return error("unsupported group property: %s" % body.get("property"), 400)
        targets = groups_from_body(body)
        if not targets:
            return error("groupId is required", 400)
        func = getattr(s.client, "set_group_" + action)
        value = as_boolean(body.get(field), True)
        try:
            for target in targets:
                await execute(func, jid_from_text(target), value)
        except Exception as e:
            return failure(e, name)
        return ok(status="success", response={})

    async def ephemeral_group(req, body):
        """property=ephemeral: `value` in seconds (0 turns it off) or boolean."""
        s = session(req)
        try:
            seconds = ephemeral_messages.timer_seconds(body.get("value"))
        except ValueError as e:
            return error(e, 400)
        targets = groups_from_body(body)
        if not targets:
            return error("groupId is required", 400)
        if not connected(s):
            return error("Disconnected", 400)
        try:
            for target in targets:
                await execute(ephemeral_messages.apply_timer, s.client,
                              jid_from_text(target), seconds, time.time(), s)
        except Exception as e:
            return failure(e, "group-property")
        return ok(status="success", response={})

    async def group_property(req):
        body = await req.json()
        if ephemeral_messages.is_ephemeral_property(body.get("property")):
            return await ephemeral_group(req, body)
        return await adjust(req, "group-property", "value")

    async def messages_admins_only(req):
        return await adjust(req, "messages-admins-only", "value", "announce")

    async def change_privacy_group(req):
        return await adjust(req, "change-privacy-group", "status", "announce")

    async def group_pic(req):
        s = session(req)
        if not connected(s):
            return error("Disconnected", 400)
        fields, file = {}, b""
        if req.content_type.startswith("multipart/"):
            reader = await req.multipart()
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.filename is not None:
                    file = await part.read(decode=False)
                else:
                    fields[part.name] = await part.text()
        else:
            fields = await req.json()
        targets = groups_from_body(fields)
        if not targets:
            return error("groupId is required", 400)
        try:
            data = file or image_from_body(fields)
        except ValueError as e:
            return error(e, 400)
        if not data:
            return error("the image is required", 400)
        try:
            jpeg = await execute(photo_to_jpeg, data)
        except Exception:
            return error("the file is not a valid image", 400)
        ids = []
        try:
            for target in targets:
                ids.append(await execute(s.client.set_group_photo, jid_from_text(target), jpeg))
        except Exception as e:
            return failure(e, "group-pic")
        return ok(status="success", response={"pictureId": ids[0] if len(ids) == 1 else ids})

    r.add_get("/api/{tok}/all-groups", all_groups)
    r.add_get("/api/{tok}/group-members/{groupId}", group_members)
    r.add_get("/api/{tok}/group-members-ids/{groupId}", group_members_ids)
    r.add_get("/api/{tok}/group-admins/{groupId}", group_admins)
    r.add_get("/api/{tok}/group-invite-link/{groupId}", group_invite_link)
    r.add_get("/api/{tok}/group-revoke-link/{groupId}", group_revoke_link)
    r.add_post("/api/{tok}/group-property", group_property)
    r.add_post("/api/{tok}/messages-admins-only", messages_admins_only)
    r.add_post("/api/{tok}/change-privacy-group", change_privacy_group)
    r.add_post("/api/{tok}/group-pic", group_pic)
