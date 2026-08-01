"""
Cross-process coordination locks for WinZapp multi-account support
(client/coord_locks.py)
====================================================================

Three SEPARATE named locks guard the three independent global critical
sections of multi-account mode, so a long-held lock in one area never blocks
the others (see plan Zadanie 1.1 / section E):

  * registry_lock  — held BRIEFLY around every read-modify-write of the
                     account registry (accounts.json) and the migration.
  * node_lock      — held (possibly for many seconds) around the shared
                     WPPConnect Node probe / start / adopt / stop protocol.
  * updater_lock   — held around the updater's runtime-lease / update_state
                     bookkeeping.

Implementation notes
---------------------
* On Windows the lock is a *named mutex* (``CreateMutexW`` + ``WaitForSingleObject``).
  A Windows mutex is owned by the THREAD that acquired it and must be released
  by that same thread — never release from another thread. To make in-process
  re-entrancy safe we pair the OS mutex with a ``threading.RLock``: the OS
  mutex is acquired only on the OUTERMOST entry (recursion depth 0 -> 1) and
  released only on the outermost exit, and only ever touched from the acquiring
  thread because the RLock serialises threads within the process first.
* On non-Windows (dev machines / Linux CI) there is no ``CreateMutexW``; we fall
  back to ``fcntl.flock`` on a lock file. flock is advisory and per-open-file,
  and does NOT synchronise threads of the same process, so the same
  ``threading.RLock`` provides intra-process mutual exclusion there too.
* ``timeout`` is in seconds; exceeding it raises ``LockTimeout``. The lock is
  ALWAYS released on ``__exit__`` (try/finally at the call site via the context
  manager protocol), including when the guarded block raises.
"""

from __future__ import annotations

import os
import sys
import threading
import time

_IS_WINDOWS = sys.platform == "win32"


def canonical_dir(path: str) -> str:
    """Canonical form of a directory path for stable cross-process keying.
    normcase(realpath(abspath(...))) so that e.g. C:\\Users\\X\\global and
    c:\\users\\x\\GLOBAL (same dir on Windows) hash to the SAME lock name — a
    mismatch would let two processes mutate the same JSON under different
    mutexes (GPT r1-code #2).
    """
    try:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except OSError:
        return os.path.normcase(os.path.abspath(path))


class LockTimeout(RuntimeError):
    """Raised when a lock cannot be acquired within the requested timeout."""


_kernel32 = None


def _win_kernel32():
    """Return a cached kernel32 WinDLL with correct 64-bit signatures.
    Without explicit restype/argtypes, ctypes defaults every result to c_int,
    which TRUNCATES a 64-bit HANDLE on Windows x64 (GPT r1-code #1) — the
    handle would be corrupt and ReleaseMutex/CloseHandle would fail silently.
    use_last_error=True lets us surface real Win32 errors via WinError.
    """
    global _kernel32
    if _kernel32 is not None:
        return _kernel32
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.WaitForSingleObject.restype = wintypes.DWORD
    k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k.ReleaseMutex.restype = wintypes.BOOL
    k.ReleaseMutex.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32 = k
    return k


