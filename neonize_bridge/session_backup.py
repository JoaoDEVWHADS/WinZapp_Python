"""`GET /api/<secret>/backup-sessions` and `POST /api/<secret>/restore-sessions`
(WPPConnect's miscController.backupAllSessions / restoreAllSessions).

A backup is a zip with one folder per paired account and, in it, the files
that make the account: `session.db` (whatsmeow's keys: the login itself),
`bridge.db` (the messages), `app_state.db`, `labels.json` and `carts.json`.
Each SQLite file is copied with SQLite's backup API, so a copy taken while the
bridge writes is still a consistent database. The zip holds the login of every
account: it goes only to whoever knows the bridge's secret (authentication.py),
as in WPPConnect.

A restore takes the same zip (multipart field `file`) and writes back, for each
account in it, only those files, and never over an account the bridge is
running (it is reported as skipped). It answers WPPConnect's
`{"error": false, "message": ...}` plus the accounts restored and skipped.

The pure functions are at the top (tested in test_session_backup.py).
"""
import io
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile

from aiohttp import web

import inputs

log = logging.getLogger("bridge")

DATABASES = ("session.db", "bridge.db", "app_state.db")
FILES = ("labels.json", "carts.json")
MAX_ZIP = 1024 ** 3
MAX_MEMBERS = 1000


def backup_members(folder, names) -> list:
    """(name in the zip, path on disk, is a database) of what a backup holds."""
    out = []
    for name in names:
        for file in DATABASES + FILES:
            path = os.path.join(folder, name, file)
            if os.path.isfile(path):
                out.append((f"{name}/{file}", path, file in DATABASES))
    return out


def copy_database(source, destination) -> None:
    """A consistent copy of a SQLite file that may be open and written."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def make_backup(folder, names) -> bytes:
    data = io.BytesIO()
    with tempfile.TemporaryDirectory() as scratch, \
            zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, path, database in backup_members(folder, names):
            if database:
                copy = os.path.join(scratch, arcname.replace("/", "_"))
                copy_database(path, copy)
                archive.write(copy, arcname)
            else:
                archive.write(path, arcname)
    return data.getvalue()


def restore_plan(member_names) -> dict:
    """{account: [file, ...]} of a restore zip; ValueError when it holds
    anything else (another path, another file, a folder in a folder)."""
    if len(member_names) > MAX_MEMBERS:
        raise ValueError("too many files")
    plan = {}
    for member in member_names:
        if member.endswith("/"):
            continue
        parts = member.split("/")
        if len(parts) != 2 or "\\" in member or not inputs.valid_session_name(parts[0]) \
                or parts[1] not in DATABASES + FILES:
            raise ValueError(f"unexpected file in the backup: {member}")
        plan.setdefault(parts[0], []).append(parts[1])
    if not plan:
        raise ValueError("the backup holds no account")
    return plan


def running(state, name) -> bool:
    account = state["sessions"].get(name)
    return account is not None and getattr(account, "client", None) is not None


def apply_restore(folder, archive, plan, busy) -> tuple:
    """Writes the plan's files; ([restored], [skipped])."""
    restored, skipped = [], []
    for name, files in sorted(plan.items()):
        if busy(name):
            skipped.append(name)
            continue
        target = os.path.join(folder, name)
        os.makedirs(target, exist_ok=True)
        for file in files:
            with archive.open(f"{name}/{file}") as source, \
                    open(os.path.join(target, file + ".restoring"), "wb") as out:
                shutil.copyfileobj(source, out)
            os.replace(os.path.join(target, file + ".restoring"), os.path.join(target, file))
            for leftover in ("-wal", "-shm"):     # an old journal must not replay over it
                if file in DATABASES and os.path.exists(os.path.join(target, file + leftover)):
                    os.remove(os.path.join(target, file + leftover))
        restored.append(name)
    return restored, skipped


def register_routes(r, *, state, folder):
    """Wire the routes to the aiohttp router `r`."""
    import asyncio

    from administration import sessions_on_disk

    async def backup(req):
        names = sessions_on_disk(folder)
        try:
            data = await asyncio.get_running_loop().run_in_executor(None, make_backup, folder,
                                                                    names)
        except Exception:
            log.exception("backup-sessions")
            return web.json_response({"status": False, "message": "Error on backup session"},
                                     status=500)
        return web.Response(body=data, content_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="backup-sessions.zip"'})

    async def restore(req):
        try:
            reader = await req.multipart()
            part = await reader.next()
            while part is not None and part.name != "file":
                part = await reader.next()
            if part is None:
                raise ValueError("send the backup in the field `file`")
            data = bytearray()
            while True:
                chunk = await part.read_chunk(1 << 20)
                if not chunk:
                    break
                data += chunk
                if len(data) > MAX_ZIP:
                    raise ValueError("the backup is too large")
            archive = zipfile.ZipFile(io.BytesIO(bytes(data)))
            plan = restore_plan(archive.namelist())
        except (ValueError, zipfile.BadZipFile, AssertionError) as error:
            return web.json_response({"status": False, "message": str(error)}, status=400)
        restored, skipped = await asyncio.get_running_loop().run_in_executor(
            None, apply_restore, folder, archive, plan, lambda name: running(state, name))
        log.info("sessions restored: %d, skipped (running): %d", len(restored), len(skipped))
        return web.json_response({"error": False, "message": "Sessions restored",
                                  "restored": restored, "skipped": skipped})

    r.add_get("/api/{secretkey}/backup-sessions", backup)
    r.add_post("/api/{secretkey}/restore-sessions", restore)
