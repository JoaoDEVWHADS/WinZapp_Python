"""
Shared WPPConnect Node coordination for WinZapp multi-account (client/node_coord.py)
====================================================================================

One local WPPConnect Node server (port 6300) is shared by every account process.
This module decides — safely, across processes — when to start it, when to adopt
a running one, and when to stop it, so two accounts never fight over it and a
crash never leaves an orphan (plan Zad 3.0/3.1, GPT plan r3-r8 + code review).

Model (no "owner client" — GPT r5): 

  * installation_id — stable id for this WinZapp install (global/installation_id).
  * instance marker (global/node_instance.json) — describes the CURRENT Node:
    {state, instance_id, pid, create_time, startup_deadline?}. state ∈
    starting | ready | stopping.
  * Node identity endpoint /winzapp/identity returns {installation_id,
    instance_id, protocol_version, pid} so we verify a *specific* Node holds the
    port (not just "something is listening") and can recover its pid+create_time.
  * per-account node-leases (global/node_leases/<account_id>) — a live client
    that needs the Node. The Node is stopped only when the LAST live lease is
    ours (should_stop_node); a healthy Node with other live leases is left alone.

This module is pure/injectable (probe_identity, is_alive, now are parameters) so
the whole state machine is unit-tested without a real Node, HTTP, or psutil.
The actual spawn / HTTP GET / tree-kill live in the caller (main.py), driven by
the action dicts plan_startup() returns.
"""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from typing import Callable, Optional

from coord_locks import node_lock

PROTOCOL_VERSION = 1

_INSTALL_ID_FILE = "installation_id"
_MARKER_FILE = "node_instance.json"
_LEASE_DIR = "node_leases"
_STARTUP_TIMEOUT = 60.0  # seconds a 'starting' node has to expose identity


