"""Tests for client/coord_locks.py — cross-process coordination locks.

On non-Windows CI these exercise the flock fallback + the in-process RLock
re-entrancy layer. The three factories must produce independent locks.
"""

import os
import threading
import time

import pytest

from coord_locks import (
    app_settings_lock,
    LockTimeout,
    NamedLock,
    node_lock,
    node_port_lock,
    registry_lock,
    sessions_lock,
    updater_lock,
)


def test_basic_acquire_release(tmp_path):
    lk = NamedLock("WinZappTest_basic", str(tmp_path / "a.lock"))
    with lk:
        pass  # acquired and released without error
    # Re-acquire after release works
    with lk:
        pass


def test_reentrant_same_thread(tmp_path):
    lk = NamedLock("WinZappTest_reentrant", str(tmp_path / "b.lock"))
    with lk:
        with lk:  # nested acquisition by same thread must not deadlock
            with lk:
                pass


def test_mutual_exclusion_between_threads(tmp_path):
    """Two threads sharing the same lock name must not be in the CS together."""
    lock_path = str(tmp_path / "c.lock")
    in_cs = []
    max_concurrent = [0]
    state_lock = threading.Lock()

    def worker():
        lk = NamedLock("WinZappTest_mutex", lock_path, timeout=5.0)
        with lk:
            with state_lock:
                in_cs.append(1)
                max_concurrent[0] = max(max_concurrent[0], sum(in_cs))
            time.sleep(0.05)
            with state_lock:
                in_cs.pop()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_concurrent[0] == 1, "more than one thread entered the critical section"


def test_timeout_raises(tmp_path):
    """A second holder that can't get in within timeout raises LockTimeout.

    We hold the lock in a background thread, then a foreground attempt with a
    tiny timeout must raise. Uses distinct NamedLock objects (same name) to
    simulate contention while relying on the shared process state.
    """
    lock_path = str(tmp_path / "d.lock")
    held = threading.Event()
    release = threading.Event()

    def holder():
        lk = NamedLock("WinZappTest_timeout", lock_path, timeout=5.0)
        with lk:
            held.set()
            release.wait(timeout=5.0)

    t = threading.Thread(target=holder)
    t.start()
    assert held.wait(timeout=5.0)

    lk2 = NamedLock("WinZappTest_timeout", lock_path, timeout=0.1)
    with pytest.raises(LockTimeout):
        lk2.acquire()

    release.set()
    t.join()


def test_released_after_exception(tmp_path):
    """Lock must be released even if the guarded block raises."""
    lk = NamedLock("WinZappTest_exc", str(tmp_path / "e.lock"))
    with pytest.raises(ValueError):
        with lk:
            raise ValueError("boom")
    # If the lock had leaked, this second acquisition would deadlock/timeout.
    with NamedLock("WinZappTest_exc", str(tmp_path / "e.lock"), timeout=1.0):
        pass


def test_release_unheld_raises(tmp_path):
    lk = NamedLock("WinZappTest_unheld", str(tmp_path / "f.lock"))
    with pytest.raises(RuntimeError):
        lk.release()


def test_factories_are_independent(tmp_path):
    """registry / node / updater locks must not block one another."""
    gd = str(tmp_path)
    os.makedirs(os.path.join(gd, "node_coord"), exist_ok=True)
    rl = registry_lock(gd, timeout=1.0)
    nl = node_lock(gd, timeout=1.0)
    ul = updater_lock(gd, timeout=1.0)
    # Holding all three at once must be possible (distinct names/files).
    with rl:
        with nl:
            with ul:
                pass


def test_factory_names_differ(tmp_path):
    gd = str(tmp_path)
    assert registry_lock(gd).name != node_lock(gd).name
    assert node_lock(gd).name != updater_lock(gd).name
    assert registry_lock(gd).name != updater_lock(gd).name
    # sessions_lock is a distinct, independent critical section.
    assert sessions_lock(gd).name != registry_lock(gd).name
    assert sessions_lock(gd).name != node_lock(gd).name
    assert sessions_lock(gd).name != updater_lock(gd).name
    assert app_settings_lock(gd).name not in {
        registry_lock(gd).name,
        node_lock(gd).name,
        updater_lock(gd).name,
        sessions_lock(gd).name,
        node_port_lock(gd).name,
    }
    assert node_port_lock(gd).name not in {
        registry_lock(gd).name,
        node_lock(gd).name,
        updater_lock(gd).name,
        sessions_lock(gd).name,
    }


def test_same_global_dir_same_name(tmp_path):
    """Same global dir must map to the same lock name (cross-process key)."""
    gd = str(tmp_path)
    assert registry_lock(gd).name == registry_lock(gd).name


def _spawned_lock_probe(global_dir, result_queue):
    """Top-level so multiprocessing's Windows spawn mode can import it."""
    child_lock = registry_lock(global_dir, timeout=0.5)
    depth = child_lock._state.depth
    try:
        child_lock.acquire()
    except LockTimeout:
        result_queue.put((depth, "blocked"))
    else:
        child_lock.release()
        result_queue.put((depth, "acquired"))


if hasattr(os, "fork"):
    def test_fork_child_does_not_inherit_lock_ownership(tmp_path):
        """A forked child must reset ownership and remain blocked by flock."""
        gd = str(tmp_path)
        lock = registry_lock(gd, timeout=2.0)
        with lock:  # parent holds it across the fork
            pid = os.fork()
            if pid == 0:  # child
                rc = 0
                try:
                    child_lock = registry_lock(gd, timeout=0.5)
                    if child_lock._state.depth != 0:
                        rc = 3  # phantom inherited re-entrancy -> bug
                    else:
                        try:
                            child_lock.acquire()
                            rc = 5  # should have been blocked by parent's flock
                            child_lock.release()
                        except LockTimeout:
                            rc = 0  # correct: parent genuinely holds it
                except Exception:
                    rc = 4
                os._exit(rc)
            _, status = os.waitpid(pid, 0)
            assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
else:
    def test_spawned_child_is_blocked_by_parent_process_lock(tmp_path):
        """Windows spawn child sees fresh state but the parent's mutex blocks it."""
        import multiprocessing

        gd = str(tmp_path)
        context = multiprocessing.get_context("spawn")
        result_queue = context.Queue()
        lock = registry_lock(gd, timeout=2.0)
        with lock:
            child = context.Process(
                target=_spawned_lock_probe, args=(gd, result_queue))
            child.start()
            child.join(timeout=5.0)
            if child.is_alive():
                child.terminate()
                child.join(timeout=2.0)
                pytest.fail("spawned child did not finish its lock probe")

        assert child.exitcode == 0
        assert result_queue.get(timeout=1.0) == (0, "blocked")
