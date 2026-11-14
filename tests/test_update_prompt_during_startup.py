"""The update prompt must not open on top of the startup dialog, and a quit
that gets stuck must not leave a windowless process behind.

Reported: after answering "No" to the alpha update prompt the app never opened
again; its process kept running with no window and held the instance lock, so
every later launch handed its request to it and returned. The prompt is
scheduled 15 s after launch, which a slow start spends inside the modal "API
is starting" dialog, so the prompt opened as a second modal loop on top of it.
"""

import threading

import pytest

import main_window.window_lifecycle as lifecycle
import updater
from main_window.updates import UpdatesMixin
from main_window.window_lifecycle import WindowLifecycleMixin


class _Checker:
    """UpdateChecker bound onto a stub that only carries what the prompt reads."""

    _UI_NOT_READY_RETRY_MS = 2000
    _show_update_dialog = updater.UpdateChecker._show_update_dialog
    _main_window_ready = updater.UpdateChecker._main_window_ready

    def __init__(self, ready):
        self._mw = type("MW", (), {})()
        if ready is not None:
            self._mw._ui_ready_event = ready
        self.retries = []
        self.claims_released = 0

    def _release_prompt(self):
        self.claims_released += 1

    def _schedule_retry(self):
        pass


@pytest.fixture
def no_dialog(monkeypatch):
    created = []

    class _Dialog:
        def __init__(self, *a, **k):
            created.append(a)
            raise RuntimeError("the dialog must not be built")

    monkeypatch.setattr(updater, "UpdateDialog", _Dialog)
    return created


def test_the_prompt_waits_while_the_main_window_is_still_being_built(monkeypatch, no_dialog):
    later = []
    monkeypatch.setattr(updater.wx, "CallLater", lambda ms, fn, *a, **k: later.append((ms, fn, a, k)))
    checker = _Checker(threading.Event())

    checker._show_update_dialog("2.0.0.9", "notes", "http://zip", "", signature_url="sig", is_alpha=True)

    assert no_dialog == []
    assert checker.claims_released == 0   # the claim is kept while it waits
    assert later == [(2000, checker._show_update_dialog,
                      ("2.0.0.9", "notes", "http://zip", ""),
                      {"signature_url": "sig", "is_alpha": True})]


def test_the_prompt_opens_once_the_main_window_exists(monkeypatch):
    shown = []

    class _Dialog:
        def __init__(self, parent, version, changelog):
            shown.append(version)

        def ShowModal(self):
            return updater.wx.ID_NO

        def Destroy(self):
            pass

    monkeypatch.setattr(updater, "UpdateDialog", _Dialog)
    ready = threading.Event()
    ready.set()
    checker = _Checker(ready)

    checker._show_update_dialog("2.0.0.9", "notes", "http://zip")

    assert shown == ["2.0.0.9"]
    assert checker.claims_released == 1


def test_a_main_window_without_the_event_counts_as_ready():
    assert _Checker(None)._main_window_ready() is True


def test_the_prompt_also_waits_while_pairing_owns_the_screen(monkeypatch, no_dialog):
    later = []
    monkeypatch.setattr(updater.wx, "CallLater", lambda ms, fn, *a, **k: later.append(ms))
    ready = threading.Event()
    ready.set()
    checker = _Checker(ready)
    checker._mw.wpp_update_may_run_now = lambda: False

    checker._show_update_dialog("2.0.0.9", "notes", "http://zip")

    assert no_dialog == [] and later == [2000]


def test_no_prompt_opens_on_an_app_that_is_quitting(monkeypatch, no_dialog):
    later = []
    monkeypatch.setattr(updater.wx, "CallLater", lambda ms, fn, *a, **k: later.append(ms))
    ready = threading.Event()
    ready.set()
    checker = _Checker(ready)
    checker._mw._shutting_down = True

    checker._show_update_dialog("2.0.0.9", "notes", "http://zip")

    assert no_dialog == [] and later == []
    assert checker.claims_released == 1


