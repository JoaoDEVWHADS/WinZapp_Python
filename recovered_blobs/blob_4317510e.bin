"""
Updater coordination for WinZapp multi-account (client/update_coord.py)
=======================================================================

Closes the updater TOCTOU (plan Zad. 2.-1, GPT r5 #1 / r6 #1). Sits UNDER the
dedicated ``updater_lock`` (never the registry lock — see coord_locks) so the
updater's state file can't be corrupted by a registry write racing on a
different lock.

Two coordinated pieces:

  * runtime-lease — a per-process marker file ``global/runtime/<pid>_<ct>``.
    Each WinZapp process creates one VERY EARLY in bootstrap (before migration),
    under ``updater_lock``. The updater refuses to install while any *other*
    live runtime-lease exists, so files are never swapped under a running
    account process. Leases are keyed by (pid, process_create_time) so a reused
    PID from a long-dead process is never mistaken for a live holder.

  * update_state.json — ``{update_in_progress, owner_pid, owner_create_time}``
    in ``global/`` guarded ONLY by ``updater_lock``. Bootstrap consults it (also
    under the lock) and refuses to start while an install is in progress, so a
    new process can't spin up mid file-swap. A crashed updater (dead owner) is
    auto-recovered: the flag reads as not-in-progress.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Callable, Optional

from coord_locks import updater_lock

_RUNTIME_DIR = "runtime"
_STATE_FILE = "update_state.json"


# ── process liveness (pid + create_time, guards against PID reuse) ───────────
def _default_proc_create_time(pid: int) -> Optional[float]:
    """Return the process creation time for pid, or None if it doesn't exist.

    Uses psutil when available; otherwise falls back to a best-effort check
    (existence only) — on the real Windows target psutil ships with the app.
    """
    try:
        import psutil  # type: ignore

        if not psutil.pid_exists(pid):
            return None
        return psutil.Process(pid).create_time()
    except Exception:
        # Fallback: can't verify create_time -> report existence via os.kill(0).
        try:
            os.kill(pid, 0)
            return 0.0  # sentinel "alive, unknown create_time"
        except (OSError, ProcessLookupError):
            return None
        except Exception:
            return None


def lease_alive(pid: int, create_time: float,
                proc_create_time: Callable[[int], Optional[float]] = _default_proc_create_time) -> bool:
    """True iff a process with this pid AND matching create_time is alive.

    The create_time match defends against PID reuse: a new process that happens
    to get the same PID as a dead lease holder has a different create_time.
    The 0.0 sentinel (fallback path, unknown create_time) matches leases whose
    create_time was also recorded as 0.0.
    """
    ct = proc_create_time(pid)
    if ct is None:
        return False
    if ct == 0.0 or create_time == 0.0:
        return True  # fallback path: existence-only match
    return abs(ct - create_time) < 1e-6


# ── runtime leases ───────────────────────────────────────────────────────────
def _runtime_dir(global_dir: str) -> str:
    d = os.path.join(global_dir, _RUNTIME_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def create_runtime_lease(global_dir: str, pid: Optional[int] = None,
                         create_time: Optional[float] = None) -> str:
    """Create a runtime-lease for this process. Returns the lease filename.

    Held under updater_lock so it's atomic w.r.t. the updater's live-lease scan.
    Prefer ``try_create_runtime_lease`` in bootstrap: it refuses to create a
    lease while an update is in progress, closing the start-vs-install race.
    """
    if pid is None:
        pid = os.getpid()
    if create_time is None:
        ct = _default_proc_create_time(pid)
        create_time = ct if ct is not None else 0.0
    with updater_lock(global_dir):
        d = _runtime_dir(global_dir)
        lease_id = uuid.uuid4().hex[:8]
        fname = f"{pid}_{create_time}_{lease_id}"
        path = os.path.join(d, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "create_time": create_time,
                       "lease_id": lease_id, "started_at": int(time.time())}, f)
        return fname


def try_create_runtime_lease(global_dir: str, pid: Optional[int] = None,
                             create_time: Optional[float] = None,
                             is_alive: Callable[[int, float], bool] = lease_alive):
    """Atomically: if no update is in progress, create + return a lease name;
    else return None. The whole check+write runs under ONE updater_lock so a
    process can't slip a lease in after the updater scanned but before it set
    the in-progress flag (GPT r2-code #1)."""
    if pid is None:
        pid = os.getpid()
    if create_time is None:
        ct = _default_proc_create_time(pid)
        create_time = ct if ct is not None else 0.0
    with updater_lock(global_dir):
        if _is_update_in_progress_locked(global_dir, is_alive):
            return None
        d = _runtime_dir(global_dir)
        lease_id = uuid.uuid4().hex[:8]
        fname = f"{pid}_{create_time}_{lease_id}"
        with open(os.path.join(d, fname), "w", encoding="utf-8") as f:
            json.dump({"pid": pid, "create_time": create_time,
                       "lease_id": lease_id, "started_at": int(time.time())}, f)
        return fname


def release_runtime_lease(global_dir: str, lease_name: str) -> None:
    with updater_lock(global_dir):
        try:
            os.remove(os.path.join(global_dir, _RUNTIME_DIR, lease_name))
        except OSError:
            pass


def _live_leases_locked(global_dir: str, is_alive: Callable[[int, float], bool]) -> list[dict]:
    """Scan leases. Caller MUST hold updater_lock. A lease file that is
    unreadable or missing pid/create_time is treated as a LIVE unknown holder
    (fail-closed, GPT r2-code #5) — it blocks updates rather than being swept,
    because we cannot prove the owning process is dead."""
    d = _runtime_dir(global_dir)
    live: list[dict] = []
    for fname in os.listdir(d):
        path = os.path.join(d, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lease = json.load(f)
            pid = int(lease["pid"])
            ct = float(lease["create_time"])
        except (OSError, ValueError, KeyError, TypeError):
            # Corrupt/incomplete lease: cannot prove dead -> treat as live.
            live.append({"pid": None, "create_time": None, "_name": fname, "_corrupt": True})
            continue
        if is_alive(pid, ct):
            lease["_name"] = fname
            live.append(lease)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
    return live


def live_runtime_leases(global_dir: str, is_alive: Callable[[int, float], bool] = lease_alive) -> list[dict]:
    """Return live leases; sweep away provably-dead ones."""
    with updater_lock(global_dir):
        return _live_leases_locked(global_dir, is_alive)


# ── update_state.json ────────────────────────────────────────────────────────
def _state_path(global_dir: str) -> str:
    return os.path.join(global_dir, _STATE_FILE)


_CORRUPT_STATE = object()


def _read_state(global_dir: str):
    """Return the parsed state dict, or _CORRUPT_STATE if the file exists but is
    unreadable/invalid (fail-closed handling by callers, GPT r2-code #5)."""
    path = _state_path(global_dir)
    if not os.path.isfile(path):
        return {"update_in_progress": False, "owner_pid": None, "owner_create_time": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "update_in_progress" not in data:
            return _CORRUPT_STATE
        return data
    except (OSError, ValueError):
        return _CORRUPT_STATE


def _write_state(global_dir: str, state: dict) -> None:
    tmp = _state_path(global_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _state_path(global_dir))


def _is_update_in_progress_locked(global_dir: str,
                                  is_alive: Callable[[int, float], bool] = lease_alive) -> bool:
    """Caller holds updater_lock. Corrupt state -> True (fail-closed)."""
    state = _read_state(global_dir)
    if state is _CORRUPT_STATE:
        return True  # unknown -> block, don't fail-open
    if not state.get("update_in_progress"):
        return False
    pid = state.get("owner_pid")
    ct = state.get("owner_create_time")
    if pid is None or not is_alive(int(pid), float(ct if ct is not None else 0.0)):
        # dead owner -> recover the stale flag
        _write_state(global_dir, {"update_in_progress": False,
                                  "owner_pid": None, "owner_create_time": None})
        return False
    return True


def try_begin_update(global_dir: str, pid: Optional[int] = None,
                     create_time: Optional[float] = None,
                     is_alive: Callable[[int, float], bool] = lease_alive):
    """Atomically claim the update slot. Returns an owner-token dict on success,
    or None if another live updater owns it OR any account process is still
    running. All check+write under ONE updater_lock (GPT r2-code #1,#2)."""
    if pid is None:
        pid = os.getpid()
    if create_time is None:
        ct = _default_proc_create_time(pid)
        create_time = ct if ct is not None else 0.0
    with updater_lock(global_dir):
        if _is_update_in_progress_locked(global_dir, is_alive):
            return None  # another live updater owns the slot
        if _live_leases_locked(global_dir, is_alive):
            return None  # accounts still running -> refuse install
        token = {"owner_pid": pid, "owner_create_time": create_time}
        _write_state(global_dir, {"update_in_progress": True, **token})
        return token


def begin_update(global_dir: str, pid: Optional[int] = None,
                 create_time: Optional[float] = None) -> None:
    """Unconditional begin (test/back-compat). Prefer try_begin_update."""
    if pid is None:
        pid = os.getpid()
    if create_time is None:
        ct = _default_proc_create_time(pid)
        create_time = ct if ct is not None else 0.0
    with updater_lock(global_dir):
        _write_state(global_dir, {"update_in_progress": True,
                                  "owner_pid": pid, "owner_create_time": create_time})


def end_update(global_dir: str, token: Optional[dict] = None) -> bool:
    """Clear the update slot. If a token is given, only the matching owner may
    clear it (GPT r2-code #2), so a stale updater can't wipe a newer one's
    state. Returns True if cleared."""
    with updater_lock(global_dir):
        state = _read_state(global_dir)
        if state is _CORRUPT_STATE:
            state = {}
        if token is not None:
            if (state.get("owner_pid") != token.get("owner_pid")
                    or state.get("owner_create_time") != token.get("owner_create_time")):
                return False
        _write_state(global_dir, {"update_in_progress": False,
                                  "owner_pid": None, "owner_create_time": None})
        return True


def is_update_in_progress(global_dir: str,
                          is_alive: Callable[[int, float], bool] = lease_alive) -> bool:
    """True iff an update is in progress AND its owner is alive (crashed owner
    auto-recovered). Corrupt state file -> True (fail-closed)."""
    with updater_lock(global_dir):
        return _is_update_in_progress_locked(global_dir, is_alive)


# ── pure decision helpers (unit-tested) ──────────────────────────────────────
def should_block_start(update_state: dict) -> bool:
    return bool(update_state.get("update_in_progress"))


def should_block_update(live_leases: list) -> bool:
    return len(live_leases) > 0
