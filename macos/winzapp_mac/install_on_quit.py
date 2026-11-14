"""An update that installs when the app ends (Sparkle's installer waits for it).

Every account is a process of the app and Sparkle's installer watches only
one of them, so while an update is armed ending any account ends them all
(end_all) and the others are opened again after the install. Nothing here
imports Cocoa: sparkle_mac.py passes in what it knows (the main window, the
running tag, the other accounts) so every function can be tested directly.
"""

import json
import logging
import os
import subprocess

from . import update_accounts as accounts


def armed_path(mw):
    gd = getattr(mw, "global_dir", None)
    return os.path.join(gd, accounts.ARMED_FILE) if gd else ""


def record_armed(mw, tag):
    """Every account process reads this when it ends (end_all); without a
    global dir there is no other account to end."""
    path = armed_path(mw)
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(accounts.armed_record(tag), fh)
    except Exception:
        logging.exception("[sparkle_mac] could not record the update armed for quit")


def forget_armed(mw):
    path = armed_path(mw)
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        logging.exception("[sparkle_mac] could not remove %s", accounts.ARMED_FILE)


def installer_job(info):
    """*info*: the app's Info.plist dict."""
    return accounts.installer_job(info.get("CFBundleIdentifier", ""))


def installer_running(job):
    """Whether Sparkle's installer job still runs: True/False, or None when
    launchd could not be asked."""
    try:
        r = subprocess.run(["launchctl", "list", job],
                           capture_output=True, text=True, timeout=5)
        return accounts.installer_running(r.returncode, r.stdout)
    except Exception:
        logging.exception("[sparkle_mac] could not ask launchd about Sparkle's installer")
        return None


def armed_install(mw, running_tag, installer_is_running):
    """The tag of an update that installs when the app ends, or "". A record
    that no longer holds (installed, cancelled) is removed.
    *installer_is_running*: a callable, asked only when a record exists."""
    path = armed_path(mw)
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            record = json.load(fh)
    except Exception:
        record = None
    tag = accounts.armed_tag(record, running_tag,
                             installer_is_running() if record is not None else False)
    if not tag:
        forget_armed(mw)
    return tag


def end_all(mw, armed_of, other_accounts_of, job_of, launcher_of):
    """real_exit() of an account while an update is armed and other accounts
    run: the installer may be watching any of them, and installs the moment
    that one ends, under the others. So they are all ended
    (quit_all_accounts(), which comes back to real_exit() once they are gone),
    and the ones the user did not close are opened again after the install.
    True when that took over this exit. Never raises."""
    try:
        if getattr(mw, "_sparkle_ending_all", False):
            return False
        tag = armed_of(mw)
        if not tag:
            return False
        others = other_accounts_of(mw)
        if not others:
            return False
        mw._sparkle_ending_all = True
        logging.info("[sparkle_mac] %s installs on quit: ending %d other account(s) with this one",
                     tag, len(others))
        try:
            mw.output(mw.i18n.t("update_closing_other_accounts"), interrupt=True)
        except Exception:
            logging.debug("[sparkle_mac] could not speak", exc_info=True)
        command = accounts.relaunch_command(os.getpid(), job_of(), launcher_of(), others)
        subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        mw.quit_all_accounts()
        return True
    except Exception:
        logging.exception("[sparkle_mac] could not end the other accounts for the update")
        return False
