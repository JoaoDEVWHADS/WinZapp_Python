"""Group receipts: the tick of a message of ours only advances when ALL the
recipients have got there.

Before, the first receipt from any member became `onack` 2/3/4 and the app
marked the message as "read" as soon as ONE person read it. Here a group's ack is:

- 2 (delivered): all the recipients sent some receipt;
- 3 (read): all sent a read or play receipt;
- 4 (played): all sent a play receipt;
- 1 (sent) meanwhile. A one-person chat does not go through here.

Recipients = group participants minus the account itself, and only those who
were already in the group when the message went out (`Member.since`, known only
for whoever joined while the bridge was listening; whoever came from
GetGroupInfo always counts). Each person can have two addresses (number and
LID, and the Brazilian number with and without the 9th digit): two addresses
that intersect are the same person. A receipt from someone who is not a
recipient (left, joined later, and myself) is ignored.

GUESS, not verified with a real account: whoever turned off read confirmation
sends "delivered" but never "read". If everyone waited for them, the message
would never turn blue. So whoever delivered and let `grace` seconds pass
without reading stops holding back ack 3 (as long as at least one person
really read). Ack 4 has no such leeway: a voice note only becomes "played" when
everyone played it. There is no timer: the leeway is reevaluated at each new
receipt, in message-ack and in get-messages.

The pure functions are at the top (test_group_receipts.py); `GroupReceipts` is
the part of `Session` that keeps the member list and talks to neonize.
"""
import collections
import logging
import threading
import time
from dataclasses import dataclass, field

import msgmap
from groups import number_forms
from redaction import redact

log = logging.getLogger("bridge")

#: seconds after which whoever only delivered (without reading) stops holding back ack 3. A guess.
READ_GRACE = 600
#: after this the cached member list is fetched again (GetGroupInfo)
ROSTER_TTL = 6 * 3600
#: how many messages remember the highest ack already emitted
ACK_LIMIT = 5000

STAGES = ("delivered", "read", "played")


# ----------------------------------------------------------------- addresses
def _normalize(text):
    """'x:12@c.us' -> 'x@s.whatsapp.net'; '' if it is not an address."""
    user, at_sign, server = str(text or "").partition("@")
    user = user.split(":")[0]
    if not user or not at_sign or not server:
        return ""
    if server == "c.us":
        server = "s.whatsapp.net"
    return f"{user}@{server}"


def keys_of(*addresses):
    """All the comparable forms of ONE person's addresses: without device,
    @c.us equal to @s.whatsapp.net and, on a Brazilian mobile, with and without
    the 9th digit."""
    keys = set()
    for address in addresses:
        base = _normalize(address)
        if not base:
            continue
        user, _, server = base.partition("@")
        if server == "s.whatsapp.net" and user.isdigit():
            keys.update(f"{form}@{server}" for form in number_forms(user))
        else:
            keys.add(base)
    return frozenset(keys)


@dataclass(frozen=True)
class Member:
    """A group participant: `id` (number @c.us when known, otherwise the
    LID) and all the `keys` under which it can appear in a receipt."""
    id: str
    keys: frozenset = field(compare=False)
    since: int = 0      # seconds when they joined, seen live; 0 = not known


def _preferred_id(phone, jid, lid):
    chosen = phone or (jid if jid and not jid.endswith("@lid") else "") or lid or jid
    return msgmap.jid_wpp(chosen)


def member_from_participant(p, text):
    """neonize `GroupInfo` participant -> Member (or None without an address).
    `text(jid)` returns 'user@server'."""
    phone = text(getattr(p, "PhoneNumber", None))
    jid = text(getattr(p, "JID", None))
    lid = text(getattr(p, "LID", None))
    keys = keys_of(phone, jid, lid)
    if not keys:
        return None
    return Member(_preferred_id(phone, jid, lid), keys)


def member_from_address(address, other="", since=0):
    """Member from an address (of a group event) and, if known, the same
    person's other address."""
    keys = keys_of(address, other)
    if not keys:
        return None
    addresses = [e for e in (address, other) if e]
    phone = next((e for e in addresses if not e.endswith("@lid")), "")
    lid = next((e for e in addresses if e.endswith("@lid")), "")
    return Member(_preferred_id(phone, "", lid), keys, int(since or 0))


