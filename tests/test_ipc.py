"""Tests for client/ipc.py — account-scoped activate/quit IPC.

On Linux these exercise the AF_UNIX fallback transport + the shared protocol
(request_id framing, activate/quit dispatch, readiness, queue-before-window).
The Windows named-pipe transport shares the same protocol layer.
"""

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
