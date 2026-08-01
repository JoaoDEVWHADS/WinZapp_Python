"""
One-time migration: flat legacy data/ -> accounts/<default>/ (Zad. 2.1)
======================================================================

Turns a pre-multi-account install (everything in a single flat ``data/``) into
the new layout, creating a "default" account. Designed to be atomic and
crash-recoverable (plan Zad. 2.1 + GPT r3/r6/r7 review):

  * Runs entirely under ``registry_lock``.
  * Journal is consulted BEFORE the "registry already has accounts -> no-op"
    shortcut, so a crash after the registry commit but before the backup step
    is finished on the next run (GPT r6 #6).
  * Legacy sources are a FROZEN whitelist (settings.json, secret.key,
    messages.db, token.tk, media/, voice_messages/, media_failed.json, log/) —
    never the new global/ , accounts/ , .staging-* or legacy_backup_* dirs that
    also live under data/ (GPT r6/r7 #7).
  * Copy to ``.staging-<id>`` then atomic ``os.rename`` to accounts/<id>; verify
    the copy matches the source before committing (GPT r6 #3/#6).
  * State ``paired`` ONLY when a credible token exists; otherwise ``pending``
    (GPT r6 #6).
  * The legacy single-instance mutex is ACQUIRED and HELD for the whole
    migration, so a still-running old version can't race us (GPT r3/#6).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time
import uuid

from accounts import AccountRegistry
from coord_locks import registry_lock, canonical_dir

# Frozen whitelist of legacy entries (relative to flat data/).
_LEGACY_ENTRIES = (
    "settings.json", "secret.key", "messages.db", "token.tk",
    "media", "voice_messages", "media_failed.json", "log",
)
# Dirs that belong to the NEW layout and must never be treated as legacy source.
_NEW_LAYOUT = {"global", "accounts", "logs"}

_JOURNAL = "migration.journal"


def _data_root(global_dir: str) -> str:
    return os.path.dirname(os.path.abspath(global_dir))


def _has_legacy(data_root: str) -> bool:
    for probe in ("settings.json", "messages.db", "token.tk"):
        if os.path.isfile(os.path.join(data_root, probe)):
            return True
    return False


def _has_credible_token(staging: str) -> bool:
    """True if the migrated data carries a usable WA token (=> paired)."""
    if os.path.isfile(os.path.join(staging, "token.tk")):
        return True
    sp = os.path.join(staging, "settings.json")
    if os.path.isfile(sp):
        try:
            with open(sp, "r", encoding="utf-8") as f:
                pi = (json.load(f) or {}).get("privateinfo", {})
            return bool(pi.get("WA_token_protected") or pi.get("WA_token"))
        except (OSError, ValueError):
            return False
    return False


def _read_journal(global_dir: str) -> dict | None:
    try:
        with open(os.path.join(global_dir, _JOURNAL), "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_journal(global_dir: str, data: dict) -> None:
    tmp = os.path.join(global_dir, _JOURNAL + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, os.path.join(global_dir, _JOURNAL))


def _clear_journal(global_dir: str) -> None:
    try:
        os.remove(os.path.join(global_dir, _JOURNAL))
    except OSError:
        pass


def _legacy_mutex_name(data_root: str) -> str:
    # Mirrors autostart._get_dynamic_mutex_name() (md5 of the flat data path).
    h = hashlib.md5(canonical_dir(data_root).encode("utf-8")).hexdigest()
    return f"Global\\WinZappSingleInstance_{h}"


def _acquire_legacy_mutex(data_root: str):
    """Acquire (and return a handle to) the OLD single-instance mutex so a
    running old version can't race the migration. No-op handle on non-Windows.
    Returns (handle, ok). ok=False means an old instance is running."""
    if sys.platform != "win32":
        return None, True
    import ctypes  # pragma: no cover (Windows-only)
    from ctypes import wintypes

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    handle = k.CreateMutexW(None, True, _legacy_mutex_name(data_root))
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    if already:
        if handle:
            k.CloseHandle(handle)
        return None, False
    return handle, True


def _release_legacy_mutex(handle) -> None:
    if handle is None or sys.platform != "win32":
        return
    import ctypes  # pragma: no cover
    k = ctypes.windll.kernel32
    k.ReleaseMutex(handle)
    k.CloseHandle(handle)


def _copy_legacy(data_root: str, staging: str) -> None:
    os.makedirs(staging, exist_ok=True)
    for name in _LEGACY_ENTRIES:
        src = os.path.join(data_root, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(staging, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(src, dst)


def _verify_copy(data_root: str, staging: str) -> bool:
    """Every legacy source entry must be present in staging (completeness vs
    the source, not a fixed 3-file set — GPT r6 #6)."""
    for name in _LEGACY_ENTRIES:
        src = os.path.join(data_root, name)
        if not os.path.exists(src):
            continue
        dst = os.path.join(staging, name)
        if not os.path.exists(dst):
            return False
        if os.path.isfile(src) and os.path.getsize(src) != os.path.getsize(dst):
            return False
    return True


def _backup_legacy(data_root: str) -> None:
    """Move legacy entries out of the flat root into legacy_backup_<ts>/ (kept,
    not deleted). Only touches whitelisted entries; never new-layout dirs."""
    backup = os.path.join(data_root, f"legacy_backup_{int(time.time())}")
    os.makedirs(backup, exist_ok=True)
    for name in _LEGACY_ENTRIES:
        src = os.path.join(data_root, name)
        if name in _NEW_LAYOUT:
            continue
        if os.path.exists(src):
            try:
                shutil.move(src, os.path.join(backup, name))
            except (OSError, shutil.Error):
                pass


def _split_global_settings(global_dir: str, account_dir: str) -> None:
    """Extract global keys from the migrated account's settings.json into
    global/app.json, and rewrite the account settings.json without them.
    Best-effort: any error is swallowed so migration never fails on this."""
    try:
        from app_settings import AppSettings, split_legacy_settings

        sp = os.path.join(account_dir, "settings.json")
        if not os.path.isfile(sp):
            return
        with open(sp, "r", encoding="utf-8") as f:
            legacy = json.load(f)
        if not isinstance(legacy, dict):
            return
        glob, per = split_legacy_settings(legacy)
        app = AppSettings(global_dir)
        for k, v in glob.items():
            try:
                app.set(k, v)
            except KeyError:
                pass
        tmp = sp + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(per, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, sp)
    except Exception:
        pass


def migrate_if_needed(global_dir: str):
    """Perform migration if a legacy flat data/ dir exists and no registry yet.

    Returns the new default account id, or None (no legacy / already migrated).
    """
    global_dir = os.path.abspath(global_dir)
    os.makedirs(global_dir, exist_ok=True)
    data_root = _data_root(global_dir)

    with registry_lock(global_dir):
        # 1) Journal FIRST — finish/rollback an interrupted run before the
        #    "already has accounts -> no-op" shortcut (GPT r6 #6).
        journal = _read_journal(global_dir)
        if journal is not None:
            stage = journal.get("stage")
            tid = journal.get("target_id")
            if stage == "committed":
                # Registry commit happened; just finish the (idempotent) backup.
                if _has_legacy(data_root):
                    _backup_legacy(data_root)
                _clear_journal(global_dir)
                return None
            if stage == "staging" and tid:
                # Crash before commit: discard the staging dir and start over.
                shutil.rmtree(os.path.join(data_root, f".staging-{tid}"),
                              ignore_errors=True)
                _clear_journal(global_dir)

        reg = AccountRegistry(global_dir, lock_factory=registry_lock)
        if reg.is_recovery_mode() or reg.list():
            return None  # already migrated / registry present
        if not _has_legacy(data_root):
            return None

        # 2) Hold the legacy mutex so an old running version can't race us.
        handle, ok = _acquire_legacy_mutex(data_root)
        if not ok:
            raise RuntimeError(
                "An older WinZapp instance is running — close it before migrating."
            )
        try:
            acc_id = uuid.uuid4().hex
            staging = os.path.join(data_root, f".staging-{acc_id}")
            shutil.rmtree(staging, ignore_errors=True)
            _write_journal(global_dir, {"stage": "staging", "target_id": acc_id})

            _copy_legacy(data_root, staging)
            if not _verify_copy(data_root, staging):
                shutil.rmtree(staging, ignore_errors=True)
                _clear_journal(global_dir)
                raise RuntimeError("Migration copy verification failed")

            state = "paired" if _has_credible_token(staging) else "pending"

            # Atomic rename staging -> accounts/<id>
            dest = reg.data_dir_for(acc_id)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            os.rename(staging, dest)

            # 3) Commit to the registry, then journal=committed, then backup.
            acc = reg.add("default", state=state)
            # add() minted a fresh id; align the on-disk dir with it.
            if acc["id"] != acc_id:
                os.rename(dest, reg.data_dir_for(acc["id"]))
                acc_id = acc["id"]
            if state == "paired":
                reg.set_last_foreground(acc_id)

            # Split global settings (language/updates/tray/connection) out of the
            # migrated account's settings.json into global/app.json (Zad 2.3), so
            # they're shared across accounts. Best-effort: never fail migration.
            _split_global_settings(global_dir, reg.data_dir_for(acc_id))

            _write_journal(global_dir, {"stage": "committed", "target_id": acc_id})
            _backup_legacy(data_root)
            _clear_journal(global_dir)
            return acc_id
        finally:
            _release_legacy_mutex(handle)