# --------------------------------------------------------------- cached list
class Roster:
    """The members of each group, kept between messages. Safe across threads."""

    def __init__(self, ttl=ROSTER_TTL):
        self.ttl = ttl
        self._groups = {}       # group -> (members, instant)
        self._lock = threading.RLock()

    def define(self, group, members, now):
        """Replaces the whole list (GetGroupInfo). Whoever was already known keeps
        the `since` they had: the new list does not know when anyone joined."""
        with self._lock:
            old = self._groups.get(group, ([], 0))[0]
            new = []
            for m in members:
                if not m.since:
                    previous = next((a for a in old if a.since and a.keys & m.keys), None)
                    if previous:
                        m = Member(m.id, m.keys, previous.since)
                new.append(m)
            self._groups[group] = (new, now)

    def members(self, group):
        """The list (even if old) or None if the group was never loaded."""
        with self._lock:
            found = self._groups.get(group)
            return list(found[0]) if found else None

    def stale(self, group, now):
        with self._lock:
            found = self._groups.get(group)
            return found is None or now - found[1] >= self.ttl

    def joined(self, group, member):
        """Someone joined. Group not yet loaded: nothing to do (the full load,
        later, already brings them)."""
        with self._lock:
            found = self._groups.get(group)
            if found is None or member is None:
                return
            members = [m for m in found[0] if not (m.keys & member.keys)]
            members.append(member)
            self._groups[group] = (members, found[1])

    def left(self, group, keys):
        with self._lock:
            found = self._groups.get(group)
            if found is None or not keys:
                return
            self._groups[group] = ([m for m in found[0] if not (m.keys & keys)], found[1])

    def invalidate(self, group):
        with self._lock:
            self._groups.pop(group, None)


# ---------------------------------------------------------------- evaluation
Result = collections.namedtuple("Result", "ack expected delivered reads plays rows")


def recipients(members, my_keys, message_instant=0):
    """Who should receive a message of ours: the members minus my account
    and minus whoever joined after it."""
    return [m for m in members
            if not (m.keys & my_keys)
            and not (message_instant and m.since and m.since > message_instant)]


def _find(index, who, resolver, memory):
    keys = keys_of(who)
    for c in keys:
        if c in index:
            return index[c]
    if resolver is None:
        return None
    if who not in memory:
        try:
            memory[who] = resolver(who) or ""
        except Exception:
            memory[who] = ""
    for c in keys_of(memory[who]):
        if c in index:
            return index[c]
    return None


def evaluate(expected, receipts, now, grace=READ_GRACE, resolver=None):
    """Receipts [(who, stage, ts)] of a message of ours in a group -> Result.

    `expected` comes from `recipients`; `resolver(address)` (optional) returns
    the person's other address when the receipts and the list do not intersect.
    `ack` is 1..4 as per the module (1 also without recipients). `rows` are
    only the recipients' receipts, with `who` replaced by the member's `id`:
    one row per person even if they answered through two addresses."""
    index = {}
    for i, m in enumerate(expected):
        for c in m.keys:
            index.setdefault(c, i)
    by_person = [dict() for _ in expected]    # stage -> lowest ts
    rows, memory = [], {}
    for who, stage, ts in receipts:
        if stage not in STAGES:
            continue
        i = _find(index, who, resolver, memory)
        if i is None:
            continue
        ts = int(ts or 0)
        seen = by_person[i].get(stage)
        if seen is None or (ts and (not seen or ts < seen)):
            by_person[i][stage] = ts
        rows.append((expected[i].id, stage, ts))

    delivered = reads = plays = unread_grace = 0
    for stages in by_person:
        if not stages:
            continue
        delivered += 1
        if "read" in stages or "played" in stages:
            reads += 1
        else:
            times = [t for t in stages.values() if t]
            if times and now - min(times) >= grace:
                unread_grace += 1
        if "played" in stages:
            plays += 1

    n = len(expected)
    ack = 1
    if n and delivered == n:
        ack = 2
        if reads >= 1 and reads + unread_grace == n:
            ack = 3
        if plays == n:
            ack = 4
    return Result(ack, n, delivered, reads, plays, rows)


# -------------------------------------------------------------- group events
def apply_event(roster, group, e, now, text, other_address=None):
    """GroupInfoEv -> joins and leaves in the list of `group`. `text(jid)` ->
    'user@server'; `other_address(address)` -> the other address or ''."""
    since = now
    try:
        since = msgmap.seconds(e.Timestamp) or now
    except Exception:
        pass

    def pair(address):
        try:
            return (other_address(address) or "") if other_address else ""
        except Exception:
            return ""

    for jid in getattr(e, "Leave", ()):
        address = text(jid)
        roster.left(group, keys_of(address, pair(address)))
    for jid in getattr(e, "Join", ()):
        address = text(jid)
        roster.joined(group, member_from_address(address, pair(address), since))


# ------------------------------------------------------------------- session
def _text(jid):
    if jid is None or not getattr(jid, "User", ""):
        return ""
    return f"{jid.User}@{jid.Server}"


class _State:
    def __init__(self):
        self.roster = Roster()
        self.acks = collections.OrderedDict()   # message id -> highest ack emitted
        self.lock = threading.Lock()


