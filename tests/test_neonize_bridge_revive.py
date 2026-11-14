import pytest

from core import neonize_bridge_process as process
from main_window import neonize_bridge as nb


def test_a_missing_bridge_on_neonize_is_revived():
    assert nb.should_revive_bridge(True, False, False, None, 100.0)


def test_nothing_is_revived_off_neonize_or_with_the_port_open():
    assert not nb.should_revive_bridge(False, False, False, None, 100.0)
    assert not nb.should_revive_bridge(True, True, False, None, 100.0)


def test_only_one_revival_at_a_time_and_not_again_too_soon():
    assert not nb.should_revive_bridge(True, False, True, None, 100.0)
    assert not nb.should_revive_bridge(True, False, False, 100.0, 100.0 + nb.REVIVE_COOLDOWN - 1)
    assert nb.should_revive_bridge(True, False, False, 100.0, 100.0 + nb.REVIVE_COOLDOWN)


def test_no_revival_while_leaving_or_after_the_attempts_are_used_up():
    assert not nb.should_revive_bridge(True, False, False, None, 100.0, leaving=True)
    assert not nb.should_revive_bridge(True, False, False, None, 100.0,
                                       attempts=nb.REVIVE_MAX_ATTEMPTS)
    assert nb.should_revive_bridge(True, False, False, None, 100.0,
                                   attempts=nb.REVIVE_MAX_ATTEMPTS - 1)


class _Window(nb.NeonizeBridgeMixin):
    wpp_port = 6300

    def __init__(self, uses_neonize=True):
        self._uses = uses_neonize
        self.events = []

    def _uses_neonize(self):
        return self._uses

    def _use_neonize_bridge_secret(self):
        self.events.append("secret")


class _Thread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class _Bridge:
    started = []
    stopped = []
    result = True

    def __init__(self, port):
        self.port = port

    def start(self):
        _Bridge.started.append(self.port)
        return _Bridge.result

    def stop(self):
        _Bridge.stopped.append(self.port)


@pytest.fixture
def gone(monkeypatch):
    _Bridge.started, _Bridge.stopped, _Bridge.result = [], [], True
    monkeypatch.setattr(process, "port_open", lambda *a, **k: False)
    monkeypatch.setattr(process, "NeonizeBridge", _Bridge)
    monkeypatch.setattr(nb.threading, "Thread", _Thread)
    monkeypatch.setattr(nb.time, "sleep", lambda s: None)


def test_the_method_does_nothing_when_the_port_answers(monkeypatch):
    monkeypatch.setattr(process, "port_open", lambda *a, **k: True)
    window = _Window()
    window._revive_neonize_bridge()
    assert not getattr(window, "_neonize_reviving", False)


def test_the_method_starts_the_bridge_once_in_the_background(gone):
    window = _Window()
    window._revive_neonize_bridge()
    window._revive_neonize_bridge()      # inside the cooldown: no second start
    assert _Bridge.started == [6300] and window.events == ["secret"]
    assert window._neonize_reviving is False


def test_a_program_that_is_leaving_starts_nothing(gone):
    window = _Window()
    window._shutting_down = True
    window._revive_neonize_bridge()
    assert _Bridge.started == []
    purging = _Window()
    purging._purge_account_on_exit = "acc"
    purging._revive_neonize_bridge()
    assert _Bridge.started == []


def test_a_start_that_ends_after_shutdown_began_is_stopped_again(gone, monkeypatch):
    window = _Window()

    class _Late(_Bridge):
        def start(self):
            window._shutting_down = True      # the program began leaving during the start
            return super().start()

    monkeypatch.setattr(process, "NeonizeBridge", _Late)
    window._revive_neonize_bridge()
    assert _Bridge.stopped == [6300] and window.events == []


def test_a_failed_start_is_logged_and_the_flag_cleared(gone):
    _Bridge.result = False
    window = _Window()
    window._revive_neonize_bridge()
    assert window.events == [] and window._neonize_reviving is False


def test_an_exception_in_the_start_clears_the_flag(gone, monkeypatch):
    class _Broken(_Bridge):
        def start(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(process, "NeonizeBridge", _Broken)
    window = _Window()
    window._revive_neonize_bridge()
    assert window._neonize_reviving is False


def test_the_existing_bridge_object_is_reused(gone):
    window = _Window()
    window.neonize_bridge = _Bridge(6300)
    window._revive_neonize_bridge()
    assert _Bridge.started == [6300]


def test_the_attempts_stop_after_the_cap(gone):
    window = _Window()
    window._neonize_revive_attempts = nb.REVIVE_MAX_ATTEMPTS
    window._revive_neonize_bridge()
    assert _Bridge.started == []
