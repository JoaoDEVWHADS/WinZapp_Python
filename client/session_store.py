"""
Per-account WPPConnect session isolation for WinZapp (client/session_store.py)
==============================================================================

Each account owns a ``sessions.json`` under its data dir listing the WPPConnect
sessions it created, with status and (Fernet-encrypted) token. This backs the
session-cleanup invariant (plan Zad 3.2, GPT r2/r5): a process only ever closes
sessions it can PROVE are its own AND abandoned — never another account's, never
the current one, never one mid-pairing.

Session status:
  * active     — the session this account is currently using.
  * pairing    — a session being paired; the OLD session stays active until the
                 new one succeeds, and a crash mid-pairing does NOT auto-close it
                 (owner pid/create_time/attempt_id recorded for recovery).
  * abandoned  — a superseded session safe to close/logout.

Tokens are stored encrypted with the same per-account Fernet key that backs DB
payload/token encryption (``crypto`` is injected: token_vault in prod, a fake in
tests). A token that fails to decrypt is treated as absent — never a crash.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

_SESSIONS_FILE = "sessions.json"
VALID_STATUS = ("active", "pairing", "abandoned")


class SessionStore:
    def __init__(self, account_dir: str, crypto):
        self.account_dir = os.path.abspath(account_dir)
        self._path = os.path.join(self.account_dir, _SESSIONS_FILE)
        self._crypto = crypto
        os.makedirs(self.account_dir, exist_ok=True)

    # ── io ───────────────────────────────────────────────────────────────
    def _read(self) -> dict:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("sessions"), list):
                return data
        except (OSError, ValueError):
            pass
        return {"sessions": []}

    def _write(self, data: dict) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._path)

    def _decrypt(self, enc: Optional[str]) -> Optional[str]:
        if not enc:
            return None
        try:
            return self._crypto.decrypt(enc)
        except Exception:
            # Corrupt / wrong-key token -> treat as no token, never crash.
            return None

    def _decorate(self, s: dict) -> dict:
        out = dict(s)
        out["token"] = self._decrypt(s.get("token_enc"))
        out.pop("token_enc", None)
        return out

    # ── reads ────────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        return [self._decorate(s) for s in self._read()["sessions"]]

    def get(self, name: str) -> Optional[dict]:
        for s in self._read()["sessions"]:
            if s["name"] == name:
                return self._decorate(s)
        return None

    # ── mutations ────────────────────────────────────────────────────────
    def register(self, name: str, token: Optional[str], status: str = "active",
                 owner_pid: Optional[int] = None, owner_create_time: Optional[float] = None,
                 attempt_id: Optional[str] = None) -> dict:
        if status not in VALID_STATUS:
            raise ValueError(f"invalid status {status!r}")
        data = self._read()
        entry = {
            "name": name,
            "token_enc": self._crypto.encrypt(token) if token else None,
            "status": status,
            "created_at": int(time.time()),
        }
        if owner_pid is not None:
            entry["owner_pid"] = owner_pid
        if owner_create_time is not None:
            entry["owner_create_time"] = owner_create_time
        if attempt_id is not None:
            entry["attempt_id"] = attempt_id
        data["sessions"] = [s for s in data["sessions"] if s["name"] != name]
        data["sessions"].append(entry)
        self._write(data)
        return self._decorate(entry)

    def set_status(self, name: str, status: str) -> None:
        if status not in VALID_STATUS:
            raise ValueError(f"invalid status {status!r}")
        data = self._read()
        for s in data["sessions"]:
            if s["name"] == name:
                s["status"] = status
                self._write(data)
                return

    def remove(self, name: str) -> None:
        data = self._read()
        before = len(data["sessions"])
        data["sessions"] = [s for s in data["sessions"] if s["name"] != name]
        if len(data["sessions"]) != before:
            self._write(data)

    def ensure_from_legacy_token(self, name: str, token: str) -> dict:
        """Seed a session from a migrated legacy token if none exists yet."""
        existing = self.get(name)
        if existing is not None:
            return existing
        return self.register(name, token=token, status="active")


def sessions_to_close(sessions: list[dict], current_session: str) -> list[dict]:
    """Pure filter: sessions this account may safely close. ONLY 'abandoned'
    ones, and never the current session (plan Zad 3.2 / GPT r5 #5)."""
    return [s for s in sessions
            if s.get("status") == "abandoned" and s.get("name") != current_session]
