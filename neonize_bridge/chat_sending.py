"""Routes for sending message types that the client does not send through
send-file: location, link with preview, sticker (and animated sticker), image
and file in base64 and voice note in base64. All of them answer like
`send-message` (server.py's `store_sent`), the format WinZapp reads.

Nothing here was tested against a real account: neonize does not install
outside Windows. The signatures match the neonize 0.5.2 source code
(send_message, build_sticker_message); audio is built by audio_message.py.

The pure functions are at the top (tested in test_chat_sending.py);
`register_routes` wires the routes to the server.
"""
import base64
import binascii
import logging
import mimetypes
import re

import responses

log = logging.getLogger("bridge")

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
_DATA_URI = re.compile(r"^data:([^;,]*)(?:;[^,]*)?,", re.IGNORECASE)


def coordinates(lat, lng):
    """(latitude, longitude) as numbers within the limits, or ValueError."""
    try:
        a, o = float(lat), float(lng)
    except (TypeError, ValueError):
        raise ValueError("lat and lng must be numbers") from None
    if not (-90 <= a <= 90 and -180 <= o <= 180):
        raise ValueError("lat/lng out of range")
    return a, o


def base64_data(text):
    """'data:<mime>;base64,<data>' or just the data -> (bytes, mime). The mime
    is '' when it did not come. ValueError if it is not base64."""
    text = str(text or "").strip()
    found = _DATA_URI.match(text)
    mime = found.group(1).lower() if found else ""
    if found:
        text = text[found.end():]
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("invalid base64") from None
    if not data:
        raise ValueError("empty file")
    return data, mime


def file_source(text):
    """The bytes neonize receives as a file, from a base64 or data URI.
    URL (http/https/ftp/file...) and disk path are refused: neonize downloads
    the URL and opens the path inside the user's machine (loopback, internal
    network, cloud metadata; local files) and forwards the result to a contact.
    The client never sends a URL to these routes, so there is nothing to
    preserve."""
    text = str(text or "").strip()
    if _SCHEME.match(text):
        raise ValueError("url sources are not supported: send base64 or a data URI")
    return base64_data(text)


def file_kind(mime, name=""):
    """'image' | 'video' | 'audio' | 'document', by the mime or, without it, by
    the file name."""
    mime = (mime or mimetypes.guess_type(name or "")[0] or "").lower()
    base = mime.split("/")[0]
    return base if base in ("image", "video", "audio") else "document"


def with_group(phone, group):
    """A number without '@' becomes a group JID when the route says isGroup."""
    phone = phone[0] if isinstance(phone, list) else phone
    phone = str(phone or "")
    return phone + "@g.us" if group and "@" not in phone else phone


def register_routes(r, *, session, ok, error, destination_of, store_sent, send_media,
                    quoted_context, in_thread):
    """Wire the send routes to the aiohttp router `r`."""
    def connected(s):
        return s.client is not None and s.status == "CONNECTED"

    async def send(req, name, build):
        """JSON body -> `build(s, body, destination)` (runs on a thread and returns
        neonize's SendResponse) -> response in the send-message format."""
        s = session(req)
        try:
            body = await req.json()
            destination = destination_of(with_group(body["phone"], body.get("isGroup")))
            prepared = build(s, body, destination)
        except (KeyError, ValueError) as e:
            return error("invalid request: %s" % e, 400)
        if not connected(s):
            return responses.disconnected()
        try:
            resp = await in_thread(prepared)
        except Exception as e:
            log.exception(name)
            return error(e)
        return store_sent(s, destination, resp)

    def quoted_ctx(s, body):
        quoted = body.get("quotedMessageId")
        return quoted_context(s, quoted) if quoted else None

    async def send_location(req):
        def build(s, body, destination):
            lat, lng = coordinates(body["lat"], body["lng"])
            from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import LocationMessage, Message
            message = Message(locationMessage=LocationMessage(
                degreesLatitude=lat, degreesLongitude=lng,
                name=str(body.get("title") or body.get("name") or ""),
                address=str(body.get("address") or "")))
            return lambda: s.client.send_message(destination, message)
        return await send(req, "send-location", build)

    async def send_link_preview(req):
        # neonize generates the card by fetching the page (and the og:image
        # image) from the user's machine, from a URL chosen by whoever calls: the
        # same SSRF as the stickers. WinZapp does not use this route.
        return error("link previews are not available through neonize: it would fetch "
                     "the page from this machine", 501)

    def sticker(animated):
        def build_with(s, body, destination):
            source, _ = file_source(body.get("path") or body["base64"])
            return lambda: s.client.send_sticker(destination, source, animated_gif=animated)
        return build_with

    async def send_sticker(req):
        return await send(req, "send-sticker", sticker(False))

    async def send_sticker_gif(req):
        return await send(req, "send-sticker-gif", sticker(True))

    async def send_image(req):
        def build(s, body, destination):
            data, _ = base64_data(body["base64"])
            ctx = quoted_ctx(s, body)
            return lambda: send_media(s, destination, "image", data,
                                      body.get("caption") or body.get("message") or "",
                                      body.get("filename") or "", "", False, ctx)
        return await send(req, "send-image", build)

    async def send_file_base64(req):
        def build(s, body, destination):
            data, mime = base64_data(body["base64"])
            name = body.get("filename") or ""
            mime = mime or mimetypes.guess_type(name)[0] or ""
            ctx = quoted_ctx(s, body)
            return lambda: send_media(s, destination, file_kind(mime, name), data,
                                      body.get("caption") or body.get("message") or "",
                                      name, mime, bool(body.get("isPtt")), ctx)
        return await send(req, "send-file-base64", build)

    async def send_voice(req):
        def build(s, body, destination):
            source, _ = file_source(body["path"])
            ctx = quoted_ctx(s, body)
            return lambda: send_media(s, destination, "audio", source, "", "", "", True, ctx)
        return await send(req, "send-voice", build)

    p = "/api/{tok}/"
    r.add_post(p + "send-location", send_location)
    r.add_post(p + "send-link-preview", send_link_preview)
    r.add_post(p + "send-sticker", send_sticker)
    r.add_post(p + "send-sticker-gif", send_sticker_gif)
    r.add_post(p + "send-image", send_image)
    r.add_post(p + "send-file-base64", send_file_base64)
    r.add_post(p + "send-voice", send_voice)
