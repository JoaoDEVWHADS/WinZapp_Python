"""Presence in the bridge: who is online, when they were last seen and who is
typing or recording audio.

WhatsApp only delivers presence by event (and only of whoever the account
subscribed to with `subscribe-presence`), so the bridge keeps each person's
last event in a small memory and answers `last-seen/:phone` and
`chat-is-online/:phone` from it. neonize brings two events: `PresenceEv` (From,
Unavailable, LastSeen) and `ChatPresenceEv` (MessageSource, State, Media). The
formats emitted are the ones the client reads in core/websocket_client.py
(`onpresencechanged`) and those of the response, the ones in
core/contact_presence.py (`response_snapshot`).

Privacy: when the person hides their last seen, whatsmeow delivers a zeroed
`LastSeen`. That does not tell "offline" from "online but hidden", so the
`last-seen` route answers `unsupported` (the client does not insist) instead
of claiming "offline". Nothing here logs a number, JID or name.

The pure functions are at the top (tested in test_presence.py);
`register_routes` wires the `chat-is-online` route and `register_events` wires
neonize's events to a session. Nothing here was proven against a real account.
"""
import logging
import time

from aiohttp import web

import msgmap
from groups import number_forms

log = logging.getLogger("bridge")

# How long each fact is worth. "Online" goes away on its own (the "offline"
# notice is not guaranteed); "offline" with a last seen ages slowly; typing and
# recording last only a few seconds (the "stopped" notice may not arrive either).
ONLINE_TTL = 300
OFFLINE_TTL = 3600
ACTIVITY_TTL = 25
MAX_PEOPLE = 2000

# ChatPresence.State and ChatPresenceMedia of the neonize proto.
STATE_TYPING, STATE_PAUSED = 1, 2
MEDIA_AUDIO = 2


def key(jid) -> str:
    """The id the route receives ('5511999', '5511999@c.us', 'x:12@s.whatsapp.net',
    'x@lid') -> the memory key ('5511999@c.us'). '' if empty."""
    text = str(jid or "")
    if not text:
        return ""
    if "@" not in text:
        text += "@c.us"
    return msgmap.jid_wpp(text)


def equivalent_keys(k) -> list:
    """The key and, for a Brazilian mobile (`@c.us`), its other form (with or
    without the 9th digit). A LID stays as it came: its digits are not a phone."""
    user, _, server = str(k or "").partition("@")
    if not k:
        return []
    if server != "c.us" or not user.isdigit():
        return [k]
    return [f"{u}@c.us" for u in number_forms(user)]


def person_keys(primary, alternative="") -> list:
    """The keys under which a person is stored: the event's JID and, if
    whatsmeow/the bridge knew the pair (number <-> LID), the other. No repeats."""
    found = []
    for jid in (primary, alternative):
        k = key(jid)
        if k and k not in found:
            found.append(k)
    return found


def seen_from(ts):
    """PresenceEv's LastSeen -> seconds, or None when it comes zeroed/negative
    (the person hides their last seen)."""
    t = msgmap.seconds(ts)
    return t if t > 0 else None


def activity_state(state, media) -> str:
    """(State, Media) of ChatPresenceEv -> 'composing' | 'recording' | 'paused'
    (the values the client understands); '' if the state is not known."""
    if state == STATE_TYPING:
        return "recording" if media == MEDIA_AUDIO else "composing"
    if state == STATE_PAUSED:
        return "paused"
    return ""


class Presences:
    """Presence memory in RAM. Time always comes from outside (`now`, seconds)."""

    def __init__(self):
        self._people = {}       # key -> {"online", "seen", "at"}
        self._activity = {}     # (chat, who) -> (state, at)

    def _prune(self, now):
        self._activity = {k: v for k, v in self._activity.items()
                          if now - v[1] < ACTIVITY_TTL}
        excess = len(self._people) - MAX_PEOPLE
        if excess > 0:
            oldest = sorted(self._people, key=lambda k: self._people[k]["at"])[:excess]
            for k in oldest:
                del self._people[k]

    def set_presence(self, keys, online, seen, now):
        """Stores the last PresenceEv. `seen`: seconds, or None if hidden."""
        record = {"online": bool(online), "seen": seen or None, "at": now}
        for k in keys:
            self._people[k] = record
        self._prune(now)

    def set_activity(self, chat, who, state, now):
        """Stores typing/recording of `who` in `chat`; 'paused' clears it."""
        if state in ("composing", "recording"):
            self._activity[(chat, who)] = (state, now)
        else:
            self._activity.pop((chat, who), None)
        self._prune(now)

    def read(self, person_id, now):
        """What is known about a person now, or None if nothing is worth any
        more: {"state", "isOnline", "lastSeen"}. Recent typing/recording counts
        as online (the person has the chat open). A Brazilian mobile may be
        stored with or without the 9th digit: tries both forms."""
        for k in equivalent_keys(key(person_id)):
            snapshot = self._read_key(k, now)
            if snapshot is not None:
                return snapshot
        return None

    def _read_key(self, k, now):
        act = self._activity.get((k, k))
        if act and now - act[1] < ACTIVITY_TTL:
            return {"state": act[0], "isOnline": True, "lastSeen": None}
        record = self._people.get(k)
        if record is None:
            return None
        if record["online"]:
            if now - record["at"] >= ONLINE_TTL:
                return None
            return {"state": "available", "isOnline": True, "lastSeen": None}
        if now - record["at"] >= OFFLINE_TTL:
            return None
        return {"state": "unavailable", "isOnline": False, "lastSeen": record["seen"]}


