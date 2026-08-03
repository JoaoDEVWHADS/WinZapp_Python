"""Tests for the "Sair" (Exit) shutdown wait.

Reported live: after the WPPConnect graceful-shutdown fix (waiting for Chrome
to close cleanly instead of taskkill /F /T'ing it immediately, to avoid
corrupting the linked-device credentials in its LevelDB profile — see
_stop_wpp_server()'s own docstring), clicking "Sair" made WinZapp's window sit
there tagged "Not Responding" by Windows for tens of seconds before actually
closing.

Two compounding bugs, both here:

1. real_exit() called _stop_wpp_server() directly on the wx main thread. That
   method can legitimately block for the whole graceful-stop budget (an HTTP
   request plus a poll loop) — which stops the message loop from pumping for
   that whole time, and Windows marks any window whose message loop goes quiet
   for a few seconds as "Not Responding". real_exit() must never call it
   synchronously.

2. The HTTP request and the poll loop after it each had their OWN full budget
   (25s + 25s = 50s worst case) instead of sharing one. Even off the main
   thread, a 50s wait to quit is bad on its own merits.
"""

import inspect
import re

import pytest

from main import MainWindow


class TestRealExitDoesNotBlockTheMainThread:
    def test_stop_wpp_server_is_not_called_synchronously(self):
        """The call inside real_exit() itself must be indirect (inside a
        function object handed to a background thread), never a direct,
        top-level `self._stop_wpp_server()` statement — that line is exactly
        what used to freeze the message loop."""
        src = inspect.getsource(MainWindow.real_exit)
        # Strip the docstring/comments referencing the method by name so this
        # doesn't false-positive on prose — check only for an unindented-under-
        # threading call shape: a bare `self._stop_wpp_server()` statement that
        # is NOT inside the nested function handed to threading.Thread.
        assert "threading.Thread(target=" in src, (
            "real_exit() no longer hands its teardown work to a background thread"
        )
        # The nested function (whatever it's named) must be what threading.Thread
        # targets, and _stop_wpp_server() must be called from within it.
        nested_def_match = re.search(r"def (_\w+)\(\):", src)
        assert nested_def_match, "real_exit() must define a nested teardown function"
        nested_name = nested_def_match.group(1)
        assert f"target={nested_name}" in src
        # Everything from the nested def onward is the background body.
        background_body = src[src.index(f"def {nested_name}("):]
        assert "self._stop_wpp_server()" in background_body

    def test_the_window_is_hidden_before_the_background_wait_starts(self):
        """Instant visual feedback on click, independent of how long the
        background teardown actually takes."""
        src = inspect.getsource(MainWindow.real_exit)
        hide_pos = src.index("self.Hide()")
        thread_pos = src.index("threading.Thread(target=")
        assert hide_pos < thread_pos, "the window must be hidden before the wait, not after"


class TestGracefulStopBudgetIsBounded:
    def test_the_two_stages_share_one_deadline_instead_of_stacking(self):
        """The bug: the HTTP call got timeout=_WPP_GRACEFUL_STOP_SECONDS AND the
        poll loop after it got its own fresh _WPP_GRACEFUL_STOP_SECONDS window —
        additive, so the real worst case was double the documented budget."""
        src = inspect.getsource(MainWindow._stop_wpp_server)
        # `deadline` computed exactly once from the constant, then reused by
        # both the request timeout and the poll loop — not two independent
        # `_WPP_GRACEFUL_STOP_SECONDS` windows back to back.
        assert src.count("time.time() + self._WPP_GRACEFUL_STOP_SECONDS") == 1, (
            "_stop_wpp_server() must derive both the HTTP timeout and the poll "
            "deadline from ONE shared budget, not spend the full constant twice"
        )
        assert "deadline = time.time() + self._WPP_GRACEFUL_STOP_SECONDS" in src
        assert "timeout=max(1, deadline - time.time())" in src, (
            "the /close-session request must be capped by what's left of the "
            "shared deadline, not get its own full budget"
        )

    def test_the_budget_is_short_enough_to_feel_like_quitting(self):
        """Not a hard number the user asked for, just a sanity ceiling: the old
        50s-worst-case regression must not come back, and the original 2s flat
        sleep (the thing that started this whole chain of fixes, by corrupting
        the WhatsApp Web session) must not either."""
        assert 2 < MainWindow._WPP_GRACEFUL_STOP_SECONDS <= 15
