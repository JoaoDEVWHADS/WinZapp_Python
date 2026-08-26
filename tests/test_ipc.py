"""Tests for client/ipc.py — account-scoped activate/quit IPC.

On Linux these exercise the AF_UNIX fallback transport + the shared protocol
(request_id framing, activate/quit dispatch, readiness, queue-before-window).
The Windows named-pipe transport shares the same protocol layer.
"""

import sys
import threading
import time

import pytest

import ipc


def _gd(tmp_path):
    import os
    gd = str(tmp_path / "global")
    os.makedirs(gd, exist_ok=True)
    return gd


def test_no_listener_returns_false(tmp_path):
    gd = _gd(tmp_path)
    assert ipc.request_activate(gd, "a" * 32, source="user", timeout=0.3) is False
    assert ipc.request_quit(gd, "a" * 32, timeout=0.3) is False


def test_activate_delivers_with_source(tmp_path):
    gd = _gd(tmp_path)
    acc = "a" * 32
    received = []

    def on_activate(source):
        received.append(source)

    listener = ipc.IpcListener(gd, acc, on_activate=on_activate, on_quit=lambda: None)
    listener.start()
    try:
        assert listener.wait_ready(timeout=2.0)
        ok = ipc.request_activate(gd, acc, source="user", timeout=2.0)
        assert ok is True
        # give the listener thread a moment to run the callback
        for _ in range(50):
            if received:
                break
            time.sleep(0.02)
        assert received == ["user"]
    finally:
        listener.stop()


def test_quit_ack_then_release(tmp_path):
    """request_quit returns True only after the target signals release."""
    gd = _gd(tmp_path)
    acc = "b" * 32
    released = threading.Event()

    def on_quit():
        # Simulate the process shutting down and releasing its mutex/lease.
        threading.Timer(0.1, released.set).start()

    listener = ipc.IpcListener(
        gd, acc, on_activate=lambda s: None, on_quit=on_quit,
        released_predicate=lambda: released.is_set(),
    )
    listener.start()
    try:
        assert listener.wait_ready(timeout=2.0)
        ok = ipc.request_quit(gd, acc, timeout=3.0)
        assert ok is True
        assert released.is_set()
    finally:
        listener.stop()


def test_activate_scoped_by_account(tmp_path):
    """A request for account A must not reach a listener for account B."""
    gd = _gd(tmp_path)
    a, b = "a" * 32, "b" * 32
    hits = []
    la = ipc.IpcListener(gd, a, on_activate=lambda s: hits.append("a"), on_quit=lambda: None)
    lb = ipc.IpcListener(gd, b, on_activate=lambda s: hits.append("b"), on_quit=lambda: None)
    la.start(); lb.start()
    try:
        assert la.wait_ready(2.0) and lb.wait_ready(2.0)
        ipc.request_activate(gd, a, source="user", timeout=2.0)
        time.sleep(0.2)
        assert hits == ["a"]
    finally:
        la.stop(); lb.stop()


def test_queue_before_window_then_flush(tmp_path):
    """Requests arriving before the window is ready are queued and flushed."""
    gd = _gd(tmp_path)
    acc = "c" * 32
    delivered = []
    window_ready = {"v": False}

    def on_activate(source):
        if not window_ready["v"]:
            # simulate: no window yet -> the listener should have queued it,
            # so we should never see this until window_ready is True.
            delivered.append(("early", source))
        else:
            delivered.append(("ready", source))

    listener = ipc.IpcListener(
        gd, acc, on_activate=on_activate, on_quit=lambda: None,
        window_ready_predicate=lambda: window_ready["v"],
    )
    listener.start()
    try:
        assert listener.wait_ready(2.0)
        ipc.request_activate(gd, acc, source="user", timeout=2.0)
        time.sleep(0.2)
        assert delivered == []  # queued, not delivered yet
        window_ready["v"] = True
        listener.flush_queue()
        for _ in range(50):
            if delivered:
                break
            time.sleep(0.02)
        assert delivered == [("ready", "user")]
    finally:
        listener.stop()


