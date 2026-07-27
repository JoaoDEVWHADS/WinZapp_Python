"""Tests for toast notification behaviour.

Covers the "pile of notifications appears at once" bug: Windows queues toasts it
cannot display (screen off, Focus Assist) and pops them in sequence on wake, so
WinZapp must keep at most one notification alive and collapse any backlog of its
own instead of handing Windows a burst of banners.

Also covers the "sound plays well before the banner appears" complaint:
_dispatch() used to run a blocking WinRT/COM remove_toast_group() call in
front of EVERY show_toast(), and queued the sound only after show_toast()
returned — both added latency between "message arrived" and the sound/
banner actually happening that had nothing to do with Windows' own
(uncontrollable) toast-rendering pipeline.

NotificationManager starts a worker thread and touches the registry in
__init__, so the logic under test is exercised against a stub carrying only the
attributes those methods use.
"""

import queue
import time

import pytest
import wx

from core.notification_manager import NotificationManager


class _FakeToaster:
    """Records the toast calls a real WinRT toaster would receive."""

    def __init__(self, fail_group_removal=False):
        self.removed_groups = []
        self.removed_toasts = []
        self.shown_toasts = []
        self.fail_group_removal = fail_group_removal

    def remove_toast_group(self, group):
        if self.fail_group_removal:
            raise RuntimeError("not supported by this toaster")
        self.removed_groups.append(group)

    def remove_toast(self, toast):
        self.removed_toasts.append(toast)

    def show_toast(self, toast):
        self.shown_toasts.append(toast)


class _FakeI18n:
    def get_language(self):
        pass

    def t(self, key):
        return f"[{key}]"


class _Stub:
    """Minimal stand-in for NotificationManager."""

    TOAST_TAG = NotificationManager.TOAST_TAG
    TOAST_GRP = NotificationManager.TOAST_GRP
    _TOAST_LIKELY_GONE_SECONDS = NotificationManager._TOAST_LIKELY_GONE_SECONDS

    _coalesce_pending     = NotificationManager._coalesce_pending
    _clear_active_toasts  = NotificationManager._clear_active_toasts
    _dispatch             = NotificationManager._dispatch

    def _play_sound(self, remote_jid=""):
        pass

    def __init__(self, toaster=None, interactable=False):
        self._queue = queue.Queue()
        self._toaster = toaster
        self._last_toast = None
        self._last_shown_at = None
        self._interactable = interactable
        self.i18n = _FakeI18n()
        self.main_window = object()


class TestCoalescePending:
    def test_empty_queue_keeps_the_current_item(self):
        mgr = _Stub()
        item, dropped = mgr._coalesce_pending(("Ana", "oi", "j@g.us"))
        assert item == ("Ana", "oi", "j@g.us")
        assert dropped == 0

    def test_burst_collapses_to_the_newest(self):
        """The exact screen-off scenario: 30 messages must not become 30 banners."""
        mgr = _Stub()
        for i in range(29):
            mgr._queue.put((f"Sender {i}", f"body {i}", "j@g.us"))
        mgr._queue.put(("Newest", "last body", "j@g.us"))

        item, dropped = mgr._coalesce_pending(("Oldest", "first body", "j@g.us"))

        assert item == ("Newest", "last body", "j@g.us")
        assert dropped == 30
        assert mgr._queue.empty()

    def test_shutdown_signal_wins_over_pending_items(self):
        mgr = _Stub()
        mgr._queue.put(("Ana", "oi", "j@g.us"))
        mgr._queue.put(None)
        item, _ = mgr._coalesce_pending(("Bruno", "ola", "j@g.us"))
        assert item is None

    def test_items_after_a_shutdown_signal_are_left_alone(self):
        mgr = _Stub()
        mgr._queue.put(None)
        mgr._queue.put(("Ana", "oi", "j@g.us"))
        item, _ = mgr._coalesce_pending(("Bruno", "ola", "j@g.us"))
        assert item is None
        assert not mgr._queue.empty()