class NamedLock:
    """A re-entrant, cross-process lock identified by ``name``.

    Use as a context manager::

        with NamedLock("WinZappRegistry_<hash>", lock_path) as lk:
            ...  # critical section

    ``name``      Windows global mutex name (without the ``Global\\`` prefix,
                  which is added internally). Also used to key the per-process
                  singleton so two ``NamedLock`` objects with the same name in
                  one process share one ``threading.RLock`` and one recursion
                  counter.
    ``lock_path`` Filesystem path used for the ``flock`` fallback on
                  non-Windows. Parent directory is created on demand.
    ``timeout``   Seconds to wait for the OS lock before raising ``LockTimeout``.
    """

    # Per-process registry so that the SAME logical lock (same name) shares one
    # RLock + recursion counter even if callers construct multiple NamedLock
    # instances for it.
    _process_state_lock = threading.Lock()
    _process_state: dict[str, "_LockState"] = {}

    def __init__(self, name: str, lock_path: str, timeout: float = 10.0):
        if not name:
            raise ValueError("NamedLock requires a non-empty name")
        self.name = name
        self.lock_path = lock_path
        self.timeout = timeout
        self._state = self._get_state(name)

    @classmethod
    def _get_state(cls, name: str) -> "_LockState":
        with cls._process_state_lock:
            st = cls._process_state.get(name)
            if st is None:
                st = _LockState()
                cls._process_state[name] = st
            return st

    # ── context manager ──────────────────────────────────────────────────
    def __enter__(self) -> "NamedLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    # ── acquire / release ────────────────────────────────────────────────
    def acquire(self) -> None:
        st = self._state
        deadline = time.monotonic() + self.timeout

        # 1) Intra-process mutual exclusion (also handles thread ownership so
        #    the OS mutex is only ever touched by the acquiring thread).
        remaining = max(0.0, deadline - time.monotonic())
        if not st.rlock.acquire(timeout=remaining if remaining > 0 else 0.001):
            raise LockTimeout(f"Timed out acquiring in-process lock '{self.name}'")

        try:
            # Re-entrant: only the OUTERMOST acquisition touches the OS lock.
            if st.depth == 0:
                remaining = max(0.0, deadline - time.monotonic())
                self._os_acquire(remaining)
                st.owner_thread = threading.get_ident()
            st.depth += 1
        except BaseException:
            st.rlock.release()
            raise

    def release(self) -> None:
        st = self._state
        # Guard: only the owning thread may release (GPT r1-code #8). Touching
        # depth / OS handle / flock from a foreign thread could unlock an flock
        # another thread relies on. Verify ownership BEFORE mutating anything.
        if st.owner_thread != threading.get_ident() or st.depth <= 0:
            raise RuntimeError(f"Releasing un-held lock '{self.name}' from wrong thread")
        st.depth -= 1
        try:
            if st.depth == 0:
                self._os_release()
                st.owner_thread = None
        finally:
            st.rlock.release()

    # ── OS-level primitive ───────────────────────────────────────────────
    def _os_acquire(self, timeout: float) -> None:
        if _IS_WINDOWS:
            self._win_acquire(timeout)
        else:
            self._flock_acquire(timeout)

    def _os_release(self) -> None:
        if _IS_WINDOWS:
            self._win_release()
        else:
            self._flock_release()

    # ── Windows named mutex ──────────────────────────────────────────────
    def _win_acquire(self, timeout: float) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = _win_kernel32()
        full_name = f"Global\\{self.name}"
        handle = kernel32.CreateMutexW(None, False, full_name)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())

        ms = 0xFFFFFFFF if timeout is None else max(0, int(timeout * 1000))
        WAIT_OBJECT_0 = 0x0
        WAIT_ABANDONED = 0x80
        WAIT_TIMEOUT = 0x102
        rc = kernel32.WaitForSingleObject(handle, ms)
        if rc == WAIT_TIMEOUT:
            kernel32.CloseHandle(handle)
            raise LockTimeout(f"Timed out acquiring OS mutex '{full_name}'")
        if rc not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            kernel32.CloseHandle(handle)
            raise OSError(f"WaitForSingleObject failed for '{full_name}' (rc {rc})")
        # WAIT_ABANDONED: previous owner died holding it — we now own it and the
        # protected state may be inconsistent; callers that care run recovery.
        self._state.win_handle = handle

    def _win_release(self) -> None:
        import ctypes

        kernel32 = _win_kernel32()
        handle = self._state.win_handle
        if handle:
            if not kernel32.ReleaseMutex(handle):
                # Log-worthy but don't mask the primary flow; close anyway.
                pass
            kernel32.CloseHandle(handle)
            self._state.win_handle = None

    # ── POSIX flock fallback ─────────────────────────────────────────────
    def _flock_acquire(self, timeout: float) -> None:
        import fcntl

        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)), exist_ok=True)
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + (timeout if timeout is not None else 0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._state.flock_fd = fd
                return
            except OSError:
                if timeout is not None and time.monotonic() >= deadline:
                    os.close(fd)
                    raise LockTimeout(f"Timed out acquiring flock '{self.lock_path}'")
                time.sleep(0.02)

    def _flock_release(self) -> None:
        import fcntl

        fd = self._state.flock_fd
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
                self._state.flock_fd = None


class _LockState:
    """Per-process shared state for one logical lock name."""

    __slots__ = ("rlock", "depth", "win_handle", "flock_fd", "owner_thread")

    def __init__(self) -> None:
        self.rlock = threading.RLock()
        self.depth = 0
        self.win_handle = None
        self.flock_fd = None
        self.owner_thread = None


# ── Lock factories (one per global critical section) ─────────────────────────
# Each returns a NamedLock keyed to a distinct name + file under the global dir,
# so registry / node / updater locks never collide with one another.

def _hash_dir(global_dir: str) -> str:
    import hashlib

    return hashlib.md5(canonical_dir(global_dir).encode("utf-8")).hexdigest()[:16]


def registry_lock(global_dir: str, timeout: float = 10.0) -> NamedLock:
    h = _hash_dir(global_dir)
    return NamedLock(
        f"WinZappRegistry_{h}",
        os.path.join(global_dir, "registry.lock"),
        timeout=timeout,
    )


def node_lock(global_dir: str, timeout: float = 30.0) -> NamedLock:
    h = _hash_dir(global_dir)
    return NamedLock(
        f"WinZappNode_{h}",
        os.path.join(global_dir, "node_coord", "node.lock"),
        timeout=timeout,
    )


def updater_lock(global_dir: str, timeout: float = 10.0) -> NamedLock:
    h = _hash_dir(global_dir)
    return NamedLock(
        f"WinZappUpdater_{h}",
        os.path.join(global_dir, "updater.lock"),
        timeout=timeout,
    )
