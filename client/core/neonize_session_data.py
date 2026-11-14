"""Deleting an account's data from the neonize bridge.

With the Neonize engine the WhatsApp keys and every message of an account live
in the bridge's data folder, one ``<session>/`` each (``session.db``, ``bridge.db``),
which only the bridge can remove: it keeps both files open. Removing an account
(account_removal.py) and cleaning up abandoned pairing attempts therefore ask
the bridge, through its ``delete-session`` route (neonize_bridge/cleanup.py),
which logs the device out, stops the session and removes the folder.

The HTTP call is a parameter, so the rules are tested without a bridge.
"""

import logging

from core.api_client import api_post

#: Logging out of WhatsApp is a network round trip on the bridge's side.
DELETE_TIMEOUT = 40


def delete_session(base_url: str, secret: str, name: str, *, post=api_post) -> bool:
    """Ask the bridge at ``base_url`` ("http://127.0.0.1:6300") to delete session
    ``name``. True when it confirmed (a session it never had counts: the data
    is gone); False when it could not be reached or refused, so the caller
    keeps the work to retry."""
    try:
        minted = post(f"{base_url}/api/{name}/{secret}/generate-token", timeout=10)
        token = minted.json().get("token") if minted.status_code in (200, 201) else None
        if not token:
            logging.warning("[neonize] no token to delete session %s (HTTP %s)",
                            name[:12], minted.status_code)
            return False
        response = post(f"{base_url}/api/{name}:{token}/delete-session",
                        timeout=DELETE_TIMEOUT)
    except Exception as error:
        # type only: a requests error repeats the URL, and the secret is in it
        logging.warning("[neonize] could not delete session %s: %s",
                        name[:12], type(error).__name__)
        return False
    if response.status_code == 200:
        logging.info("[neonize] session %s deleted from the bridge", name[:12])
        return True
    logging.warning("[neonize] the bridge refused to delete session %s (HTTP %s)",
                    name[:12], response.status_code)
    return False


def bridge_deleter(base_url: str, secret: str):
    """``name -> bool`` for account_removal: delete a session on this bridge."""
    return lambda name: delete_session(base_url, secret, name)


def startup_deleter(global_dir: str):
    """The deleter for finish_pending_deletions() before any window exists:
    None unless the install runs on the Neonize engine. It can only work when a
    bridge already answers (another account's); otherwise the leftover waits
    for the bridge this process starts later
    (MainWindow._finish_pending_deletions_on_bridge)."""
    from app_settings import AppSettings
    from core import connection_engine as engines
    from core import neonize_bridge_process as bridge

    app = AppSettings(global_dir)
    # The port is each account's own; the address alone tells the bridge apart.
    engine = engines.engine_to_keep(
        app.get("wpp_engine"), app.get("wpp_custom_api"), app.get("wpp_server"),
        app.get("wpp_ws_server"), engines.NEONIZE_PORT)
    if engine != engines.NEONIZE:
        return None
    secret = bridge.read_secret(bridge.bridge_dir())
    if secret and bridge.port_open(engines.NEONIZE_PORT):
        return bridge_deleter(f"{engines.NEONIZE_SERVER}:{engines.NEONIZE_PORT}", secret)
    return lambda name: False
