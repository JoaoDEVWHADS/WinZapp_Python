"""A sync callback queued for an old round must not clear or speak for a new one."""

import pytest
from main_window import sync
from tests.test_run_sync_broken_store import _make, _fast  # noqa: F401
from tests.test_run_sync_warm_path import _instrumented


@pytest.mark.parametrize("change", ["run", "token", "offline", "shutdown", None])
def test_announcements_check_ownership_when_ui_queue_drains(monkeypatch, change):
    queued = []
    stub = _instrumented(_make([3], wa_web=3, local_chats=3))
    stub._sync_run_id, stub.token = 1, "old"
    monkeypatch.setattr(sync.wx, "CallAfter", lambda fn, *a, **kw: queued.append(lambda: fn(*a, **kw)))
    stub._run_sync()
    # Only drain the two stage callbacks, not list-refresh/media callbacks.
    stages = [fn for fn in queued]
    stub.statuses.clear()
    stub.spoken.clear()
    if change == "run":
        stub._sync_run_id += 1
    elif change == "token":
        stub.token = "new"
    elif change == "offline":
        stub.offline_mode = True
    elif change == "shutdown":
        stub._shutting_down = True
    for callback in stages:
        callback()
    assert bool(stub.statuses) is (change is None)
    if change is not None:
        assert stub.spoken == []