def presence_event(wpp_id, online, seen, now) -> dict:
    """PresenceEv -> a person's `onpresencechanged`. `snapshotStatus: ready`
    only when the data is complete (online, or offline with the last seen):
    with the last seen hidden the client does not yet know it was really offline."""
    event = {
        "id": wpp_id, "state": "available" if online else "unavailable",
        "isOnline": bool(online), "t": int(now),
        "isGroup": False, "isUser": True}
    if not online and seen:
        event["lastSeen"] = seen
    if online or seen:
        event["snapshotStatus"] = "ready"
    return event


def activity_event(chat_wpp, who_wpp, state, now, group) -> dict:
    """ChatPresenceEv -> the `onpresencechanged`. In a group the state goes per
    participant; in a private chat, in the event itself (without claiming
    online/offline)."""
    if group:
        return {
            "id": chat_wpp, "state": state, "t": int(now), "isOnline": False,
            "isGroup": True, "isUser": False, "shortName": "",
            "participants": [{"id": who_wpp, "state": state, "shortName": ""}]}
    event = {"id": chat_wpp, "state": state, "t": int(now),
             "isGroup": False, "isUser": True}
    if state in ("composing", "recording"):
        event["isOnline"] = True
    return event


def last_seen_response(snapshot) -> dict:
    """The response fields of `last-seen/:phone` for what `Presences.read`
    returned. `unsupported` with no data or with the last seen hidden."""
    if snapshot is None or (not snapshot["isOnline"] and not snapshot["lastSeen"]):
        return {"response": False, "presence": {"status": "unsupported"}}
    return {"response": snapshot["lastSeen"] or False, "presence": {
        "status": "ready", "isOnline": snapshot["isOnline"],
        "lastSeen": snapshot["lastSeen"], "state": snapshot["state"]}}


def online_response(snapshot) -> dict:
    """The response fields of `chat-is-online/:phone` (WPPConnect returns just
    a boolean). With no data, False."""
    response = {"response": bool(snapshot and snapshot["isOnline"])}
    if snapshot is None:
        response["presence"] = {"status": "unsupported"}
    return response


def _jid_text(jid) -> str:
    if jid is None or not getattr(jid, "User", ""):
        return ""
    return f"{jid.User}@{jid.Server}"


def register_events(cli, s):
    """Wires the neonize client's `cli` PresenceEv and ChatPresenceEv to the
    session `s` (needs `s.name` and `s.emit`). Called on neonize's thread."""
    import neonize.events as nev

    s.presences = Presences()

    def pair(c, jid):
        """The other JID of the same person (number <-> LID), or '' if unknown."""
        try:
            if jid.Server == "lid":
                return _jid_text(c.get_pn_from_lid(jid))
            if jid.Server == "s.whatsapp.net":
                return _jid_text(c.get_lid_from_pn(jid))
        except Exception:
            pass
        return ""

    def preferred(c, jid):
        """(the id to show the app, the memory keys): the number before the LID."""
        primary = _jid_text(jid)
        other = pair(c, jid)
        show = primary
        if primary.endswith("@lid") and other and not other.endswith("@lid"):
            show = other
        return msgmap.jid_wpp(show), person_keys(primary, other)

    @cli.event(nev.PresenceEv)
    def _presence(c, e):
        try:
            now = time.time()
            wpp_id, keys = preferred(c, e.From)
            if not keys:
                return
            seen = seen_from(e.LastSeen)
            s.presences.set_presence(keys, not e.Unavailable, seen, now)
            log.info("presence received (online=%s seen=%s)", not e.Unavailable, bool(seen))
            s.emit("onpresencechanged", {
                "session": s.name,
                **presence_event(wpp_id, not e.Unavailable, seen, now)})
        except Exception:
            log.exception("presence")

    @cli.event(nev.ChatPresenceEv)
    def _activity(c, e):
        try:
            source = e.MessageSource
            if source.IsFromMe:
                return
            state = activity_state(e.State, e.Media)
            if not state:
                return
            now = time.time()
            group = bool(source.IsGroup)
            chat_wpp, chat_keys = preferred(c, source.Chat)
            if not chat_keys:
                return
            if group:
                who_wpp, who_keys = preferred(c, source.Sender)
                if not who_wpp:
                    return
                for k in who_keys:
                    s.presences.set_activity(chat_keys[0], k, state, now)
            else:
                who_wpp = chat_wpp
                for k in chat_keys:
                    s.presences.set_activity(k, k, state, now)
            log.info("activity received (%s group=%s)", state, group)
            s.emit("onpresencechanged", {
                "session": s.name,
                **activity_event(chat_wpp, who_wpp, state, now, group)})
        except Exception:
            log.exception("activity")


def register_routes(r, *, session, ok):
    """Wire `chat-is-online/:phone` to the aiohttp router `r`."""
    from profile_privacy import valid_person_id

    async def chat_is_online(req):
        if not valid_person_id(req.match_info["phone"]):
            return web.json_response(
                {"status": "error", "response": "Invalid contact id"}, status=400)
        memory = getattr(session(req), "presences", None)
        snapshot = memory.read(req.match_info["phone"], time.time()) if memory else None
        return ok(status="success", **online_response(snapshot))

    r.add_get("/api/{tok}/chat-is-online/{phone}", chat_is_online)