def test_a_concurrent_activate_is_not_blocked_by_an_in_flight_quit(tmp_path):
    """Regression: handling "quit" used to happen inline in the accept loop,
    including its up-to-10s wait for released_predicate() — so any other
    request sent while a quit was in flight had nowhere to connect to until
    that wait finished. Each connection is now handed to its own thread so
    the accept loop is free to pick up the next one immediately."""
    gd = _gd(tmp_path)
    acc = "d" * 32
    released = threading.Event()

    def on_quit():
        # Slow enough that an inline handler would clearly stall the next
        # request; short enough to keep the test fast.
        threading.Timer(1.5, released.set).start()

    listener = ipc.IpcListener(
        gd, acc, on_activate=lambda s: None, on_quit=on_quit,
        released_predicate=lambda: released.is_set(),
    )
    listener.start()
    try:
        assert listener.wait_ready(2.0)

        quit_result = {}

        def _do_quit():
            quit_result["ok"] = ipc.request_quit(gd, acc, timeout=5.0)

        t = threading.Thread(target=_do_quit)
        t.start()
        time.sleep(0.3)  # let the quit request land and start its wait

        start = time.monotonic()
        ok = ipc.request_activate(gd, acc, source="user", timeout=2.0)
        elapsed = time.monotonic() - start

        assert ok is True
        assert elapsed < 1.0, (
            f"activate took {elapsed:.2f}s while a quit was in flight — "
            "the accept loop was blocked instead of handling it concurrently"
        )
        t.join(timeout=5)
        assert quit_result.get("ok") is True
    finally:
        listener.stop()


@pytest.mark.skipif(sys.platform != "win32", reason="named pipe DACL is Windows-only")
class TestNamedPipeDacl:
    """The module docstring has always claimed the named pipe is 'restricted
    to the current user' — this actually creates a pipe with the real
    SECURITY_ATTRIBUTES the listener builds and inspects the DACL Windows
    attached to it, rather than trusting that the pywin32 calls did what the
    comment says. A bare SECURITY_ATTRIBUTES() (the previous code) was
    confirmed, by this same technique, to grant full control to the current
    user AND BUILTIN\\Administrators AND NT AUTHORITY\\SYSTEM."""

    def test_only_the_current_user_has_an_ace(self):
        import win32pipe
        import win32file
        import win32security
        import win32api

        sa = ipc.IpcListener._current_user_pipe_sa()
        name = r"\\.\pipe\wz_test_dacl_pytest"
        handle = win32pipe.CreateNamedPipe(
            name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0, sa,
        )
        try:
            sd = win32security.GetSecurityInfo(
                handle, win32security.SE_KERNEL_OBJECT,
                win32security.DACL_SECURITY_INFORMATION,
            )
            dacl = sd.GetSecurityDescriptorDacl()
            assert dacl is not None
            assert dacl.GetAceCount() == 1

            token = win32security.OpenProcessToken(
                win32api.GetCurrentProcess(), win32security.TOKEN_QUERY
            )
            current_sid, _ = win32security.GetTokenInformation(token, win32security.TokenUser)
            ace = dacl.GetAce(0)
            assert ace[2] == current_sid
        finally:
            win32file.CloseHandle(handle)

    def test_the_current_user_can_still_connect(self):
        """The security lockdown must not lock out the very process that
        creates the pipe."""
        import win32pipe
        import win32file
        import pywintypes

        sa = ipc.IpcListener._current_user_pipe_sa()
        name = r"\\.\pipe\wz_test_dacl_connect_pytest"
        handle = win32pipe.CreateNamedPipe(
            name,
            win32pipe.PIPE_ACCESS_DUPLEX,
            win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
            win32pipe.PIPE_UNLIMITED_INSTANCES,
            65536, 65536, 0, sa,
        )
        connected = {}

        def _client():
            try:
                h = win32file.CreateFile(
                    name, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None,
                )
                connected["ok"] = True
                win32file.CloseHandle(h)
            except pywintypes.error as exc:
                connected["error"] = exc

        t = threading.Thread(target=_client)
        t.start()
        try:
            win32pipe.ConnectNamedPipe(handle, None)
        finally:
            t.join(timeout=5)
            win32file.CloseHandle(handle)

        assert connected.get("ok") is True, connected.get("error")