class TestClearActiveToasts:
    def test_removes_the_whole_group(self):
        toaster = _FakeToaster()
        mgr = _Stub(toaster)
        mgr._clear_active_toasts()
        assert toaster.removed_groups == [NotificationManager.TOAST_GRP]

    def test_falls_back_to_removing_the_last_toast(self):
        """Basic (non-interactable) toasters may not support group removal."""
        toaster = _FakeToaster(fail_group_removal=True)
        mgr = _Stub(toaster)
        sentinel = object()
        mgr._last_toast = sentinel
        mgr._clear_active_toasts()
        assert toaster.removed_toasts == [sentinel]

    def test_no_toaster_is_a_no_op(self):
        mgr = _Stub(None)
        mgr._clear_active_toasts()  # must not raise

    def test_nothing_to_remove_is_a_no_op(self):
        toaster = _FakeToaster(fail_group_removal=True)
        mgr = _Stub(toaster)
        mgr._clear_active_toasts()  # no _last_toast yet
        assert toaster.removed_toasts == []

    def test_removal_failure_never_propagates(self):
        """A failed cleanup must never stop the new notification from showing."""

        class _Broken:
            def remove_toast_group(self, group):
                raise RuntimeError("winrt unavailable")

            def remove_toast(self, toast):
                raise RuntimeError("winrt unavailable")

        mgr = _Stub(_Broken())
        mgr._last_toast = object()
        mgr._clear_active_toasts()  # must not raise


class TestToastIdentity:
    def test_tag_and_group_are_stable_constants(self):
        """A per-notification tag is what let banners stack up; the whole fix
        depends on every toast reusing one identity."""
        assert isinstance(NotificationManager.TOAST_TAG, str)
        assert isinstance(NotificationManager.TOAST_GRP, str)
        assert NotificationManager.TOAST_TAG
        assert NotificationManager.TOAST_GRP


class TestDispatchLatency:
    """_dispatch() is called on the worker thread for every notification.
    These cover the two latency fixes: skipping the blocking clear when
    nothing is likely still showing, and firing the sound before (not
    after) the WinRT/COM work."""

    def test_sound_is_queued_before_the_toast_is_shown(self, monkeypatch):
        """The whole point of the reorder: by the time show_toast() has even
        been called, the sound must already be queued."""
        calls = []
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: calls.append("sound"))
        toaster = _FakeToaster()
        real_show = toaster.show_toast
        toaster.show_toast = lambda t: (calls.append("toast"), real_show(t))[1]
        mgr = _Stub(toaster)

        mgr._dispatch("title", "body", "j@g.us")

        assert calls == ["sound", "toast"]

    def test_first_ever_notification_still_clears(self, monkeypatch):
        """_last_shown_at is None (nothing shown yet this session) — must
        still attempt the clear, same as before this change."""
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: None)
        toaster = _FakeToaster()
        mgr = _Stub(toaster)
        assert mgr._last_shown_at is None

        mgr._dispatch("title", "body", "j@g.us")

        assert toaster.removed_groups == [NotificationManager.TOAST_GRP]
        assert mgr._last_shown_at is not None  # recorded after showing

    def test_recent_toast_still_clears(self, monkeypatch):
        """A burst arriving within the "likely still visible" window must
        keep clearing — this is the actual case the clear exists to fix."""
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: None)
        toaster = _FakeToaster()
        mgr = _Stub(toaster)
        mgr._last_shown_at = time.monotonic()  # "just shown"

        mgr._dispatch("title", "body", "j@g.us")

        assert toaster.removed_groups == [NotificationManager.TOAST_GRP]

    def test_stale_toast_skips_the_clear(self, monkeypatch):
        """Once the previous toast has almost certainly auto-dismissed,
        skip the blocking clear — this is the actual latency fix."""
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: None)
        toaster = _FakeToaster()
        mgr = _Stub(toaster)
        mgr._last_shown_at = time.monotonic() - (mgr._TOAST_LIKELY_GONE_SECONDS + 1)

        mgr._dispatch("title", "body", "j@g.us")

        assert toaster.removed_groups == []
        assert len(toaster.shown_toasts) == 1  # the new toast is still shown

    def test_last_shown_at_updates_after_each_dispatch(self, monkeypatch):
        monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: None)
        mgr = _Stub(_FakeToaster())
        before = time.monotonic()

        mgr._dispatch("title", "body", "j@g.us")

        assert mgr._last_shown_at >= before
