"""The other accounts and the update slot of a Sparkle update, without Cocoa.

Every account is its own process. Before an update the user installs from
Sparkle's window the other accounts quit and WinZapp claims update_coord's
update slot (sparkle_mac explains why that order); when the update does not
install they are opened again. An update Sparkle downloaded in the background
installs instead when the app ends, and its installer waits for one account
process only, so ending any account while it is armed ends them all and opens
the others again once the installer is done (armed_tag(), RELAUNCH_SCRIPT).
This is the decision logic of that, as plain functions: each takes the
client collaborator it needs (update_coord's lease listing and slot, ipc's quit
request, the process spawner) as an argument, so it is tested on every
platform with fakes (tests/test_macos_update_accounts.py) and sparkle_mac
passes the real ones. The module imports nothing from the client, objc or wx.
"""

import logging
import time

from . import provenance

LOG = "[sparkle_mac]"
# In the global dir, next to update_coord's files: the tag of an update
# Sparkle downloaded in the background and will install when the app ends.
ARMED_FILE = "sparkle_install_on_quit.json"
# Sparkle's installer is the launchd job "<bundle id>-sparkle-updater"
# (SUInstallerLauncher.m:259), running from the end of the download until the
# install is over.
INSTALLER_JOB_SUFFIX = "-sparkle-updater"
RELAUNCH_WAIT_STEPS = 240          # half-seconds the reopening waits for the installer

# Detached from WinZapp (it outlives it): wait for this process ($1) to end
# and Sparkle's installer job ($2) to finish, at most $3 half-seconds, then
# start each account ($5...) in the background with the app's executable ($4),
# as account_launcher.build_launch_command() starts one in a frozen build. It
# runs from /bin/sh, never from the bundle being replaced.
RELAUNCH_SCRIPT = """pid="$1"; job="$2"; limit="$3"; exe="$4"; shift 4
while kill -0 "$pid" 2>/dev/null; do sleep 0.5; done
n=0
while [ "$n" -lt "$limit" ] && launchctl list "$job" 2>/dev/null | grep -q '"PID"'; do
  sleep 0.5; n=$((n + 1))
done
for account in "$@"; do
  "$exe" --account "$account" --startup-source user --background >/dev/null 2>&1 &
done
"""


def other_accounts(account_id, leases):
    """The account ids other than *account_id* with a live runtime lease.
    *leases* is node_coord.live_node_leases(), already filtered by the liveness
    rule; a corrupt record, one without an id and this account are left out."""
    if not account_id:
        return []
    others = [lease.get("account_id") for lease in leases if not lease.get("_corrupt")]
    return sorted({a for a in others if a and a != account_id})


def quit_accounts(others, request_quit):
    """The peer walk of MainWindow.quit_all_accounts(), without exiting: each
    account closes its WhatsApp session and confirms before the next. One that
    fails does not stop the others."""
    for other in others:
        try:
            logging.info("%s asking account %s to quit before the update", LOG, other)
            request_quit(other)
        except Exception:
            logging.exception("%s request_quit failed for %s", LOG, other)
    if others:
        logging.info("%s other accounts asked to quit: %d", LOG, len(others))


def claim_slot(try_begin, attempts, wait, sleep=time.sleep):
    """The update slot token, or None while another account still runs.
    *try_begin*() is update_coord.try_begin_update with its liveness rule: a
    token, or None when an account is alive. The quitting accounts drop their
    leases as they exit, so *attempts* tries are made, *wait* seconds apart.
    An exception from *try_begin* is a refusal at once, not a retry."""
    for _ in range(attempts):
        try:
            token = try_begin()
        except Exception:
            logging.exception("%s try_begin_update failed — not updating", LOG)
            return None
        if token is not None:
            return token
        sleep(wait)
    return None


def release_slot(token, end_update):
    """Give the slot back (*end_update*(token)); nothing to give back for no
    token. Never raises."""
    if not token:
        return
    try:
        end_update(token)
    except Exception:
        logging.exception("%s end_update failed", LOG)


def accounts_to_reopen(closed, running):
    """Of the accounts closed for the update, those that are not running now
    (one that never quit still is), in the order they were closed."""
    running = set(running)
    return [a for a in closed if a not in running]


def reopen_accounts(accounts, spawn, announce):
    """Start again each account in *accounts* (*spawn*(account) launches one in
    the background) and *announce*() once. Nothing for an empty list. Never
    raises: a failure is logged and the rest are not attempted."""
    if not accounts:
        return
    try:
        for account in accounts:
            logging.info("%s reopening account %s", LOG, account)
            spawn(account)
        announce()
    except Exception:
        logging.exception("%s reopening the other accounts failed", LOG)


def pop_verdict(verdicts, tag, now, ttl):
    """The offer-time answer stored for *tag*, removed from *verdicts*, or None
    when there is none or it is older than *ttl* seconds (asked again)."""
    entry = verdicts.pop(tag, None)
    if entry is None or now - entry[0] > ttl:
        return None
    return entry[1]


def armed_record(tag):
    """What ARMED_FILE holds for an update to *tag*."""
    return {"tag": tag}


def armed_tag(record, running_tag, installer_running):
    """The tag of an update that installs when the app ends, or "".

    *record* is ARMED_FILE read back (None when there is none or it is
    unreadable); *installer_running* is installer_running()'s answer. A tag
    that is not newer than the running one was installed (or is a leftover);
    an installer that is gone was cancelled or finished. Only when launchd
    cannot be asked (None) does the record alone count: ending every account
    for nothing costs a restart, one left running costs its bundle being
    replaced under it."""
    tag = record.get("tag") if isinstance(record, dict) else None
    if not provenance.tag_is_newer(tag, running_tag):
        return ""
    return "" if installer_running is False else tag


def installer_job(bundle_id):
    """The launchd label of Sparkle's installer for *bundle_id*, or ""."""
    return f"{bundle_id}{INSTALLER_JOB_SUFFIX}" if bundle_id else ""


def installer_running(returncode, output):
    """`launchctl list <job>`: True while the job has a process, False when
    it has none or does not exist."""
    return returncode == 0 and '"PID"' in (output or "")


def relaunch_command(pid, job, exe, accounts, steps=RELAUNCH_WAIT_STEPS):
    """argv of the detached shell that opens *accounts* again after the
    install (RELAUNCH_SCRIPT)."""
    return ["/bin/sh", "-c", RELAUNCH_SCRIPT, "winzapp-reopen",
            str(int(pid)), job, str(int(steps)), exe, *accounts]
