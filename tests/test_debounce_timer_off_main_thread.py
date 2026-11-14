"""The debounced schedulers may be called from worker threads.

wx.CallLater starts a wxTimer, and wx asserts that only the main thread may do
that. _schedule_set_chats() said "safe to call from any thread" while calling
wx.CallLater directly, so Shift+F5's worker -- which calls it after the resync
has already succeeded -- raised wxAssertionError, and the user heard "could not
resync" for a resync that had worked (reported from a user's log, 2026-09-28).

On wxMSW the check is an assertion, not a refusal: wx.CallLater keeps its
reference before Start(), the timer runs anyway and clears the pending flag
(the same user's second Shift+F5 raised again, which it could not have done
with the flag stuck). The schedulers still clear the flag themselves when the
timer fails to start, since nothing else would ever clear it.
"""

import pytest

from main import MainWindow
from main_window import chat_list


class _Window:
    _schedule_set_chats = MainWindow._schedule_set_chats
    _schedule_refresh_messages = MainWindow._schedule_refresh_messages

    def _do_scheduled_set_chats(self):
        pass

    def _do_scheduled_refresh_messages(self):
        pass


@pytest.fixture
def wx_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(chat_list.wx, "CallAfter",
                        lambda fn, *a, **k: calls.append(("CallAfter", fn, a)))
    monkeypatch.setattr(chat_list.wx, "CallLater",
                        lambda ms, fn, *a, **k: calls.append(("CallLater", ms, fn)))
    return calls


def test_off_the_main_thread_the_timer_is_handed_to_the_main_thread(monkeypatch, wx_calls):
    monkeypatch.setattr(chat_list.wx, "IsMainThread", lambda: False)
    callback = object()

    chat_list._start_debounce_timer(300, callback)

    assert [c[0] for c in wx_calls] == ["CallAfter"]
    wx_calls[0][1]()   # what the main thread then runs
    assert wx_calls[1:] == [("CallLater", 300, callback)]


def test_on_the_main_thread_the_timer_starts_directly(monkeypatch, wx_calls):
    monkeypatch.setattr(chat_list.wx, "IsMainThread", lambda: True)
    callback = object()

    chat_list._start_debounce_timer(300, callback)

    assert wx_calls == [("CallLater", 300, callback)]


@pytest.mark.parametrize("method, flag", [
    ("_schedule_set_chats", "_set_chats_pending"),
    ("_schedule_refresh_messages", "_refresh_messages_pending"),
])
def test_a_scheduler_called_from_a_worker_does_not_start_a_timer_there(
        monkeypatch, wx_calls, method, flag):
    monkeypatch.setattr(chat_list.wx, "IsMainThread", lambda: False)
    window = _Window()

    getattr(window, method)()

    assert [c[0] for c in wx_calls] == ["CallAfter"]
    assert getattr(window, flag) is True


@pytest.mark.parametrize("method, flag", [
    ("_schedule_set_chats", "_set_chats_pending"),
    ("_schedule_refresh_messages", "_refresh_messages_pending"),
])
def test_a_timer_that_fails_to_start_does_not_latch_the_flag(monkeypatch, method, flag):
    def _refuse(*_a, **_k):
        raise RuntimeError("timer can only be started from the main thread")
    monkeypatch.setattr(chat_list, "_start_debounce_timer", _refuse)
    window = _Window()

    with pytest.raises(RuntimeError):
        getattr(window, method)()

    assert getattr(window, flag) is False


def test_a_timer_that_fails_on_the_main_thread_after_the_handover_releases_the_flag(monkeypatch):
    queued = []
    monkeypatch.setattr(chat_list.wx, "IsMainThread", lambda: False)
    monkeypatch.setattr(chat_list.wx, "CallAfter", lambda fn, *a, **k: queued.append(fn))

    def _refuse(*_a, **_k):
        raise RuntimeError("timer refused")
    monkeypatch.setattr(chat_list.wx, "CallLater", _refuse)
    window = _Window()

    window._schedule_set_chats()
    assert window._set_chats_pending is True    # nothing has failed yet
    queued[0]()                                 # the main thread runs the handover

    assert window._set_chats_pending is False
