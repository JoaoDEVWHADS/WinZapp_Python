"""Server upkeep and leftovers of WPPConnect's API: `unhealthy`,
`collect-page-garbage`, `profile/:phone` and `chatwoot`.

- `unhealthy` answers 503, as the reference server does, but does not end the
  process: the reference server exits there (it serves to test an
  orchestrator), and here one process holds every account, and any page open
  in the browser can send a plain GET to 127.0.0.1;
- `collect-page-garbage` collects the bridge's own garbage (there is no page)
  and answers the process's memory before and after, in the fields
  core/page_heap.py reads (`before`, `after`, `tookMs`);
- `profile/:phone` is the deprecated getNumberProfile: what check-number-status
  answers for the number;
- `chatwoot` takes Chatwoot's webhook as WPPConnect's DeviceController.chatWoot
  does: an outgoing message of a conversation goes to the contact's number,
  its text as text and each attachment (an http(s) URL Chatwoot gives) as a
  file; status changes and private notes are acknowledged and dropped.

The pure functions are at the top (tested in test_maintenance.py).
"""
import asyncio
import gc
import logging
import os
import tempfile
import time

from aiohttp import web

log = logging.getLogger("bridge")

MAX_ATTACHMENT = 64 * 1024 * 1024
DROPPED_EVENTS = ("conversation_status_changed", "conversation_resolved")


def process_memory():
    """Bytes of memory the process holds (its working set on Windows), or None."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t),
                            ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters),
                                                        counters.cb):
                return int(counters.WorkingSetSize)
            return None
        import resource
        return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:
        return None


def collect(memory=process_memory, clock=time.perf_counter) -> dict:
    before, started = memory(), clock()
    gc.collect()
    return {"before": before, "after": memory(), "tookMs": round((clock() - started) * 1000, 1)}


def chatwoot_plan(body) -> dict:
    """What a Chatwoot webhook asks for: {"drop": True} or
    {"phone", "text", "attachments": [{"url", "kind"}]}."""
    body = body if isinstance(body, dict) else {}
    if body.get("event") in DROPPED_EVENTS or body.get("private") or body.get("is_private"):
        return {"drop": True}
    if body.get("message_type") != "outgoing":
        return {"drop": True}
    try:
        phone = body.get("phone") or body["conversation"]["meta"]["sender"]["phone_number"]
    except (KeyError, TypeError):
        return {"drop": True}
    phone = "".join(ch for ch in str(phone) if ch.isdigit())
    if not phone:
        return {"drop": True}
    message = body.get("message")
    if not isinstance(message, dict):
        try:
            message = body["conversation"]["messages"][0]
        except (KeyError, IndexError, TypeError):
            message = {}
    attachments = []
    for item in message.get("attachments") or ():
        url = str((item or {}).get("data_url") or "")
        if url.startswith(("http://", "https://")):
            attachments.append({"url": url, "kind": "audio" if item.get("file_type") == "audio"
                                else "image" if item.get("file_type") == "image" else "document"})
    return {"phone": phone, "text": str(message.get("content") or body.get("content") or ""),
            "attachments": attachments}


def register_routes(r, *, session, ok, destination_of, store_sent, send_media):
    """Wire the routes to the aiohttp router `r`."""
    import contacts
    from groups import number_forms

    async def execute(func, *args):
        return await asyncio.get_running_loop().run_in_executor(None, func, *args)

    async def unhealthy(req):
        return web.Response(status=503)

    async def collect_page_garbage(req):
        session(req)
        return ok(status="success", response=await execute(collect))

    async def profile(req):
        s = session(req)
        digits = "".join(ch for ch in req.match_info["phone"].split("@")[0] if ch.isdigit())
        if s.client is None or s.status != "CONNECTED":
            return web.json_response({"status": "error", "message": "Disconnected"}, status=400)
        if len(digits) < 8:
            return ok(status="success", response=contacts.number_response(digits, None))
        try:
            responses = await execute(s.client.is_on_whatsapp,
                                      *["+" + f for f in number_forms(digits)])
        except Exception:
            log.exception("profile")
            return web.json_response({"status": "error", "message": "Error on get number profile"},
                                     status=500)
        found = contacts.found_in_query(responses)
        return ok(status="success", response=contacts.number_response(digits, found))

    def download(url):
        import requests
        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            handle, path = tempfile.mkstemp(prefix="chatwoot-")
            size = 0
            with os.fdopen(handle, "wb") as out:
                for block in response.iter_content(65536):
                    size += len(block)
                    if size > MAX_ATTACHMENT:
                        raise ValueError("attachment too large")
                    out.write(block)
            return path, response.headers.get("Content-Type", "")

    async def chatwoot(req):
        s = session(req)
        if s.client is None or s.status != "CONNECTED":
            return web.json_response({"status": "error", "message": "Disconnected"}, status=400)
        try:
            body = await req.json()
        except ValueError:
            body = {}
        plan = chatwoot_plan(body)
        if plan.get("drop"):
            return ok(status="success", message="Success on receive chatwoot")
        destination = destination_of(plan["phone"])
        try:
            if not plan["attachments"] and plan["text"]:
                from neonize.proto.waE2E.WAWebProtobufsE2E_pb2 import Message
                resp = await execute(s.client.send_message, destination,
                                     Message(conversation=plan["text"]))
                store_sent(s, destination, resp)
            for item in plan["attachments"]:
                path, mime = await execute(download, item["url"])
                try:
                    resp = await execute(send_media, s, destination, item["kind"], path,
                                         plan["text"], os.path.basename(item["url"]),
                                         mime, item["kind"] == "audio")
                    store_sent(s, destination, resp)
                finally:
                    os.remove(path)
        except Exception:
            log.exception("chatwoot")
            return web.json_response({"status": "error", "message": "Error on receive chatwoot"},
                                     status=400)
        return ok(status="success", message="Success on receive chatwoot")

    r.add_get("/unhealthy", unhealthy)
    r.add_post("/api/{tok}/collect-page-garbage", collect_page_garbage)
    r.add_get("/api/{tok}/profile/{phone}", profile)
    r.add_post("/api/{tok}/chatwoot", chatwoot)
