"""Notices when the bridge's event loop stops answering.

Every route, every Socket.IO ping and every event to the client runs on one
asyncio loop. When something blocks it (a store lock held for long, a
synchronous call in a handler), the client's socket misses its pings,
python-socketio drops it and WinZapp resynchronizes all its chats. The
client's own log only shows the drop; this puts in bridge.log how long the
loop stood still, so the next report says whether the bridge was the cause.

`stall` is pure (tested in test_loop_watch.py); `watch` is the task.
"""
import asyncio
import logging
import time

log = logging.getLogger("bridge")

TICK = 1.0          # seconds between two looks at the clock
REPORT = 2.0        # a delay past the tick this long is worth a line


def stall(expected, now, report=REPORT):
    """Seconds the loop stood still past `expected`, or 0.0 under `report`."""
    late = now - expected
    return late if late >= report else 0.0


async def watch(clock=time.monotonic, sleep=asyncio.sleep, tick=TICK, rounds=None):
    """Logs every stall of the loop; runs until cancelled (or `rounds` ticks)."""
    done = 0
    while rounds is None or done < rounds:
        expected = clock() + tick
        await sleep(tick)
        late = stall(expected, clock())
        if late:
            log.warning("event loop stood still for %.1f s", late)
        done += 1
