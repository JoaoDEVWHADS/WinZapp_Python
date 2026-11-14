"""Which recorded WinZapp process is still alive, on the Mac.

update_coord (client/update_coord.py) records each account process as a
runtime lease (pid + creation time) and the update in progress as the same
pair, and lease_alive() decides whether that process still runs. Its answer
needs the creation time of a pid. On Windows it reads it through the Win32
API; elsewhere it uses psutil, and without psutil it can only say "exists" and
records 0.0, which lease_alive() then accepts for ANY process holding that
pid, unless _default_proc_matches_us() can prove the pid is not WinZapp — and
off Windows, without psutil, that returns None (cannot tell). Normal quits end
in os._exit(0), which skips the atexit that releases a lease, so 0.0 leases
pile up and stay "alive" forever once the pid is reused (measured on a real
install: 35 of them, one owned by a system daemon). Every update then refused
"another account is running", and a stale update in progress could make every
launch exit at once (main.py's start-up check).

The Mac build now ships psutil (build_app.py MAC_EXTRA), so creation times
are real again. On top of that, this layer answers _default_proc_matches_us()
by the process's own executable, psutil or not: a recorded pid now held by
anything but WinZapp (or, in a development run, this interpreter) is a dead
lease. update_coord looks that function up on every call, so its own
start-up gate, try_begin_update() and every lease listing reap the leaked
leases themselves; nothing is deleted by hand.

lease_alive() here is the strict rule for the Sparkle path's own decisions: a
lease recorded as 0.0 is dead outright when psutil works here (every live Mac
process then records its real creation time; a 0.0 lease is from before), and
so is one whose pid is not a WinZapp executable. If psutil ever failed to
import, the 0.0 rule is off (every lease would be 0.0) and the executable
check alone remains; build_app.py refuses to build without a working psutil.
"""

import logging
import os
import subprocess
import sys


def _process_name(pid):
    """(known, name): the executable name of *pid*, (True, "") when there is
    no such process, (False, "") when it cannot be told."""
    try:
        import psutil
        try:
            proc = psutil.Process(pid)
            names = {proc.name()}
            try:
                names.add(os.path.basename(proc.exe()))
            except psutil.Error:
                pass
            return True, "|".join(sorted(n for n in names if n))
        except psutil.NoSuchProcess:
            return True, ""
        except psutil.Error:
            return False, ""
    except ImportError:
        pass
    try:
        r = subprocess.run(["ps", "-o", "comm=", "-p", str(int(pid))],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return False, ""
    if r.returncode != 0 and not r.stdout.strip():
        return True, ""        # ps found no such process
    return True, os.path.basename(r.stdout.strip())


def _expected_names():
    """Executable names a live WinZapp process can have: the app's own
    (Contents/MacOS/WinZapp), and whatever this very process is reported as
    (a development run's interpreter: python.org's framework build is
    "Python", not sys.executable's "python3")."""
    names = {"winzapp"}
    for path in (sys.executable, os.path.realpath(sys.executable or "")):
        base = os.path.basename(path or "").lower()
        if base:
            names.add(base)
    known, own = _process_name(os.getpid())
    if known and own:
        names.update(n.lower() for n in own.split("|"))
    return names


def matches_us(pid):
    """True / False when *pid* is / is not a WinZapp process; None when it
    cannot be told (callers keep failing closed, as update_coord does)."""
    known, name = _process_name(pid)
    if not known:
        return None
    if not name:
        return False
    expected = _expected_names()
    return any(n.lower() in expected for n in name.split("|"))


def can_measure():
    """Whether this process records real creation times (psutil works). Only
    then is a 0.0 lease certainly a leaked one: in a build where psutil failed
    to import, every lease, this account's and the others' included, is 0.0."""
    try:
        import psutil
        return psutil.Process(os.getpid()).create_time() > 0
    except Exception:
        return False


def lease_alive(pid, create_time):
    """Strict liveness for a lease or update slot recorded on the Mac: a 0.0
    creation time is a leaked lease (dead) when this process can measure
    creation times, and a pid that is not a WinZapp executable is dead;
    otherwise update_coord's own pid + creation time match decides."""
    import update_coord
    if not create_time and can_measure():
        return False
    if matches_us(pid) is False:
        return False
    return update_coord.lease_alive(pid, create_time)


def install():
    import update_coord
    update_coord._default_proc_matches_us = matches_us
    logging.debug("[coord_mac] update_coord identifies WinZapp processes by executable")
