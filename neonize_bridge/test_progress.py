"""Transfer progress: the pure calculations, the limiter and the probe (with a
fake clock and reading; no real waiting besides one thread test)."""
import threading

import pytest

import progress as p


@pytest.mark.parametrize("value,expected", [
    (0, 0.0), (10, 0.1), (55, 0.55), (100, 1.0), (250, 1.0), ("42", 0.42),
    (-1, None), (None, None), ("x", None), (float("nan"), None),
])
def test_fraction_from_percent(value, expected):
    assert p.fraction_from_percent(value) == expected


@pytest.mark.parametrize("current,expected,fraction", [
    (0, 1000, 0.0), (250, 1000, 0.25), (1000, 1000, p.IN_PROGRESS_CEILING),
    (5000, 1000, p.IN_PROGRESS_CEILING),          # file larger than said: never goes past the ceiling
    (10, 0, None), (10, -5, None), (-1, 100, None), (None, 100, None), ("a", 100, None),
])
def test_fraction_from_file(current, expected, fraction):
    assert p.fraction_from_file(current, expected) == fraction


def test_progress_id_of_only_accepts_text_from_the_body():
    assert p.progress_id_of({"progressId": "  ABC  "}) == "ABC"
    assert p.progress_id_of({"progressId": 7}) == ""
    assert p.progress_id_of({}) == ""
    assert p.progress_id_of(None) == ""
    assert p.progress_id_of([1]) == ""
    assert len(p.progress_id_of({"progressId": "x" * 999})) == 200


def test_payloads_in_the_format_the_client_reads():
    assert p.upload_event("account1", "U1", 0.12345678) == {
        "uploadId": "U1", "progress": 0.1235, "session": "account1"}
    assert p.download_event("account1", "D1", 0.5) == {
        "progressId": "D1", "progress": 0.5, "session": "account1"}


def test_limiter_only_emits_when_the_whole_percent_advances():
    lim = p.Limiter(minimum=0.25)
    assert lim.decide(0.10, 0.0) is True
    assert lim.decide(0.10, 1.0) is False        # equal
    assert lim.decide(0.104, 2.0) is False       # same whole percent
    assert lim.decide(0.05, 3.0) is False        # never goes back
    assert lim.decide(0.20, 4.0) is True


def test_limiter_waits_the_minimum_interval_but_does_not_stop_the_100():
    lim = p.Limiter(minimum=0.25)
    assert lim.decide(0.10, 10.0) is True
    assert lim.decide(0.20, 10.1) is False       # too early
    assert lim.decide(0.20, 10.3) is True
    assert lim.decide(1.0, 10.31) is True        # the end overrides the interval
    assert lim.finished
    assert lim.decide(1.0, 20.0) is False        # and only once


def test_limiter_ignores_a_reading_with_no_value():
    assert p.Limiter().decide(None, 0.0) is False


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _tracker(readings, received, clock):
    queue = iter(readings)

    def read():
        value = next(queue)
        if isinstance(value, Exception):
            raise value
        return value
    return p.Tracker(read, received.append, clock=clock)


def test_step_emits_through_the_limiter_and_survives_a_bad_reading():
    clock, received = Clock(), []
    a = _tracker([0.1, RuntimeError("dll"), None, 0.1, 0.5], received, clock)
    for _ in range(5):
        clock.t += 1
        a.step()
    assert received == [0.1, 0.5]


def test_emit_that_fails_does_not_bring_down_the_step():
    def explode(_):
        raise RuntimeError("socket")
    a = p.Tracker(lambda: 0.5, explode)
    a.step()       # does not raise


def test_finish_emits_the_100_once():
    clock, received = Clock(), []
    a = _tracker([0.3], received, clock)
    clock.t = 1
    a.step()
    a.finish()
    a.finish()
    assert received == [0.3, 1.0]


def test_the_thread_probes_until_it_stops():
    reads = []
    three = threading.Event()

    def read():
        reads.append(1)
        if len(reads) >= 3:
            three.set()
        return min(len(reads) / 10, 0.9)
    received = []
    a = p.Tracker(read, received.append, interval=0.01, minimum=0.0)
    with a:
        assert three.wait(5)
    n = len(reads)
    threading.Event().wait(0.1)
    assert len(reads) == n          # stopped on leaving the context
    assert received[0] == 0.1
    assert a._thread is None


def test_leaving_the_context_with_an_error_does_not_emit_the_100():
    received = []
    with pytest.raises(RuntimeError):
        with p.Tracker(lambda: None, received.append, interval=0.01):
            raise RuntimeError("failed")
    assert received == []
