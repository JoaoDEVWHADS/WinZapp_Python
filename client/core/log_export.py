"""Settings > Advanced > Export this account's logs: one zip for a bug report.

What goes in: every file in the current account's logs folder
(data/accounts/<id>/logs: log.log, shutdown_audit.log, wppconnect.log...),
under ``account/``, and, when the Neonize engine has run on this install, the
bridge's own log (bridge.log and the bridge.log.1 it keeps), under
``neonize_bridge/`` (docs/reference/diagnosing-from-logs.md asks for both).
Only the bridge's logs: its run folder also holds a pid file and the list of
clients using it.

A log the app is writing right now is read as it is at that moment. A file
that cannot be read is left out and named in the answer, so one locked file
never costs the whole export.
"""
import datetime
import os
import zipfile

ACCOUNT_FOLDER = "account"
BRIDGE_FOLDER = "neonize_bridge"
BRIDGE_LOG_PREFIX = "bridge.log"


def default_name(now=None) -> str:
    """The file name the save dialog proposes: winzapp-logs-YYYYMMDD-HHMM.zip."""
    now = now or datetime.datetime.now()
    return f"winzapp-logs-{now:%Y%m%d-%H%M}.zip"


def log_sources(account_logs, bridge_run=None) -> list:
    """[(path on disk, name in the zip)] of what an export carries, sorted;
    a folder that does not exist adds nothing."""
    sources = []
    for folder, prefix, keep in (
            (account_logs, ACCOUNT_FOLDER, lambda name: True),
            (bridge_run, BRIDGE_FOLDER, lambda name: name.startswith(BRIDGE_LOG_PREFIX))):
        if not folder or not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if os.path.isfile(path) and keep(name):
                sources.append((path, f"{prefix}/{name}"))
    return sources


def write_zip(target, sources) -> tuple:
    """Write `sources` into the zip `target`: (files written, names left out).
    Raises OSError when the zip itself cannot be written; a half-written zip
    is removed then."""
    written, skipped = 0, []
    try:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path, name in sources:
                try:
                    archive.write(path, name)
                    written += 1
                except OSError:
                    skipped.append(name)
    except OSError:
        try:
            os.remove(target)
        except OSError:
            pass
        raise
    return written, skipped
