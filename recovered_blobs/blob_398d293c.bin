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


def release_runtime_lease(global_dir: str, lease_name: str) -> None:
    with updater_lock(global_dir):
        try:
            os.remove(os.path.join(global_dir, _RUNTIME_DIR, lease_name))
        except OSError:
            pass


def live_runtime_leases(global_dir: str, is_alive: Callable[[int, float], bool] = lease_alive) -> list[dict]:
    """Return live leases; sweep away dead ones (crashed processes)."""
    d = _runtime_dir(global_dir)
    live: list[dict] = []
    with updater_lock(global_dir):
        for fname in os.listdir(d):
            path = os.path.join(d, fname)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    lease = json.load(f)
            except (OSError, ValueError):
                # unreadable lease -> remove
                try:
                    os.remove(path)
                except OSError:
                    pass
                continue
            if is_alive(int(lease["pid"]), float(lease["create_time"])):
                lease["_name"] = fname
                live.append(lease)
            else:
                try:
                    os.remove(path)
                except OSError:
                    pass
    return live


# ── update_state.json ────────────────────────────────────────────────────────
def _state_path(global_dir: str) -> str:
    return os.path.join(global_dir, _STATE_FILE)


def _read_state(global_dir: str) -> dict:
    try:
        with open(_state_path(global_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"update_in_progress": False, "owner_pid": None, "owner_create_time": None}


def _write_state(global_dir: str, state: dict) -> None:
    tmp = _state_path(global_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, _state_path(global_dir))


def begin_update(global_dir: str, pid: Optional[int] = None,
                 create_time: Optional[float] = None) -> None:
    if pid is None:
        pid = os.getpid()
    if create_time is None:
        ct = _default_proc_create_time(pid)
        create_time = ct if ct is not None else 0.0
    with updater_lock(global_dir):
        _write_state(global_dir, {
            "update_in_progress": True,
            "owner_pid": pid,
            "owner_create_time": create_time,
        })


def end_update(global_dir: str) -> None:
    with updater_lock(global_dir):
        _write_state(global_dir, {
            "update_in_progress": False,
            "owner_pid": None,
            "owner_create_time": None,
        })


def is_update_in_progress(global_dir: str,
                          is_alive: Callable[[int, float], bool] = lease_alive) -> bool:
    """True iff an update is in progress AND its owner process is still alive.

    A crashed updater (dead owner) is auto-recovered: the stale flag is cleared
    and False is returned, so a dead install never permanently blocks startup.
    """
    with updater_lock(global_dir):
        state = _read_state(global_dir)
        if not state.get("update_in_progress"):
            return False
        pid = state.get("owner_pid")
        ct = state.get("owner_create_time")
        if pid is None or not is_alive(int(pid), float(ct if ct is not None else 0.0)):
            # dead owner -> recover
            _write_state(global_dir, {
                "update_in_progress": False,
                "owner_pid": None, "owner_create_time": None,
            })
            return False
        return True


# ── pure decision helpers (unit-tested) ──────────────────────────────────────
def should_block_start(update_state: dict) -> bool:
    return bool(update_state.get("update_in_progress"))


def should_block_update(live_leases: list) -> bool:
    return len(live_leases) > 0
