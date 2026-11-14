"""Temporary messages (that disappear on their own): the `temporary-messages`
route and the `ephemeral` branch of `group-property` (groups_extra.py).

The unit of the timer, checked in neonize 0.5.2 (client.py and the
disassembly of the native library, not just the documentation):

- `set_disappearing_timer(jid, timer, setting_ts)` delivers `timer` as an
  integer, with no arithmetic at all, as Go's `time.Duration`: NANOSECONDS.
  whatsmeow divides by 1e9 (`Duration.Seconds()`) to get the `expiration` in
  seconds.
- If `timer` is a `timedelta`, the Python wrapper multiplies it by 1000
  (milliseconds, not nanoseconds): the value would arrive 1e6 times too small.
  So the bridge ALWAYS passes an integer in nanoseconds.
- `setting_ts` is, on the Go side, milliseconds since 1970 (`time.UnixMilli`);
  the wrapper computes `int(time.time() + setting_ts.total_seconds() * 1000)`, so
  `setting_ts` has to be the delay that, added to `time.time()`, gives now in
  milliseconds. Without `setting_ts` Go receives 1970.

WhatsApp only offers off, 24 hours, 7 days and 90 days; other values are
refused here. None of this was tested against a real account.

The pure functions are at the top (tested in test_ephemeral_messages.py);
`register_routes` wires the route to the server.
"""
import logging
from datetime import timedelta

import responses
from chat_actions import phones
from chat_listing import boolean, chat_jid

log = logging.getLogger("bridge")

#: accepted durations, in seconds (0 = off)
DURATIONS = (0, 24 * 3600, 7 * 24 * 3600, 90 * 24 * 3600)
#: `value: true` without a duration: 7 days (WhatsApp Web's default when turning it on)
DEFAULT_DURATION = 7 * 24 * 3600
NANOS_PER_SECOND = 10 ** 9


def timer_seconds(value, duration=None):
    """`value` (boolean or seconds) and, if it comes, `duration` (seconds) -> one
    of the DURATIONS, or ValueError. `duration` beats `value`; empty turns it on."""
    if duration not in (None, ""):
        value = duration
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "false"):
            value = text == "true"
        elif text.isdigit():
            value = int(text)
        elif text:
            raise ValueError("value must be true, false or a number of seconds")
        else:
            value = True
    if value is None:
        value = True
    if isinstance(value, bool):
        return DEFAULT_DURATION if value else 0
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or value not in DURATIONS:
        raise ValueError("duration must be one of %s seconds" % ", ".join(map(str, DURATIONS)))
    return value


def is_ephemeral_property(property_) -> bool:
    return str(property_ or "").strip().lower() == "ephemeral"


def timer_arguments(seconds, now):
    """(timer in nanoseconds, setting_ts) for `set_disappearing_timer`, see the
    top of the module. `now` is `time.time()`."""
    delay = timedelta(seconds=(now * 1000 - now) / 1000)
    return int(seconds) * NANOS_PER_SECOND, delay


def apply_timer(client, jid, seconds, now, session=None):
    """Turns on, changes or turns off the timer of a chat or group; with
    `session`, remembers it for what the bridge sends there (chat_timers.py)."""
    timer, stamp = timer_arguments(seconds, now)
    client.set_disappearing_timer(jid, timer, stamp)
    if session is not None and getattr(jid, "User", ""):
        session.record_timer(f"{jid.User}@{jid.Server}", seconds, int(now))


def register_routes(r, *, session, ok, error, destination_of, in_thread, now):
    """Wire `temporary-messages` to the aiohttp router `r`."""
    async def temporary_messages(req):
        s = session(req)
        try:
            body = await req.json()
            body = body if isinstance(body, dict) else {}
            phone_list = phones(body)
            seconds = timer_seconds(body.get("value"), body.get("duration"))
        except ValueError as e:
            return error(e, 400)
        if s.client is None or s.status != "CONNECTED":
            return responses.disconnected()
        group = boolean(body.get("isGroup"), False)
        try:
            for phone in phone_list:
                await in_thread(apply_timer, s.client,
                                destination_of(chat_jid(phone, group)), seconds, now(), s)
        except Exception as e:
            log.exception("temporary-messages")
            return error(e)
        return ok(status="success", response={"duration": seconds})

    r.add_post("/api/{tok}/temporary-messages", temporary_messages)