def test_the_app_never_exits_just_because_the_last_window_closed():
    # wx ends the main loop when the last VISIBLE top-level window closes; with
    # the main window in the tray that is a dialog. Needs no window to check:
    # the guard has to sit between creating the app and building the window.
    import pathlib
    source = (pathlib.Path(__file__).resolve().parents[1] / "client" / "main.py").read_text(
        encoding="utf-8")
    app_at = source.index("app = wx.App()")
    guard_at = source.index("app.SetExitOnFrameDelete(False)", app_at)
    window_at = source.index("frame = MainWindow(", app_at)
    assert app_at < guard_at < window_at


def test_the_wpp_update_check_also_waits_for_the_window():
    class _Stub:
        _ui_ready_event = threading.Event()
        wpp_update_may_run_now = UpdatesMixin.wpp_update_may_run_now
        _is_pairing_dialog_active = staticmethod(lambda: False)

    assert _Stub().wpp_update_may_run_now() is False
    _Stub._ui_ready_event.set()
    assert _Stub().wpp_update_may_run_now() is True


class _Window:
    _QUIT_HARD_DEADLINE_SECONDS = 150.0
    _EXIT_HARD_DEADLINE_SECONDS = 8.0
    _teardown_complete_event = threading.Event()
    _TEARDOWN_OWNED_ELSEWHERE_WAIT_SECONDS = 0.0
    real_exit = WindowLifecycleMixin.real_exit
    _terminate_process = WindowLifecycleMixin._terminate_process

    def __init__(self, hide):
        self._hide = hide
        self.order = []

    def Hide(self):
        self.order.append("hide")
        self._hide()

    def _perform_shutdown(self):
        return True


@pytest.fixture
def timers(monkeypatch):
    armed = []

    class _Timer:
        def __init__(self, seconds, fn, *a, **k):
            armed.append(seconds)
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(lifecycle.threading, "Timer", _Timer)
    return armed


def test_the_exit_deadline_is_armed_before_the_wx_calls_that_can_block(monkeypatch, timers):
    window = _Window(hide=lambda: window.order.append(("armed", list(timers))))
    monkeypatch.setattr(lifecycle.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())

    window._terminate_process()

    assert timers == [8.0]
    assert window.order == ["hide", ("armed", [8.0])]   # armed by the time Hide() runs


def test_a_blocked_hide_cannot_stop_the_exit_deadline(monkeypatch, timers):
    def _hang():
        raise RuntimeError("Hide() blocked and finally failed")
    window = _Window(hide=_hang)
    monkeypatch.setattr(lifecycle.threading, "Thread", lambda **k: type("T", (), {"start": lambda s: None})())

    window._terminate_process()

    assert timers == [8.0]


def test_a_quit_has_an_overall_deadline(monkeypatch, timers):
    started = []
    monkeypatch.setattr(lifecycle.threading, "Thread",
                        lambda **k: type("T", (), {"start": lambda s: started.append(k.get("name"))})())
    window = _Window(hide=lambda: None)

    window.real_exit()

    assert timers == [150.0]
    assert started == ["winzapp-shutdown"]


def test_the_forced_exit_is_written_to_the_audit_log_that_survives_a_launch(monkeypatch):
    lines = []
    fired = []

    class _Timer:
        def __init__(self, seconds, fn):
            fired.append(fn)
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(lifecycle.threading, "Timer", _Timer)
    monkeypatch.setattr(lifecycle.os, "_exit", lambda code: None)

    lifecycle._arm_hard_exit(150, "quit did not finish", audit=lines.append)
    fired[0]()

    assert lines and "quit did not finish within 150s" in lines[0]


def test_the_forced_exit_logs_and_exits(monkeypatch):
    calls = []
    fired = []

    class _Timer:
        def __init__(self, seconds, fn):
            fired.append(fn)
            self.daemon = False

        def start(self):
            pass

    monkeypatch.setattr(lifecycle.threading, "Timer", _Timer)
    monkeypatch.setattr(lifecycle.os, "_exit", lambda code: calls.append(code))

    lifecycle._arm_hard_exit(5, "exit did not complete")
    fired[0]()

    assert calls == [0]
