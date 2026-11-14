"""The bridge notes in its log when its event loop stood still (loop_watch.py)."""
import asyncio
import logging

import loop_watch


def test_only_a_real_stall_counts():
    assert loop_watch.stall(10.0, 10.5) == 0.0
    assert loop_watch.stall(10.0, 12.0) == 2.0
    assert loop_watch.stall(10.0, 15.5) == 5.5


def test_watch_logs_a_stall(caplog):
    times = iter([0.0, 1.0, 10.0, 18.0])           # the second tick wakes 7 s late

    async def instant(_seconds):
        return None

    with caplog.at_level(logging.WARNING, logger="bridge"):
        asyncio.run(loop_watch.watch(clock=lambda: next(times), sleep=instant, rounds=2))
    assert [r.getMessage() for r in caplog.records] == ["event loop stood still for 7.0 s"]
