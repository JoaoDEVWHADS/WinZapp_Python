"""Deleting an account from the bridge: `POST /api/<token>/delete-session`.

Whoever deletes an account in WinZapp (or undoes a pairing) has to take along
what the bridge kept of it: the WhatsApp keys (`session.db`) and all the
messages in plain text (`bridge.db`), in `<folder>/<name>`. Only the bridge can
do that: it keeps both SQLite files open, and on Windows an open file cannot be
deleted. The route: logs the account out (the device stops being linked on the
phone), stops the session, releases the files, deletes the folder and removes
the name from `active.json`.

It requires the session's normal credential (the middleware in authentication.py
checks the `<name>:<hash>` of `/api/{tok}/...`), so an account can only delete
itself. `POST /api/<name>/<secret>/clear-session-data` (WPPConnect's
miscController.clearSessionData) does the same for any account to whoever
knows the bridge's secret, and answers `{"success": true}`.

The pure functions are at the top (tested in test_cleanup.py). Nothing here
imports neonize.
"""
import asyncio
import logging
import os
import shutil

from aiohttp import web

import inputs
import session_backup
from redaction import redact

log = logging.getLogger("bridge")


def session_folder(folder, name):
    """The folder `<folder>/<name>` to delete, or None when it is not safe to.

    Only a direct child of `folder`: the name has to be a plain session name
    (no separator, no '..') and the resolved path has to remain that child,
    never a shortcut (symbolic link or junction) leading outside the bridge's
    data.
    """
    if not inputs.valid_session_name(name):
        return None
    base = os.path.realpath(folder)
    destination = os.path.join(base, name)
    if os.path.islink(destination):
        return None
    real = os.path.realpath(destination)
    if os.path.normcase(os.path.dirname(real)) != os.path.normcase(base):
        return None
    if os.path.normcase(os.path.basename(real)) != os.path.normcase(name):
        return None
    return destination


def delete_folder(folder, name, remove=shutil.rmtree) -> bool:
    """Deletes the session folder. True also when it no longer exists (asking
    again after a failure has to be able to finish the job). False if the
    folder stayed (file still open, no permission) or if the name is not safe."""
    destination = session_folder(folder, name)
    if destination is None:
        return False
    if not os.path.lexists(destination):
        return True
    try:
        remove(destination)
    except OSError as error:
        log.error("could not delete the session folder %s: %s", redact(name),
                  type(error).__name__)
        return False
    return not os.path.lexists(destination)


def shut_down(session) -> bool:
    """Logs out of the account, stops the session and releases its files. Returns
    whether the account was connected (only then is the device really unlinked)."""
    was_connected = session.client is not None and session.status == "CONNECTED"
    session.leave()
    if session.thread is not None:
        session.thread.join(10)
    try:
        session.db.close()
    except Exception:
        log.exception("closing the storage")
    mirror = getattr(session, "app_state", None)     # app_state_mirror's app_state.db
    if mirror is not None:
        try:
            mirror.close()
        except Exception:
            log.exception("closing the app state copy")
    return was_connected


def register_routes(r, *, ok, state, folder, mark_active):
    """Wire the route to the aiohttp router `r`."""

    async def remove_account(name):
        """(None, logged out) when the account's data is gone, else (error response, _)."""
        if state["fixed"] or session_folder(folder, name) is None:
            return web.json_response(
                {"status": "error", "message": "invalid session name"}, status=400), False
        loop = asyncio.get_running_loop()
        account = state["sessions"].pop(name, None)
        left = False
        if account is not None:
            left = await loop.run_in_executor(None, shut_down, account)
        mark_active(name, False)
        if not await loop.run_in_executor(None, delete_folder, folder, name):
            return web.json_response(
                {"status": "error", "message": "could not remove the session data"},
                status=500), left
        log.info("session deleted: %s", redact(name))
        return None, left

    async def delete_session(req):
        failure, left = await remove_account(req.match_info["tok"].split(":", 1)[0])
        if failure is not None:
            return failure
        return ok(status="success", response={"removed": True, "loggedOut": left})

    async def clear_session_data(req):
        failure, _left = await remove_account(req.match_info["session"])
        if failure is not None:
            return failure
        return web.json_response({"success": True})

    r.add_post("/api/{tok}/delete-session", delete_session)
    r.add_post("/api/{session}/{secretkey}/clear-session-data", clear_session_data)
    session_backup.register_routes(r, state=state, folder=folder)
