"""
Process-safe account registry for WinZapp multi-account (client/accounts.py)
============================================================================

Stores the set of WhatsApp accounts and which one was last brought to the
foreground, in ``<global_dir>/accounts.json``. Every mutation runs inside the
process-wide ``registry_lock`` (see coord_locks.py) as a single
read-modify-write transaction with an atomic tmp+os.replace, so two WinZapp
processes racing on the file never lose each other's changes.

Design points (from the reviewed plan, Zadanie 1.2):
  * Account id = full uuid4 hex (32 chars). Validated with ^[0-9a-f]{32}$ on
    every load so a hand-edited/corrupt entry can never be used to build a path
    outside accounts/ (path-traversal guard).
  * States: pending / paired / deleting / archived.
  * order: explicit, STABLE integer used for the Ctrl+Shift+1..9 switch
    shortcuts; assigned max+1 on add, never reshuffled by rename/last_used.
  * last_foreground: the account last consciously raised to the foreground by
    the user. Only mutated by a deliberate user action (never by --background).
  * Corrupt accounts.json is NOT treated as empty: the registry enters
    read-only recovery mode (backs the file up as .corrupt-<ts>, blocks all
    mutations AND the automatic first-run) so a parse error can't spawn a new
    account that overwrites the registry and orphans existing account data.

This module never imports wx — it is pure logic and fully unit-testable.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Optional

from coord_locks import registry_lock

VALID_STATES = ("pending", "paired", "deleting", "archived")
_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_SCHEMA = 1


class RegistryCorruptError(RuntimeError):
    """Raised when a mutation is attempted while in read-only recovery mode."""


class AccountRegistry:
    def __init__(self, global_dir: str, lock_factory=registry_lock):
        self.global_dir = os.path.abspath(global_dir)
        self._path = os.path.join(self.global_dir, "accounts.json")
        self._lock_factory = lock_factory
        self._recovery = False
        os.makedirs(self.global_dir, exist_ok=True)
        # Probe once so is_recovery_mode() is meaningful right after construction.
        self._read()

    # ── recovery flag ────────────────────────────────────────────────────
    def is_recovery_mode(self) -> bool:
        return self._recovery

    # ── low-level read (no lock; callers hold it for RMW) ─────────────────
    def _read(self) -> dict:
        # Recovery is sticky for the instance lifetime: once we've seen a
        # corrupt file we must NOT silently behave as a fresh (empty) registry
        # just because the corrupt file was moved aside to its .corrupt-* backup.
        if self._recovery:
            return {"schema": _SCHEMA, "last_foreground": None, "accounts": []}
        if not os.path.isfile(self._path):
            self._recovery = False
            return {"schema": _SCHEMA, "last_foreground": None, "accounts": []}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, ValueError, OSError):
            self._enter_recovery()
            return {"schema": _SCHEMA, "last_foreground": None, "accounts": []}

        if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
            self._enter_recovery()
            return {"schema": _SCHEMA, "last_foreground": None, "accounts": []}

        # Drop entries with an invalid id (path-traversal / corruption guard).
        clean = [a for a in data["accounts"]
                 if isinstance(a, dict) and isinstance(a.get("id"), str)
                 and _ID_RE.match(a["id"])]
        data["accounts"] = clean
        self._recovery = False
        return data

    def _enter_recovery(self) -> None:
        self._recovery = True
        try:
            backup = f"{self._path}.corrupt-{int(time.time())}"
            if os.path.isfile(self._path) and not os.path.exists(backup):
                os.replace(self._path, backup)
        except OSError:
            pass

    # ── low-level atomic write ───────────────────────────────────────────
    def _write(self, data: dict) -> None:
        data["schema"] = _SCHEMA
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def _guard_mutation(self) -> None:
        # Re-read to catch a file that became corrupt after construction.
        if self._recovery:
            raise RegistryCorruptError(
                "accounts.json is corrupt — registry is in read-only recovery mode"
            )

    # ── transaction helper ───────────────────────────────────────────────
    def _txn(self, fn):
        """Run fn(data)->result under registry_lock as one RMW transaction."""
        with self._lock_factory(self.global_dir):
            data = self._read()
            if self._recovery:
                raise RegistryCorruptError(
                    "accounts.json is corrupt — registry is in read-only recovery mode"
                )
            result, changed = fn(data)
            if changed:
                self._write(data)
            return result

    # ── reads ────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        return self._read()["accounts"]

    def get(self, account_id: str) -> Optional[dict]:
        for a in self._read()["accounts"]:
            if a["id"] == account_id:
                return a
        return None

    def last_foreground(self) -> Optional[str]:
        return self._read().get("last_foreground")

    def list_paired(self) -> list[dict]:
        return sorted(
            [a for a in self.list() if a["state"] == "paired"],
            key=lambda a: a["order"],
        )

    def list_autostart_paired(self) -> list[dict]:
        return [a for a in self.list_paired() if a.get("autostart")]

    def data_dir_for(self, account_id: str) -> str:
        # accounts/<id> lives as a SIBLING of global/, never inside it.
        accounts_root = os.path.join(os.path.dirname(self.global_dir), "accounts")
        return os.path.join(accounts_root, account_id)

    # ── mutations (all under registry_lock) ──────────────────────────────
    def add(self, name: str, state: str = "pending") -> dict:
        if state not in VALID_STATES:
            raise ValueError(f"invalid state {state!r}")

        def _fn(data):
            now = int(time.time())
            next_order = max((a["order"] for a in data["accounts"]), default=0) + 1
            acc = {
                "id": uuid.uuid4().hex,
                "name": name,
                "state": state,
                "autostart": False,
                "order": next_order,
                "created_at": now,
                "last_used_at": now,
            }
            data["accounts"].append(acc)
            return acc, True

        return self._txn(_fn)

    def rename(self, account_id: str, name: str) -> None:
        def _fn(data):
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a["name"] = name
                    return None, True
            return None, False

        self._txn(_fn)

    def set_state(self, account_id: str, state: str) -> None:
        if state not in VALID_STATES:
            raise ValueError(f"invalid state {state!r}")

        def _fn(data):
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a["state"] = state
                    return None, True
            return None, False

        self._txn(_fn)

    def set_autostart(self, account_id: str, value: bool) -> None:
        def _fn(data):
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a["autostart"] = bool(value)
                    return None, True
            return None, False

        self._txn(_fn)

    def set_order(self, account_id: str, order: int) -> None:
        def _fn(data):
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a["order"] = int(order)
                    return None, True
            return None, False

        self._txn(_fn)

    def set_last_foreground(self, account_id: Optional[str]) -> None:
        def _fn(data):
            data["last_foreground"] = account_id
            return None, True

        self._txn(_fn)

    def touch_last_used(self, account_id: str) -> None:
        def _fn(data):
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a["last_used_at"] = int(time.time())
                    return None, True
            return None, False

        self._txn(_fn)

    def update_fields(self, account_id: str, **fields) -> None:
        """Atomically set several fields of one account in a single transaction.

        Used e.g. by archiving where state + autostart + last_foreground must
        change together (plan Zad. 4.5). ``last_foreground`` is a registry-level
        field and is handled specially when passed.
        """
        allowed = {"name", "state", "autostart", "order"}
        lf_sentinel = object()
        new_lf = fields.pop("last_foreground", lf_sentinel)
        bad = set(fields) - allowed
        if bad:
            raise ValueError(f"unknown fields {bad}")
        if "state" in fields and fields["state"] not in VALID_STATES:
            raise ValueError(f"invalid state {fields['state']!r}")

        def _fn(data):
            changed = False
            for a in data["accounts"]:
                if a["id"] == account_id:
                    a.update(fields)
                    changed = True
                    break
            if new_lf is not lf_sentinel:
                data["last_foreground"] = new_lf
                changed = True
            return None, changed

        self._txn(_fn)

    def remove(self, account_id: str) -> None:
        def _fn(data):
            before = len(data["accounts"])
            data["accounts"] = [a for a in data["accounts"] if a["id"] != account_id]
            if data.get("last_foreground") == account_id:
                data["last_foreground"] = None
            return None, len(data["accounts"]) != before

        self._txn(_fn)
