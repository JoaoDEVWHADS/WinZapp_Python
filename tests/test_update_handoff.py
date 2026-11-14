"""Cancel/close and installer handoff share one decision, without a wx window."""

import types

import pytest

from core.update_handoff import InstallHandoff
import update_progress as progress


class _Progress(progress.UpdateProgressLifecycle):
    def __init__(self):
        self._handoff = InstallHandoff()
        self._thread = None
        self._cancelled = False
        self._error_msg = ""
        self._main_window = types.SimpleNamespace(_shutting_down=False)
        self.disabled = False
        self._cancel_btn = types.SimpleNamespace(Disable=self.disable)
        self.modal = False
        self.results = []
        self.worked = 0

    def disable(self):
        self.disabled = True

    def IsModal(self):
        return self.modal

    def EndModal(self, result):
        self.modal = False
        self.results.append(result)

    def _worker(self):
        self.worked += 1


@pytest.fixture
def queue(monkeypatch):
    pending = []
    monkeypatch.setattr(progress.wx, "CallAfter", lambda fn, *a: pending.append((fn, a)))
    monkeypatch.setattr(progress.wx, "CallLater", lambda ms, fn: pending.append((fn, ())))
    return pending


def _next(queue):
    fn, args = queue.pop(0)
    fn(*args)


class TestCancellationAndGrant:
    def test_cancel_before_grant_is_terminal(self):
        h = InstallHandoff()
        assert h.cancel()
        assert not h.begin(True)
        assert not h.may_spawn()
        assert h.decided.is_set()

    def test_grant_before_cancel_is_irreversible(self):
        h = InstallHandoff()
        assert h.begin(True)
        assert not h.cancel()
        assert not h.begin(False), "a late callback must not revoke a grant"
        assert h.may_spawn()
        assert not h.cancelled.is_set()

    @pytest.mark.parametrize("modal", [False, True])
    def test_no_grant_after_settlement(self, modal):
        h = InstallHandoff()
        h.settled.set()
        assert not h.begin(modal)
        assert not h.may_spawn()

    @pytest.mark.parametrize("cause", ["cancel", "close", "escape"])
    def test_each_close_route_cancels_before_grant(self, cause):
        p = _Progress()
        p.modal = True
        evt = types.SimpleNamespace(GetKeyCode=lambda: progress.wx.WXK_ESCAPE)
        getattr(p, {"cancel": "_on_cancel", "close": "_on_close",
                    "escape": "_on_char_hook"}[cause])(evt)
        p._grant_install_handoff()
        assert p.results == [progress.wx.ID_CANCEL]
        assert not p._handoff.may_spawn()

    @pytest.mark.parametrize("vetoable", [False, True])
    def test_close_after_grant_cannot_cancel_installation(self, vetoable):
        p = _Progress()
        p.modal = True
        p._grant_install_handoff()
        called = []
        p._on_close(types.SimpleNamespace(CanVeto=lambda: vetoable,
                                         Veto=lambda: called.append("veto"),
                                         Skip=lambda: called.append("skip")))
        assert called == ["veto" if vetoable else "skip"]
        assert p._handoff.may_spawn() and p.disabled
        assert p.results == []

    @pytest.mark.parametrize("modal,shutdown", [(False, False), (True, True)])
    def test_grant_requires_running_modal_and_main_window(self, modal, shutdown):
        p = _Progress()
        p.modal = modal
        p._main_window._shutting_down = shutdown
        p._grant_install_handoff()
        assert not p._handoff.may_spawn()
        assert p._handoff.decided.is_set()

    def test_worker_waits_for_ui_decision(self, queue):
        p = _Progress()
        p.modal = True
        # Deterministic scheduler: the real method must wait rather than
        # interpret a still-unanswered UI request as permission.
        p._handoff.decided = types.SimpleNamespace(wait=lambda: _next(queue), set=lambda: None)
        assert p._request_install_handoff()
        assert p.disabled


class TestWorkerLifetime:
    def test_worker_starts_inside_the_modal_and_only_once(self, queue, monkeypatch):
        p = _Progress()
        monkeypatch.setattr(progress.threading, "Thread",
                            lambda target, **kw: types.SimpleNamespace(start=target))

        def show():
            assert p.worked == 0
            p.modal = True
            _next(queue)
            p._start_worker()
            return progress.wx.ID_CANCEL

        p.ShowModal = show
        assert p.run() == progress.wx.ID_CANCEL
        assert p.worked == 1
        assert p._handoff.cancelled.is_set()

    @pytest.mark.parametrize("throws", [False, True])
    def test_early_modal_return_prevents_a_late_worker(self, queue, throws):
        p = _Progress()

        def show():
            if throws:
                raise RuntimeError("native loop failed")
            return progress.wx.ID_CANCEL

        p.ShowModal = show
        if throws:
            with pytest.raises(RuntimeError):
                p.run()
        else:
            p.run()
        _next(queue)
        assert p.worked == 0
        assert p._handoff.settled.is_set()

    def test_ui_enqueue_failure_cannot_leave_an_unsettled_attempt(self, monkeypatch):
        p = _Progress()
        def fail(*a):
            raise RuntimeError("UI queue gone")
        monkeypatch.setattr(progress.wx, "CallAfter", fail)
        with pytest.raises(RuntimeError, match="UI queue gone"):
            p.run()
        assert p._handoff.cancelled.is_set() and p._handoff.settled.is_set()

    @pytest.mark.parametrize("stage", ["construct", "start"])
    def test_worker_start_failure_settles_and_ends_modal(self, monkeypatch, stage):
        p = _Progress()
        p.modal = True

        def fail():
            raise RuntimeError("no thread")

        def thread(**kw):
            if stage == "construct":
                fail()
            return types.SimpleNamespace(start=fail)

        monkeypatch.setattr(progress.threading, "Thread", thread)
        p._start_worker()
        assert p._handoff.settled.is_set()
        assert p._handoff.cancelled.is_set()
        assert p.results == [progress.wx.ID_ABORT]

    def test_deferred_completion_keeps_polling_without_blocking_ui(self, queue):
        p = _Progress()
        done = []
        assert p.defer_until_settled(lambda: done.append(True))
        _next(queue)
        assert done == [] and len(queue) == 1
        p._handoff.settled.set()
        _next(queue)
        assert done == [True] and queue == []
        assert not p.defer_until_settled(lambda: done.append(False))

    def test_late_progress_on_destroyed_control_is_ignored(self):
        def destroyed(value):
            raise RuntimeError("native control deleted")

        progress.update_control_if_alive(destroyed, 100)