class GroupReceipts:
    """`Session` methods for the ack of group messages (uses self.db,
    self.client, self.status, self.me, self.lid and _other_address)."""

    def _receipt_state(self):
        state = self.__dict__.get("_receipt_state_data")
        if state is None:
            state = self.__dict__.setdefault("_receipt_state_data", _State())
        return state

    def _my_keys(self):
        return keys_of(self.me, self.lid)

    def _resolve_address(self, address):
        return self._other_address(msgmap.jid_whatsmeow(address))

    # --- member list
    def roster_register(self, info, now=None):
        """neonize `GroupInfo` (get_joined_groups, get_group_info, JoinedGroupEv)."""
        group = msgmap.jid_whatsmeow(_text(getattr(info, "JID", None)))
        if not group.endswith("@g.us"):
            return
        members = [m for m in (member_from_participant(p, _text)
                               for p in getattr(info, "Participants", ())) if m]
        if members:
            self._receipt_state().roster.define(group, members, now or time.time())

    def roster_changed(self, e, now=None):
        """GroupInfoEv: who joined and who left."""
        group = msgmap.jid_whatsmeow(_text(getattr(e, "JID", None)))
        if group.endswith("@g.us"):
            apply_event(self._receipt_state().roster, group, e, now or time.time(),
                        _text, self._resolve_address)

    def group_members(self, chat, fetch=True, now=None):
        """The group's members, or None if not yet known. `fetch` asks neonize for
        the GroupInfo when missing or expired (blocks: call from a thread);
        failing, the old list stands."""
        group = msgmap.jid_whatsmeow(chat)
        roster = self._receipt_state().roster
        now = now or time.time()
        if fetch and roster.stale(group, now) and self.client is not None \
                and self.status == "CONNECTED":
            try:
                from neonize.utils import build_jid
                user, _, server = group.partition("@")
                self.roster_register(self.client.get_group_info(build_jid(user, server)), now)
            except Exception as error:
                log.info("group members %s: %s", redact(group), type(error).__name__)
        return roster.members(group)

    # --- evaluation
    def _message_instant(self, mid):
        try:
            return int((self.db.wpp_message(mid) or {}).get("t") or 0)
        except (TypeError, ValueError):
            return 0

    def _evaluate_group(self, chat, mid, fetch, now, grace):
        """The `evaluate` Result for the message, or None if it is not known who
        the recipients are (member list or own account unknown)."""
        mine = self._my_keys()
        members = self.group_members(chat, fetch, now) if mine else None
        if not members:
            return None
        expected = recipients(members, mine, self._message_instant(mid))
        return evaluate(expected, self.db.receipts_of(mid), now, grace,
                        self._resolve_address if fetch else None)

    def receipt_summary(self, chat, mid, now=None, grace=READ_GRACE):
        """For message-ack: (receipts of the recipients only, how many there were)
        or None if not known. May call neonize: call from a thread."""
        r = self._evaluate_group(chat, mid, True, now or time.time(), grace)
        return None if r is None else (r.rows, r.expected)

    def _remember_ack(self, mid, ack):
        """Keeps the highest ack seen; True if `ack` surpassed it."""
        state = self._receipt_state()
        with state.lock:
            if ack <= state.acks.get(mid, 0):
                return False
            state.acks[mid] = ack
            state.acks.move_to_end(mid)
            while len(state.acks) > ACK_LIMIT:
                state.acks.popitem(last=False)
            return True

    def group_ack_to_emit(self, chat, mid, now=None, grace=READ_GRACE):
        """The `onack` to emit now for a group message of ours: 2, 3 or 4,
        or None (nothing new, or it is not known who the recipients are). Never
        returns an ack lower than or equal to one already emitted."""
        r = self._evaluate_group(chat, mid, True, now or time.time(), grace)
        if r is None:
            log.info("group ack %s: unknown members", redact(chat))
            return None
        log.info("group ack %s: %d/%d delivered, %d read, %d played -> %d",
                 redact(chat), r.delivered, r.expected, r.reads, r.plays, r.ack)
        if r.ack >= 2 and self._remember_ack(mid, r.ack):
            return r.ack
        return None

    def message_ack(self, w, now=None, grace=READ_GRACE):
        """The `ack` of a message of ours for get-messages/message-by-id: None
        outside a group (the receipts' prevails); in a group, only reads the
        cache (does not block the loop) and never falls below the highest ack
        already emitted."""
        chat = (w.get("id") or {}).get("remote") or ""
        if not str(chat).endswith("@g.us"):
            return None
        mid = w["id"]["id"]
        r = self._evaluate_group(chat, mid, False, now or time.time(), grace)
        ack = r.ack if r is not None else 1
        return max(ack, self._receipt_state().acks.get(mid, 1))