# ── strict scalar validation (mirrors update_coord) ──────────────────────────
def _valid_pid(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _valid_ct(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _atomic_write(path: str, payload: dict) -> None:
    tmp = f"{path}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ── installation identity ────────────────────────────────────────────────────
def installation_id(global_dir: str) -> str:
    """Stable per-install id (created once, persisted)."""
    path = os.path.join(global_dir, _INSTALL_ID_FILE)
    with node_lock(global_dir):
        try:
            with open(path, "r", encoding="utf-8") as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            pass
        v = uuid.uuid4().hex
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(v)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return v


def identity_matches(want: dict, got: Optional[dict]) -> bool:
    """True iff the identity payload describes OUR expected Node instance."""
    if not isinstance(got, dict):
        return False
    return (got.get("installation_id") == want.get("installation_id")
            and got.get("instance_id") == want.get("instance_id")
            and got.get("protocol_version") == want.get("protocol_version"))


# ── instance marker ──────────────────────────────────────────────────────────
def _marker_path(global_dir: str) -> str:
    return os.path.join(global_dir, _MARKER_FILE)


def write_instance_marker(global_dir: str, state: str, instance_id: str,
                          pid: Optional[int], create_time: Optional[float],
                          startup_deadline: Optional[float] = None) -> None:
    assert state in ("starting", "ready", "stopping")
    payload = {"state": state, "instance_id": instance_id,
               "pid": pid, "create_time": create_time}
    if startup_deadline is not None:
        payload["startup_deadline"] = startup_deadline
    with node_lock(global_dir):
        _atomic_write(_marker_path(global_dir), payload)


def read_instance_marker(global_dir: str) -> Optional[dict]:
    try:
        with open(_marker_path(global_dir), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("state") in ("starting", "ready", "stopping"):
            return data
    except (OSError, ValueError):
        pass
    return None


def clear_instance_marker(global_dir: str) -> None:
    with node_lock(global_dir):
        try:
            os.remove(_marker_path(global_dir))
        except OSError:
            pass


# ── per-account node leases ──────────────────────────────────────────────────
def _lease_dir(global_dir: str) -> str:
    d = os.path.join(global_dir, _LEASE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def add_node_lease(global_dir: str, account_id: str, pid: int, create_time: float) -> None:
    with node_lock(global_dir):
        _atomic_write(os.path.join(_lease_dir(global_dir), account_id),
                      {"account_id": account_id, "pid": pid,
                       "create_time": create_time, "at": int(time.time())})


def release_node_lease(global_dir: str, account_id: str) -> None:
    with node_lock(global_dir):
        try:
            os.remove(os.path.join(_lease_dir(global_dir), account_id))
        except OSError:
            pass


def _live_leases_locked(global_dir: str, is_alive: Callable[[int, float], bool]) -> list[dict]:
    d = _lease_dir(global_dir)
    live: list[dict] = []
    for fname in os.listdir(d):
        if fname.endswith(".tmp"):
            try:
                os.remove(os.path.join(d, fname))
            except OSError:
                pass
            continue
        path = os.path.join(d, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lease = json.load(f)
            pid, ct = lease["pid"], lease["create_time"]
        except (OSError, ValueError, KeyError, TypeError):
            live.append({"account_id": fname, "_name": fname, "_corrupt": True})
            continue
        if not _valid_pid(pid) or not _valid_ct(ct):
            live.append({"account_id": lease.get("account_id", fname),
                         "_name": fname, "_corrupt": True})
            continue
        if is_alive(pid, float(ct)):
            live.append(lease)
        else:
            try:
                os.remove(path)
            except OSError:
                pass
    return live


def live_node_leases(global_dir: str, is_alive: Callable[[int, float], bool]) -> list[dict]:
    with node_lock(global_dir):
        return _live_leases_locked(global_dir, is_alive)


def should_stop_node(live_account_ids: list, releasing: str) -> bool:
    """True iff the ONLY remaining live lease is the one we're releasing, so
    stopping the Node won't cut off another live account (plan Zad 3.1 MVP)."""
    others = [a for a in live_account_ids if a != releasing]
    return not others and releasing in live_account_ids


# ── startup planning (start / adopt / finish-stop) ───────────────────────────
def plan_startup(global_dir: str, now: Optional[float] = None,
                 probe_identity: Callable[[], Optional[dict]] = lambda: None,
                 is_alive: Callable[[int, float], bool] = lambda p, c: False) -> dict:
    """Decide what to do about the Node at startup, under node_lock.

    Returns an action dict:
      {"action": "adopt", "identity": {...}}   -> a healthy matching Node runs
      {"action": "start_new"}                  -> (re)start a fresh Node
    Recovery rules (GPT r4 #1 / r5 #4 / r6 #3):
      * stopping marker: never adopt — finish the stop + start fresh.
      * starting marker: wait for identity until startup_deadline; past it with
        no identity -> stale, start fresh.
      * ready marker: adopt only if identity endpoint confirms OUR instance.
    """
    if now is None:
        now = time.monotonic()
    want_install = installation_id(global_dir)
    with node_lock(global_dir):
        marker = read_instance_marker(global_dir)
        if marker is None:
            return {"action": "start_new"}

        state = marker.get("state")
        want = {"installation_id": want_install,
                "instance_id": marker.get("instance_id"),
                "protocol_version": PROTOCOL_VERSION}

        if state == "stopping":
            # Must be finished and cleared; never adopted.
            return {"action": "start_new"}

        if state == "starting":
            deadline = marker.get("startup_deadline", 0.0)
            ident = probe_identity()
            if identity_matches(want, ident):
                return {"action": "adopt", "identity": ident}
            if now < deadline:
                return {"action": "wait", "until": deadline}
            return {"action": "start_new"}

        if state == "ready":
            ident = probe_identity()
            if identity_matches(want, ident):
                return {"action": "adopt", "identity": ident}
            return {"action": "start_new"}

    return {"action": "start_new"}
