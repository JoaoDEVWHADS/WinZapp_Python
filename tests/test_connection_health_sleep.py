"""Only an overrun of the sleep, not slow health work, indicates suspend."""

from types import SimpleNamespace

import pytest

from main_window import account_link
from main_window.account_link import AccountLinkMixin


class StopSimulation(BaseException):
    pass


@pytest.mark.parametrize("work,overrun,wall_jump,expected", [
    (61, 0, 0, []), (1, 61, 0, ["reset", "recover"]),
    (1, 0, 3600, []), (1, 60, 0, []),
])
def test_health_loop_measures_sleep_only(monkeypatch, work, overrun, wall_jump, expected):
    run_health_loop(monkeypatch, work, overrun, wall_jump, expected)


@pytest.mark.parametrize("flag", ["_user_offline", "_wpp_updating", "_shutting_down"])
def test_sleep_overrun_does_not_recover_during_a_user_or_owned_teardown(monkeypatch, flag):
    run_health_loop(monkeypatch, 1, 61, 0, [], flag)


def run_health_loop(monkeypatch, work, overrun, wall_jump, expected, flag=None):
    targets, events, checks = [], [], []
    window = SimpleNamespace(_HEALTH_CHECK_INTERVAL=30, _WAKE_DETECT_GAP=90,
                             trigger_sync_if_needed=lambda: None,
                             _reset_connection_state_for_resume=lambda: events.append("reset"),
                             _recover_from_suspend=lambda: events.append("recover"))
    clock = SimpleNamespace(now=1000.0, wall=1000.0, sleeps=0)

    def sleep(seconds):
        clock.sleeps += 1
        if clock.sleeps > 2:
            raise StopSimulation
        clock.now += seconds + (overrun if clock.sleeps == 2 else 0)
        clock.wall += seconds + (wall_jump if clock.sleeps == 2 else 0)
        if flag and clock.sleeps == 2:
            setattr(window, flag, True)

    def check():
        if checks:
            raise StopSimulation
        checks.append("check")
        clock.now += work
        clock.wall += work

    class Worker:
        def __init__(self, target, **kwargs):
            targets.append(target)

        def start(self):
            pass

    window.check_wa_connection_http = check
    monkeypatch.setattr(account_link, "time", SimpleNamespace(
        monotonic=lambda: clock.now, time=lambda: clock.wall, sleep=sleep))
    monkeypatch.setattr(account_link, "threading", SimpleNamespace(Thread=Worker))
    AccountLinkMixin.start_connection_health_checker(window)
    try:
        targets[0]()
    except StopSimulation:
        pass
    assert events == expected
    assert checks == ["check"]
