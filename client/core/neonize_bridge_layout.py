"""Brings the neonize bridge's own folders to the current names.

Before the bridge's files were named in English, an install kept the bridge's
sessions in ``neonize_bridge/dados-real/`` and the client's own files (pid,
output, registered clients) in ``neonize_bridge/execucao/``. Those folders
hold an account's WhatsApp keys, so they are renamed in place, never recreated:
a new empty folder would ask the user to pair again.

The files inside the data folder are renamed by the bridge itself when it
starts (``neonize_bridge/legacy_layout.py``). The folders are renamed here, by
the client, and only while no bridge is running: a running bridge holds its
files open (and Windows refuses to rename them).
"""

import logging
import os
import time

log = logging.getLogger("neonize_bridge")

#: the data folder rename is tried a few times: a bridge just stopped lets go of its files late
RENAME_ATTEMPTS = 6
RENAME_PAUSE = 0.5

#: folder of the bridge -> current name
LEGACY_FOLDERS = {"dados-real": "data", "execucao": "run"}

#: entry of the run folder -> current name
LEGACY_RUN_ENTRIES = {"ponte.pid": "bridge.pid", "ponte.log": "bridge.log",
                      "ponte.log.1": "bridge.log.1", "ponte.lock": "bridge.lock",
                      "clientes": "clients"}


def legacy_pid_file(bridge: str) -> str:
    """Where an older WinZapp wrote the pid of the bridge it started."""
    return os.path.join(bridge, "execucao", "ponte.pid")


def legacy_clients_dir(bridge: str) -> str:
    """Where an older WinZapp registered the clients using the bridge."""
    return os.path.join(bridge, "execucao", "clientes")


def stranded(bridge: str) -> bool:
    """True when the legacy data folder is still there and the current one is not:
    starting a bridge now would open an empty folder and ask the user to pair again."""
    return (os.path.isdir(os.path.join(bridge, "dados-real"))
            and not os.path.isdir(os.path.join(bridge, "data")))


def _rename(parent, old, new, rename):
    source, target = os.path.join(parent, old), os.path.join(parent, new)
    if not os.path.exists(source):
        return False
    if os.path.isdir(target) and not os.listdir(target):
        try:
            os.rmdir(target)    # an empty folder created meanwhile never holds data
        except OSError as error:
            log.warning("could not replace the empty %s: %s", new, type(error).__name__)
            return False
    if os.path.exists(target):
        log.warning("both %s and %s exist in %s; the old one was left in place",
                    old, new, os.path.basename(parent) or parent)
        return False
    try:
        rename(source, target)
    except OSError as error:
        log.warning("could not rename %s to %s: %s", old, new, type(error).__name__)
        return False
    return True


def sibling_bridge(bridge: str) -> str:
    """Where a checkout-style install kept the bridge: ``neonize_bridge/`` next to
    the WinZapp folder, before the bridge shipped inside it."""
    return os.path.join(os.path.dirname(os.path.dirname(bridge)), "neonize_bridge")


def sibling_runtime(sibling: str) -> list:
    """(pid file, clients folder) of a bridge started from ``sibling``, under both
    the current and the old names."""
    return [(os.path.join(sibling, "run", "bridge.pid"), os.path.join(sibling, "run", "clients")),
            (os.path.join(sibling, "execucao", "ponte.pid"),
             os.path.join(sibling, "execucao", "clientes"))]


def sibling_has_data(bridge: str) -> bool:
    """True when a checkout-style install next to this one holds sessions."""
    sibling = sibling_bridge(bridge)
    if os.path.normcase(os.path.abspath(sibling)) == os.path.normcase(os.path.abspath(bridge)):
        return False
    for folder in LEGACY_FOLDERS:
        for name in (folder, LEGACY_FOLDERS[folder]):
            path = os.path.join(sibling, name)
            if name in ("data", "dados-real") and os.path.isdir(path) and os.listdir(path):
                return True
    return False


def adopt_sibling_data(bridge: str, target: str, sibling_running: bool = False,
                       move=os.rename, sleep=time.sleep) -> str:
    """Brings the sessions of such an install into ``target``, the data folder of
    the bridge that now ships inside WinZapp, so the paired accounts stay paired.
    Returns "moved", "failed" (the data is still where it was: do not start a
    bridge on an empty folder) or "" when there is nothing to adopt.

    The move is a rename and nothing else: it is atomic, and when a running bridge
    holds the files it fails whole, where a copy-and-delete fallback would leave
    a stale copy for the new bridge and a half-deleted original."""
    if not sibling_has_data(bridge):
        return ""
    sibling = sibling_bridge(bridge)
    if sibling_running:
        log.warning("a bridge of the older install is still running; its data was not moved")
        return "failed"
    migrate(sibling, running=False)         # an older name is brought to the current one first
    source = os.path.join(sibling, "data")
    if not os.path.isdir(source) or not os.listdir(source):
        return ""
    if os.path.isdir(target) and os.listdir(target):
        return ""                           # this install already has its own data
    try:
        if os.path.isdir(target):
            os.rmdir(target)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        for attempt in range(RENAME_ATTEMPTS):
            try:
                move(source, target)
                break
            except PermissionError:
                # a bridge just stopped may not have released its files yet
                if attempt == RENAME_ATTEMPTS - 1:
                    raise
                sleep(RENAME_PAUSE)
    except OSError as error:
        log.warning("could not move the bridge data into %s: %s",
                    os.path.basename(os.path.dirname(target)), type(error).__name__)
        return "failed"
    log.info("neonize bridge data adopted from the older install")
    return "moved"


def migrate(bridge: str, running: bool, rename=os.rename) -> int:
    """Renames the legacy folders of ``bridge`` and returns how many entries
    moved. Does nothing while a bridge is ``running``."""
    if running:
        return 0
    moved = 0
    for old, new in LEGACY_FOLDERS.items():
        moved += _rename(bridge, old, new, rename)
    run = os.path.join(bridge, LEGACY_FOLDERS["execucao"])
    if os.path.isdir(run):
        for old, new in LEGACY_RUN_ENTRIES.items():
            moved += _rename(run, old, new, rename)
    if moved:
        log.info("neonize bridge folders brought to the current names (%d)", moved)
    return moved
