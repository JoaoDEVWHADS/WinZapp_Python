"""Regression tests for WPPConnect setup/update modal lifecycle.

ApiSetupDialog now guards late worker callbacks directly with IsModal(): when
its modal loop is still running completion uses EndModal(), and when the loop
has already ended it falls back to Close().  These tests exercise that current
contract without depending on private helpers that no longer exist.
"""

import pytest

wx = pytest.importorskip("wx")

from ui.dialogs import api_setup


class _Timer:
    def __init__(self):
        self.stop_calls = 0

    def Stop(self):
        self.stop_calls += 1


class _Gauge:
    def __init__(self):
        self.values = []

    def SetValue(self, value):
        self.values.append(value)


class _DialogStub:
    _on_cancel = api_setup.ApiSetupDialog._on_cancel
    _finish_success = api_setup.ApiSetupDialog._finish_success
    _finish_error = api_setup.ApiSetupDialog._finish_error

    def __init__(self, modal=True):
        self._modal = modal
        self._cancelled = False
        self._trickling = True
        self._timer = _Timer()
        self._gauge = _Gauge()
        self.end_results = []
        self.close_calls = 0
        self.kill_calls = 0

    def IsModal(self):
        return self._modal

    def EndModal(self, result):
        if not self._modal:
            raise AssertionError("EndModal called without a running modal loop")
        self.end_results.append(result)
        self._modal = False

    def Close(self):
        self.close_calls += 1
        self._modal = False

    def _kill_proc_tree(self):
        self.kill_calls += 1


def test_normal_success_ends_the_running_modal(monkeypatch):
    boxes = []
    monkeypatch.setattr(api_setup.wx, "MessageBox", lambda *args: boxes.append(args))
    dialog = _DialogStub()

    dialog._finish_success()

    assert dialog.end_results == [wx.ID_OK]
    assert dialog.close_calls == 0
    assert len(boxes) == 1
    assert dialog._gauge.values == [100]
    assert dialog._timer.stop_calls == 1
    assert dialog._trickling is False


def test_cancel_is_idempotent():
    dialog = _DialogStub()

    dialog._on_cancel()
    dialog._on_cancel()

    assert dialog.end_results == [wx.ID_CANCEL]
    assert dialog.kill_calls == 1
    assert dialog._timer.stop_calls == 1
    assert dialog._cancelled is True


@pytest.mark.parametrize("callback", ["_finish_success", "_finish_error"])
def test_completion_after_modal_loop_already_ended_uses_close(monkeypatch, callback):
    boxes = []
    monkeypatch.setattr(api_setup.wx, "MessageBox", lambda *args: boxes.append(args))
    dialog = _DialogStub(modal=False)

    if callback == "_finish_error":
        dialog._finish_error("details")
    else:
        dialog._finish_success()

    assert dialog.end_results == []
    assert dialog.close_calls == 1
    assert len(boxes) == 1


def test_normal_error_ends_the_running_modal(monkeypatch):
    boxes = []
    monkeypatch.setattr(api_setup.wx, "MessageBox", lambda *args: boxes.append(args))
    dialog = _DialogStub()

    dialog._finish_error("npm failed")

    assert dialog.end_results == [wx.ID_CANCEL]
    assert dialog.close_calls == 0
    assert len(boxes) == 1
    assert "npm failed" in boxes[0][0]
    assert dialog._timer.stop_calls == 1
