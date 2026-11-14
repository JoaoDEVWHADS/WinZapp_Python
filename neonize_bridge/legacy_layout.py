"""Brings a data folder written under the old (Portuguese) file names to the current
ones, so an account paired before the rename keeps its session and its messages.

Runs when the bridge starts, before any account is opened: nothing holds the files
yet. SQLite's sidecar files move together with their database. A name is only
moved when the new one does not exist, so a folder that has both is never
overwritten (the old file is left in place and a warning is logged)."""
import logging
import os

log = logging.getLogger("bridge")

#: files in the data folder itself
ROOT_FILES = {"segredo": "secret", "ativas.json": "active.json"}

#: files in each account's folder
ACCOUNT_FILES = {"ponte.db": "bridge.db", "sessao.db": "session.db",
                 "etiquetas.json": "labels.json"}

#: SQLite creates these next to a database while it is open (or after a crash)
SIDECARS = ("", "-wal", "-shm", "-journal")


def _move_group(folder, old, new, rename):
    """Moves `old` (and its sidecars) to `new`; True if the main file moved."""
    moves = [(old + suffix, new + suffix) for suffix in SIDECARS
             if os.path.exists(os.path.join(folder, old + suffix))]
    if not any(source == old for source, _ in moves):
        return False
    if any(os.path.exists(os.path.join(folder, target)) for _, target in moves):
        log.warning("both %s and %s exist; the old one was left in place", old, new)
        return False
    done = []
    try:
        for source, target in moves:
            rename(os.path.join(folder, source), os.path.join(folder, target))
            done.append((source, target))
    except OSError as error:
        for source, target in reversed(done):      # never leave a database half moved
            try:
                rename(os.path.join(folder, target), os.path.join(folder, source))
            except OSError:
                pass
        log.warning("could not rename %s to %s: %s", old, new, type(error).__name__)
        return False
    return True


def migrate(folder, rename=os.replace) -> int:
    """Renames the old files under `folder`; returns how many were moved."""
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return 0
    moved = 0
    for old, new in ROOT_FILES.items():
        moved += _move_group(folder, old, new, rename)
    for name in names:
        account = os.path.join(folder, name)
        if not os.path.isdir(account):
            continue
        for old, new in ACCOUNT_FILES.items():
            moved += _move_group(account, old, new, rename)
    if moved:
        log.info("data folder brought to the current file names (%d file(s))", moved)
    return moved
