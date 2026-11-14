"""Updates through Sparkle 2, gated by the official repository's tags.

A release build whose Info.plist names a Sparkle feed and key
(sparkle_policy.configured(), written by build_app.py from
WINZAPP_SPARKLE_PUBLIC_KEY) updates through Sparkle's standard windows, which
VoiceOver reads well; the "Check for updates" menu item and the automatic
check WinZapp starts after launch go to Sparkle instead of UpdateChecker.
Without those keys, or if Sparkle.framework cannot be loaded or started,
nothing here runs and updater_mac goes on exactly as before.

What WinZapp checks (sparkle_policy explains why only this): the release is
an existing tag of the official repository pointing at the commit its
provenance declares, newer than the running tag
(updater_mac.release_provenance()), and the appcast item stands for exactly
that tag's full zip. Sparkle downloads, verifies (signed appcast, EdDSA, code
signing) and installs. Updates are downloaded in the background and installed
when WinZapp quits (sparkle_policy.plist_keys() explains the keys). With
Sparkle 2.10.0's public API only:

1. Before Sparkle shows or downloads a release: updater:shouldProceedWithUpdate:...
   (SPUUpdaterDelegate.h:252), Sparkle's one veto before anything is shown
   or downloaded (SPUBasicUpdateDriver.m:150-158), for the scheduled
   background download as for a check the user starts. It is synchronous on
   the main thread and the answer needs the network, so the first answer is a
   silent abort (SUInstallationCanceledError, SPUUIBasedUpdateDriver.m:
   482-483), the question runs on a thread, and its end starts the same kind
   of check again, which the stored verdict (at most VERDICT_TTL old) answers.
2. A scheduled check, with "check for updates automatically" on, downloads
   the release that passed 1 without a window (SPUAutomaticUpdateDriver.m:
   87-97) and leaves Sparkle's installer waiting for the app to end
   (:104-128); updater:willInstallUpdateOnQuit:immediateInstallationBlock:
   (SPUUpdaterDelegate.h:440) records it (update_accounts.ARMED_FILE) and
   answers NO, so Sparkle ends that cycle and its next check shows the update
   as downloaded, with "Install and Relaunch" (SPUUpdater.m:903-906,
   SPUUIBasedUpdateDriver.m:236-237). Quitting installs it. The installer
   watches only the first running process of the app
   (InstallerProgressAppController.m:292-308) and installs as soon as that
   one ends (AppInstaller.m:403-410), and every account is a process of the
   same app: so while an update is armed, ending any account ends them all
   (the real_exit wrapper below), and the accounts the user did not close are
   opened again once the installer is done (update_accounts.RELAUNCH_SCRIPT).
   No second provenance check is possible there: the install happens after
   the app is gone. Check 1 is its gate.
3. When the user chooses Install in Sparkle's window (WinZapp's subclass of
   Sparkle's standard user driver holds that reply,
   SPUUIBasedUpdateDriver.m:244-275): the appcast item is checked again
   (an update Sparkle resumes skipped step 1, SPUBasicUpdateDriver.m:150), the
   other accounts quit, and WinZapp claims update_coord's update slot, which
   keeps any account from starting until the update is over (main.py exits a
   new account process while is_update_in_progress()). Only then does Install
   reach Sparkle: for a release not downloaded yet, it downloads and prepares
   its installer; for one downloaded in the background (2), it installs and
   relaunches at once (SPUUIBasedUpdateDriver.m:273-274).
4. At "Ready to Install", after a download the user started
   (SPUUIBasedUpdateDriver.m:416-425): the official repository is asked again
   and the item checked again; only a fresh yes answers Install, anything
   else answers Skip, which there cancels the prepared installer
   (SPUCoreBasedUpdateDriver.m:313-314 -> SPUInstallerDriver.m:563-572 ->
   AppInstaller.m:681-684). Quitting with that window unanswered installs on
   quit, as in 2 (an installer past its first stage installs whenever the
   app ends, AppInstaller.m:731-744): the other accounts are already closed
   and the update slot stays held until this process is gone.

When the update does not install after the other accounts were closed for it
(the download failed or was cancelled, Sparkle aborted, the last check
refused), the slot is given back, those accounts are opened again in the
background, and WinZapp says so.

The release notes of Sparkle's window are WinZapp's own when it can make
them (sparkle_notes.py): what changed between the running tag and the offered
one, fetched when the window is about to be shown and handed to Sparkle
through standardUserDriverWillShowReleaseNotesText:forUpdate:...
(SPUStandardUserDriverDelegate.h:192-205, called for plain-text notes,
SUTextViewReleaseNotesView.m:337-338). The appcast's notes stay when not.

All Sparkle calls happen on the main thread, which is wx's: Sparkle calls the
delegate and the user driver there, and the threads come back through
wx.CallAfter. No Python exception crosses into Objective-C: every method
Sparkle calls refuses (and logs) instead.
"""

import logging
import os
import signal
import subprocess
import sys
import threading
import time

import objc
import wx
from Foundation import NSAttributedString, NSBundle, NSError, NSObject, NSSet, NSURL

from . import (coord_mac, install_on_quit, provenance, provenance_messages, sparkle_notes, sparkle_policy as policy,
               update_accounts as accounts, updater_mac)

ARCH = updater_mac.ARCH
FRAMEWORK = "Sparkle.framework"
RECHECK_ATTEMPTS = 60             # one a second while Sparkle finishes the aborted cycle
NOT_NOW_RETRY_MS = 5 * 60 * 1000  # pairing or start-up still owns the screen
VERDICT_TTL = 10 * 60             # an offer-time answer older than this is asked again
SLOT_ATTEMPTS = 40                # the update slot, while the other accounts finish quitting
SLOT_WAIT = 0.5
NOTES_WAIT_MS = 5000              # the update window waits this long at most for WinZapp's notes
# Where a download that is not this release's zip is sent instead: https, so
# Sparkle accepts the request (SPUDownloader.m:65-81 refuses anything but
# http and https), and a closed local port, so it fails at once.
REFUSED_DOWNLOAD = "https://127.0.0.1:9/winzapp-refused-update.zip"
UPDATE_NOTIFICATION = "winzapp.sparkle.update"   # notify_mac identifier of the reminder

# Who answers the outstanding reply: exactly one path. Re-entrant, because a
# signal handler (main thread) can land while the main thread holds it.
_lock = threading.RLock()
_state = {"mw": None, "updater": None, "driver": None, "delegate": None,
          "checking": "", "user_waiting": False, "offered": "", "offered_item": None,
          "outstanding": None, "slot": None, "installing": False, "closed_accounts": [],
          "quitting": False, "driver_delegate": None,
          "immediate_focus": False, "user_initiated": False}
_verdicts = {}      # tag -> (monotonic time, (ok, detail)), for the next veto only
_notes = {}         # (tag, locale) -> WinZapp's notes for Sparkle's window
_pending_show = {"token": None}   # the update window waiting for its notes (_with_notes)

_CHOICE_BLOCK = {"callable": {"retval": {"type": b"v"},
                              "arguments": {0: {"type": b"^v"}, 1: {"type": b"q"}}}}


def framework_path():
    return os.path.join(updater_mac._bundle_path(), "Contents", "Frameworks", FRAMEWORK)


def enabled():
    """A release build (updater_mac.enabled()) whose Info.plist configures
    Sparkle and that carries the framework."""
    return (updater_mac.enabled() and policy.configured(updater_mac._info())
            and os.path.isdir(framework_path()))


def _error(code, text):
    return NSError.errorWithDomain_code_userInfo_(
        policy.ERROR_DOMAIN, code, {"NSLocalizedDescription": text})


def _settings():
    return getattr(_state["mw"], "settings", None) or {}


def _repo():
    return updater_mac.releases_repo(updater_mac._info())


def _running_tag():
    return provenance.running_release_tag(updater_mac._info())


def _say(text_of):
    """Speak *text_of*(i18n.t) through WinZapp's speech. The key is written
    as a literal t("...") at each call so tests/test_macos_layer_contract.py
    checks it exists in every locale."""
    mw = _state["mw"]
    try:
        mw.output(text_of(mw.i18n.t), interrupt=True)
    except Exception:
        logging.debug("[sparkle_mac] could not speak", exc_info=True)


def _show_refusal(detail):
    """The update did not go ahead: said and shown the way updater_mac says
    it (MacUpdateProgress._fail)."""
    mw = _state["mw"]
    try:
        i18n = mw.i18n
        message = provenance_messages.user_detail(detail, i18n.t)
        text = f"{i18n.t('error').format(app_name='WinZapp')}\n\n{message}"
        mw.output(text, interrupt=True)
        wx.MessageBox(text, i18n.t("update_available_title"), wx.OK | wx.ICON_ERROR, mw)
    except Exception:
        logging.exception("[sparkle_mac] could not show the refusal")


def _window_ready(mw):
    """UpdateChecker._main_window_ready(): no update window over start-up or
    pairing."""
    ready = getattr(mw, "_ui_ready_event", None)
    if ready is not None and not ready.is_set():
        return False
    may_run = getattr(mw, "wpp_update_may_run_now", None)
    return may_run is None or bool(may_run())


def _holds_claim(mw):
    """Every account is its own process and each loads Sparkle; only the one
    holding this claim (until it quits) runs the scheduled checks, so one
    update is not offered once per account. Fails open like
    UpdateChecker._claim_prompt: a check that cannot be coordinated is worth
    more than one suppressed by a bug in the coordination."""
    gd = getattr(mw, "global_dir", None)
    if not gd:
        return True
    try:
        import update_coord
        return update_coord.try_claim_update_prompt(gd, "sparkle", name=policy.CLAIM_FILE) is not None
    except Exception:
        logging.exception("[sparkle_mac] update claim failed — checking anyway")
        return True


def _other_accounts(mw):
    gd, acc_id = getattr(mw, "global_dir", None), getattr(mw, "account_id", None)
    if not (gd and acc_id):
        return []
    try:
        import node_coord
        # The slot claim's liveness rule: an account that rule calls gone is
        # not waited for (request_quit blocks up to 85 s per account).
        return accounts.other_accounts(
            acc_id, node_coord.live_node_leases(gd, is_alive=coord_mac.lease_alive))
    except Exception:
        logging.exception("[sparkle_mac] enumerating other accounts failed (non-fatal)")
        return []


def _quit_other_accounts(mw, others):
    gd = getattr(mw, "global_dir", None)
    try:
        import ipc
        accounts.quit_accounts(others, lambda other: ipc.request_quit(gd, other))
    except Exception:
        logging.exception("[sparkle_mac] quitting the other accounts failed")


def _claim_update_slot(mw):
    """update_coord's update slot, or None while another account still runs.
    Held, nothing else can start an account process (main.py) until it is
    released (_release_update_slot) or this process ends (a dead owner is
    recovered). Without a global dir there is no other account: a placeholder
    slot."""
    gd = getattr(mw, "global_dir", None)
    if not gd:
        return {}
    import update_coord
    # coord_mac's strict rule: a leaked 0.0 lease, or one whose pid is now
    # some other program, is not an account that is still open.
    return accounts.claim_slot(
        lambda: update_coord.try_begin_update(gd, is_alive=coord_mac.lease_alive),
        SLOT_ATTEMPTS, SLOT_WAIT)


def _release_update_slot():
    token, _state["slot"] = _state["slot"], None
    gd = getattr(_state["mw"], "global_dir", None)
    if not gd:
        return
    try:
        import update_coord
        accounts.release_slot(token, lambda t: update_coord.end_update(gd, t))
    except Exception:
        logging.exception("[sparkle_mac] end_update failed")


def _reopen_accounts(accounts_to_open):
    """Start again, in the background, the accounts closed for an update that
    did not install (the way account_launcher starts an account)."""
    if not accounts_to_open:
        return
    try:
        import account_launcher
        frozen = bool(getattr(sys, "frozen", False))
        accounts.reopen_accounts(
            accounts_to_open,
            lambda account: subprocess.Popen(account_launcher.build_launch_command(
                sys.argv[0], sys.executable, account, frozen,
                startup_source="user", background=True)),
            lambda: _say(lambda t: t("mac_update_reopened_other_accounts")))
    except Exception:
        logging.exception("[sparkle_mac] reopening the other accounts failed")


def _update_abandoned():
    """The update will not install: the slot goes back first, so the accounts
    closed for it can start again, and those that did close are opened again
    (one that never quit is still running). Not while this process is
    quitting: Sparkle ends the cancelled cycle during a quit or a logout, and
    accounts must not start then."""
    _state["installing"] = False
    _release_update_slot()
    closed, _state["closed_accounts"] = _state["closed_accounts"], []
    if _state["quitting"] or not closed:
        return
    _reopen_accounts(accounts.accounts_to_reopen(closed, _other_accounts(_state["mw"])))


# -- an update that installs when the app ends -----------------------------------
# The logic is in install_on_quit.py; these bind it to this module's state.

def _armed_path(mw=None):
    return install_on_quit.armed_path(mw or _state["mw"])


def _record_armed(tag):
    install_on_quit.record_armed(_state["mw"], tag)


def _forget_armed(mw=None):
    install_on_quit.forget_armed(mw or _state["mw"])


def _installer_job():
    return install_on_quit.installer_job(updater_mac._info())


def _installer_running():
    return install_on_quit.installer_running(_installer_job())


def armed_install(mw=None):
    """The tag of an update that installs when the app ends, or ""."""
    return install_on_quit.armed_install(mw or _state["mw"], _running_tag(), _installer_running)


def _end_all_for_install(mw):
    """real_exit() of an account while an update is armed: True when ending
    all the accounts took over this exit (install_on_quit.end_all)."""
    return install_on_quit.end_all(mw, armed_install, _other_accounts,
                                   _installer_job, lambda: sys.argv[0])


# -- WinZapp's notes in Sparkle's window --------------------------------------------

def _locale():
    return getattr(getattr(_state["mw"], "i18n", None), "language", "") or "en-US"


def _make_notes(tag, locale):
    """sparkle_notes.offer_notes() with WinZapp's own download and the
    changelogs this app shipped (updater's, as on Windows). Never raises."""
    try:
        # Aliased: "updater" in this module is Sparkle's SPUUpdater.
        import updater as winzapp_updater
        t = _state["mw"].i18n.t
        return sparkle_notes.offer_notes(_running_tag(), tag, locale, t, winzapp_updater._fetch_text,
                                         winzapp_updater._read_changelog_file)
    except Exception:
        logging.exception("[sparkle_mac] could not make the release notes of %s", tag)
        return ""


def _with_notes(tag, present):
    """Call *present*() once WinZapp's notes for *tag* are ready, or after
    NOTES_WAIT_MS without them (the appcast's notes are shown then, and the
    late ones kept for the next time the window opens)."""
    key = (tag, _locale())
    if key in _notes:
        return present()
    done = []

    def once():
        if not done:
            done.append(True)
            present()

    def work():
        text = _make_notes(tag, key[1])
        wx.CallAfter(_notes_ready, key, text, once)

    wx.CallLater(NOTES_WAIT_MS, once)
    threading.Thread(target=work, daemon=True, name="winzapp-sparkle-notes").start()


def _notes_ready(key, text, present):
    # Nothing is kept when nothing was made (offline, rate limited): the next
    # window asks again rather than showing the appcast's notes for good.
    if text:
        _notes[key] = text
    logging.info("[sparkle_mac] release notes of %s: %s", key[0],
                 "WinZapp's" if text else "the appcast's")
    present()


def _forget_pending_show(why):
    """The update check a window was waiting for its notes ended (the user
    closed Sparkle's "Checking for updates" window, Sparkle aborted): that
    window must not open later for a check Sparkle no longer runs, where
    Install would close the other accounts and claim the update slot with no
    cycle end left to give it back. Its reply is not answered either: Sparkle
    already ended that check."""
    if _pending_show["token"] is not None:
        logging.info("[sparkle_mac] %s: the update window waiting for its notes is not opened", why)
    _pending_show["token"] = None


def release_notes_text(original, item):
    """Sparkle's plain-text notes of *item*, replaced by WinZapp's when they
    were made for it, in the font Sparkle gave its own; None keeps Sparkle's."""
    try:
        tag = policy.item_tag(str(item.versionString() or ""), str(item.displayVersionString() or ""))
        text = _notes.get((tag, _locale())) if tag else ""
        if not text:
            return None
        attributes = original.attributesAtIndex_effectiveRange_(0, None)[0] if original.length() else {}
        return NSAttributedString.alloc().initWithString_attributes_(text, attributes)
    except Exception:
        logging.exception("[sparkle_mac] release notes: keeping the appcast's")
        return None


def _item(item):
    url = item.fileURL()
    deltas = item.deltaUpdates()
    return {"version": str(item.versionString() or ""),
            "display_version": str(item.displayVersionString() or ""),
            "url": str(url.absoluteString()) if url is not None else "",
            "deltas": bool(deltas is not None and len(deltas)),
            "installation_type": str(item.installationType() or "")}


def _item_refusal(fields):
    """The item checks of sparkle_policy.decide() alone (versions name one
    tag, its zip over https, no deltas, an application, newer than running):
    (tag, "") when they pass, (tag, why) otherwise."""
    action, tag, detail = policy.decide(fields, _repo(), ARCH, _running_tag(), (True, "ok"))
    return tag, ("" if action == policy.PROCEED else detail)


def _ask(tag):
    """updater_mac.release_provenance() for *tag*, never raising: (ok, detail)."""
    try:
        raw, detail = updater_mac.release_provenance(provenance.tag_version(tag))
        if raw is not None:
            try:
                commit = provenance.parse_provenance(raw)["source_commit"][:12]
            except Exception:
                commit = "?"        # only the log line: the verdict is release_provenance's
            logging.info("[sparkle_mac] provenance OK: %s is an official tag at commit %s", tag, commit)
        return raw is not None, detail
    except Exception as exc:
        logging.exception("[sparkle_mac] provenance of %s failed", tag)
        return False, f"could not verify commit provenance: {type(exc).__name__}"


def _take(reply):
    """True for exactly one caller per reply: the one that answers it."""
    with _lock:
        if reply is not None and _state["outstanding"] is reply:
            _state["outstanding"] = None
            return True
        return False


def _call(reply, choice):
    try:
        reply(choice)
    except Exception:
        logging.exception("[sparkle_mac] answering Sparkle failed")


# -- 1. before Sparkle shows a release --------------------------------------------

def _pop_verdict(tag):
    return accounts.pop_verdict(_verdicts, tag, time.monotonic(), VERDICT_TTL)


def _check_offer(tag, check):
    """Ask the official repository about *tag* on a thread, then the same kind
    of check again on the main thread."""
    _state["checking"] = tag

    def work():
        verdict = _ask(tag)
        wx.CallAfter(_offer_checked, tag, check, verdict)

    threading.Thread(target=work, daemon=True, name="winzapp-sparkle-provenance").start()


def _offer_checked(tag, check, verdict):
    _state["checking"] = ""
    user = check == policy.CHECK_USER or _state["user_waiting"]
    _state["user_waiting"] = False
    if not verdict[0]:
        logging.error("[sparkle_mac] %s refused: %s", tag, verdict[1])
        if not user:
            # A scheduled check stays silent, as it always has; the next one
            # asks again (offline and rate limits are usually gone by then).
            return
    _verdicts[tag] = (time.monotonic(), verdict)    # a refusal: Sparkle's error window
    _recheck(user)


def _recheck(user, attempt=0):
    updater = _state["updater"]
    if updater is None:
        return
    try:
        if updater.sessionInProgress():
            if attempt < RECHECK_ATTEMPTS:
                wx.CallLater(1000, _recheck, user, attempt + 1)
            return
        if user:
            updater.checkForUpdates()
        else:
            updater.checkForUpdatesInBackground()
    except Exception:
        logging.exception("[sparkle_mac] could not check again")


# -- 3. Install chosen in the update window ---------------------------------------

def on_update_found(item, stage, reply, show, user_initiated=False):
    """SPUUserDriver showUpdateFoundWithAppcastItem:state:reply:. *show* hands
    a reply to Sparkle's standard window, once WinZapp's release notes for it
    are ready (_with_notes). At STAGE_INSTALLING the update was downloaded in
    the background (step 2 of the module docstring) and waits for the app to
    end; the window offers to install it now."""
    try:
        _state["user_initiated"] = bool(user_initiated)
        if stage not in (policy.STAGE_NOT_DOWNLOADED, policy.STAGE_DOWNLOADED,
                         policy.STAGE_INSTALLING):
            # Sparkle's state could not be read: nothing is offered, least of
            # all "install now".
            logging.error("[sparkle_mac] unknown update stage %r: not offering it", stage)
            return _call(reply, policy.CHOICE_DISMISS)
        fields = _item(item)
        tag, why = _item_refusal(fields)
        if why:
            logging.error("[sparkle_mac] not offering %s: %s", tag or "an appcast item", why)
            return _call(reply, policy.CHOICE_DISMISS)
        logging.info("[sparkle_mac] showing %s (appcast item checks pass%s)", tag,
                     ", downloaded" if stage == policy.STAGE_INSTALLING else "")
        _state["offered"], _state["offered_item"] = tag, fields

        token = object()
        _pending_show["token"] = token

        def present():
            if _pending_show["token"] is not token:
                return          # that check ended meanwhile (_forget_pending_show)
            _pending_show["token"] = None
            try:
                show(lambda choice: on_update_choice(choice, reply, stage))
            except Exception:
                logging.exception("[sparkle_mac] update window: refusing")
                _call(reply, policy.CHOICE_DISMISS)

        _with_notes(tag, present)
    except Exception:
        logging.exception("[sparkle_mac] update found: refusing")
        _call(reply, policy.CHOICE_DISMISS)


def on_update_choice(choice, reply, stage=policy.STAGE_NOT_DOWNLOADED):
    """The user answered the update window. Skip and Later go to Sparkle as
    they are (that is the user's choice for this release; Skip of a
    downloaded update also cancels its installer, SPUUIBasedUpdateDriver.m:
    297-298); Install first closes the other accounts and claims the update
    slot."""
    try:
        if choice != policy.CHOICE_INSTALL:
            logging.info("[sparkle_mac] %s: the user chose %s", _state["offered"] or "update",
                         "skip" if choice == policy.CHOICE_SKIP else "later")
            _call(reply, choice)
            if choice == policy.CHOICE_SKIP and stage == policy.STAGE_INSTALLING:
                _forget_armed()
            return
        mw = _state["mw"]
        others = _other_accounts(mw)
        logging.info("[sparkle_mac] Install chosen for %s; closing %d other account(s) first",
                     _state["offered"] or "update", len(others))
        if others:
            _say(lambda t: t("update_closing_other_accounts"))

        _state["closed_accounts"] = list(others)

        def work():
            _quit_other_accounts(mw, others)
            slot = _claim_update_slot(mw)
            wx.CallAfter(_update_slot_claimed, reply, slot, stage)

        threading.Thread(target=work, daemon=True, name="winzapp-sparkle-slot").start()
    except Exception:
        logging.exception("[sparkle_mac] install chosen: refusing")
        _call(reply, policy.CHOICE_DISMISS)


def _update_slot_claimed(reply, slot, stage=policy.STAGE_NOT_DOWNLOADED):
    try:
        if slot is None:
            logging.error("[sparkle_mac] another account is still running: not updating")
            _call(reply, policy.CHOICE_DISMISS)
            _update_abandoned()
            mw = _state["mw"]
            return _show_refusal(mw.i18n.t("update_other_accounts_running"))
        # A downloaded update installs and relaunches on this Install; any
        # other is downloaded first, and Ready to Install asks again.
        installing = stage == policy.STAGE_INSTALLING
        _state["slot"], _state["installing"] = slot, installing
        logging.info("[sparkle_mac] update slot claimed (no account can start); Sparkle %s %s",
                     "installs" if installing else "downloads", _state["offered"] or "the update")
        if installing:
            _say(lambda t: t("update_installing"))
        _call(reply, policy.CHOICE_INSTALL)
    except Exception:
        logging.exception("[sparkle_mac] could not go on with the update")
        _call(reply, policy.CHOICE_DISMISS)
        _update_abandoned()


# -- 4. Ready to Install -------------------------------------------------------------

def on_ready_to_install(reply, show):
    """SPUUserDriver showReadyToInstallAndRelaunch: (its window has only
    "Install and Relaunch", SPUStandardUserDriver.m:514)."""
    try:
        with _lock:
            _state["outstanding"] = reply
        logging.info("[sparkle_mac] %s downloaded and prepared: Ready to Install", _state["offered"] or "update")
        show(lambda choice: on_ready_choice(choice, reply))
        announce_ready_to_install()
    except Exception:
        logging.exception("[sparkle_mac] ready to install: cancelling")
        if _take(reply):
            _call(reply, policy.CHOICE_SKIP)
            _update_abandoned()


def on_ready_choice(choice, reply):
    """Install goes ahead only if the release still holds, asked again now."""
    _forget_announcement()
    try:
        tag, fields = _state["offered"], _state["offered_item"]
        if choice != policy.CHOICE_INSTALL or not tag or fields is None:
            if _take(reply):
                logging.info("[sparkle_mac] install of %s not confirmed: cancelling it", tag or "?")
                _call(reply, policy.CHOICE_SKIP)
                _update_abandoned()
            return

        def work():
            verdict = _ask(tag)
            wx.CallAfter(_ready_checked, reply, tag, fields, verdict)

        threading.Thread(target=work, daemon=True, name="winzapp-sparkle-install-check").start()
    except Exception:
        logging.exception("[sparkle_mac] ready choice: cancelling")
        if _take(reply):
            _call(reply, policy.CHOICE_SKIP)
            _update_abandoned()


def _ready_checked(reply, tag, fields, verdict):
    try:
        action, _, detail = policy.decide(fields, _repo(), ARCH, _running_tag(), verdict)
        choice = policy.install_choice(
            policy.CHOICE_INSTALL, verdict if action == policy.PROCEED else (False, detail))
    except Exception:
        logging.exception("[sparkle_mac] install check failed")
        choice, detail = policy.CHOICE_SKIP, "could not check this update"
    if not _take(reply):
        return      # already cancelled by a quit
    if choice == policy.CHOICE_INSTALL:
        logging.info("[sparkle_mac] last check OK: %s still holds (official tag, item checks)", tag)
        _state["installing"] = True
        _say(lambda t: t("update_installing"))
        _call(reply, policy.CHOICE_INSTALL)
        logging.info("[sparkle_mac] Install handed to Sparkle for %s", tag)
        return
    logging.error("[sparkle_mac] not installing %s: %s", tag, detail)
    _call(reply, policy.CHOICE_SKIP)
    _update_abandoned()
    _show_refusal(detail)


# -- quitting ------------------------------------------------------------------------

def on_quit():
    """Every way WinZapp ends. An update that is ready (Ready to Install
    unanswered, or Install confirmed) installs when this process ends, as
    Sparkle does on quit: the update slot then stays held until this process
    is gone (a dead owner is recovered), so no account starts under the
    installer. Otherwise the slot goes back, also when the quit lands during
    a download the user started. Nothing is reopened while quitting
    (_update_abandoned)."""
    try:
        with _lock:
            _state["quitting"] = True
            ready = _state["outstanding"] is not None
        if ready:
            logging.info("[sparkle_mac] quitting at Ready to Install: Sparkle installs %s on quit",
                         _state["offered"] or "the update")
        if not (_state["installing"] or ready):
            _release_update_slot()
    except Exception:
        logging.exception("[sparkle_mac] quit: could not tidy up the update")


def _chain_signals():
    """SIGINT/SIGTERM: main.py's handler ends in os._exit(0), past every quit
    path above, so it is wrapped once Sparkle runs (from the main thread,
    where signal handlers are set and run): on_quit() first, then whatever
    handled the signal before. While an update waits for the app to end, a
    signal does not end the other accounts as real_exit() does
    (_end_all_for_install needs the peers' quit replies, and os._exit comes
    first); neither does a crash or a force quit. If the process Sparkle's
    installer watches ends that way, the bundle is replaced under the
    accounts still running; they keep running the old code until they quit."""
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous = signal.getsignal(sig)

            def handler(signum, frame, previous=previous):
                on_quit()
                if callable(previous):
                    return previous(signum, frame)
                if previous == signal.SIG_IGN:
                    return None
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

            signal.signal(sig, handler)
        except Exception:
            logging.exception("[sparkle_mac] could not wrap signal %s", sig)


def _user_driver_class():
    """WinZapp's subclass of SPUStandardUserDriver (public, not final:
    SPUStandardUserDriver.h:30), made once Sparkle is loaded."""
    if "driver_class" in _state:
        return _state["driver_class"]
    base = objc.lookUpClass("SPUStandardUserDriver")
    objc.registerMetaDataForSelector(
        b"SPUStandardUserDriver", b"showReadyToInstallAndRelaunch:", {"arguments": {2: _CHOICE_BLOCK}})
    objc.registerMetaDataForSelector(
        b"SPUStandardUserDriver", b"showUpdateFoundWithAppcastItem:state:reply:",
        {"arguments": {4: _CHOICE_BLOCK}})

    class WinZappSparkleUserDriver(base):
        def showUpdateFoundWithAppcastItem_state_reply_(self, item, state, reply):
            sup = objc.super(WinZappSparkleUserDriver, self)
            try:
                stage, user = int(state.stage()), bool(state.userInitiated())
            except Exception:
                stage, user = None, False       # unknown: on_update_found refuses it
            on_update_found(item, stage, reply,
                            lambda r: sup.showUpdateFoundWithAppcastItem_state_reply_(item, state, r),
                            user_initiated=user)

        def showReadyToInstallAndRelaunch_(self, reply):
            sup = objc.super(WinZappSparkleUserDriver, self)
            on_ready_to_install(reply, lambda r: sup.showReadyToInstallAndRelaunch_(r))

        def dismissUpdateInstallation(self):
            # Sparkle ends the session's windows here when a check is
            # aborted or cancelled (SPUUIBasedUpdateDriver.m:453-458).
            _forget_pending_show("Sparkle ended the update session")
            objc.super(WinZappSparkleUserDriver, self).dismissUpdateInstallation()

    _state["driver_class"] = WinZappSparkleUserDriver
    return WinZappSparkleUserDriver


# -- the delegate ----------------------------------------------------------------

class WinZappSparkleDelegate(NSObject):
    """SPUUpdaterDelegate. Sparkle holds its delegate weakly; _state keeps
    it alive. Each method refuses when it fails."""

    @objc.typedSelector(b"Z@:@qo^@")
    def updater_mayPerformUpdateCheck_error_(self, updater, check, error):
        """Scheduled checks only: off with WinZapp's updates setting, held
        back while start-up or pairing owns the screen, and run by one account.
        A check the user asked for always runs."""
        try:
            if check != policy.CHECK_BACKGROUND:
                return True, None
            mw = _state["mw"]
            if not policy.updates_enabled(_settings()):
                return False, _error(policy.SILENT_ABORT, "updates are turned off in Settings")
            if not _window_ready(mw):
                wx.CallLater(NOT_NOW_RETRY_MS, _recheck, False)
                return False, _error(policy.SILENT_ABORT, "not now: start-up or pairing in progress")
            if not _holds_claim(mw):
                return False, _error(policy.SILENT_ABORT, "another account checks for updates")
            return True, None
        except Exception:
            logging.exception("[sparkle_mac] may check: refusing")
            return False, _error(policy.SILENT_ABORT, "update check failed")

    @objc.typedSelector(b"@@:@")
    def allowedChannelsForUpdater_(self, updater):
        try:
            return NSSet.setWithArray_(policy.allowed_channels(_settings()))
        except Exception:
            logging.exception("[sparkle_mac] channels: stable only")
            return NSSet.set()

    @objc.typedSelector(b"Z@:@")
    def updaterShouldPromptForPermissionToCheckForUpdates_(self, updater):
        return False            # Settings > General already asks this

    @objc.typedSelector(b"Z@:@@qo^@")
    def updater_shouldProceedWithUpdate_updateCheck_error_(self, updater, item, check, error):
        try:
            fields = _item(item)
            tag = policy.item_tag(fields["version"], fields["display_version"])
            action, tag, detail = policy.decide(fields, _repo(), ARCH, _running_tag(),
                                                _pop_verdict(tag))
            if action == policy.PROCEED:
                logging.info("[sparkle_mac] offering %s (official tag confirmed, appcast item checks pass)", tag)
                _state["offered"] = tag
                return True, None
            if action == policy.REFUSE:
                logging.error("[sparkle_mac] refusing %s: %s", tag or "an appcast item", detail)
                return False, _error(policy.REFUSED,
                                     provenance_messages.user_detail(detail, _state["mw"].i18n.t))
            if not _state["checking"]:
                _check_offer(tag, check)
            elif check == policy.CHECK_USER:
                # Already being asked behind a scheduled check: its end comes
                # back as the check the user asked for.
                _state["user_waiting"] = True
            return False, _error(policy.SILENT_ABORT, "asking the official repository first")
        except Exception:
            logging.exception("[sparkle_mac] proceed: refusing")
            return False, _error(policy.REFUSED, "could not check this update")

    @objc.typedSelector(b"v@:@@@")
    def updater_willDownloadUpdate_withRequest_(self, updater, item, request):
        """A guard: the request must be the zip of the release that was
        checked, over https. Anything else (a delta, another URL) is sent to a
        URL that fails, so nothing is downloaded or installed."""
        try:
            fields = _item(item)
            tag = policy.item_tag(fields["version"], fields["display_version"])
            url = str(request.URL().absoluteString()) if request.URL() is not None else ""
            if tag and tag == _state["offered"] and url == policy.zip_url(_repo(), tag, ARCH):
                logging.info("[sparkle_mac] download started: %s", url)
                return
            logging.error("[sparkle_mac] refusing to download an unexpected update")
        except Exception:
            logging.exception("[sparkle_mac] download: refusing")
        try:
            request.setURL_(NSURL.URLWithString_(REFUSED_DOWNLOAD))
        except Exception:
            logging.exception("[sparkle_mac] could not redirect the refused download")

    @objc.typedSelector(b"v@:@@")
    def updater_didDownloadUpdate_(self, updater, item):
        logging.info("[sparkle_mac] download finished")

    @objc.typedSelector(b"v@:@@@")
    def updater_failedToDownloadUpdate_error_(self, updater, item, error):
        try:
            logging.error("[sparkle_mac] download failed: %s",
                          error.localizedDescription() if error is not None else "no reason given")
        except Exception:
            logging.error("[sparkle_mac] download failed")

    @objc.typedSelector(b"v@:@@")
    def updater_didExtractUpdate_(self, updater, item):
        # Despite its name, Sparkle calls this once its installer tool has
        # been launched and handed the download (SPUInstallerDriver.m:476-486
        # -> SPUCoreBasedUpdateDriver.m:235-252), before that tool extracts and
        # checks it; "Ready to Install" (or, for a background download,
        # updater:willInstallUpdateOnQuit:...) is what follows a successful check.
        logging.info("[sparkle_mac] Sparkle's installer started: extracting and checking the update")

    @objc.typedSelector(b"v@:@@")
    def updater_willInstallUpdate_(self, updater, item):
        logging.info("[sparkle_mac] Sparkle is installing the update")

    @objc.typedSelector(b"Z@:@@@?")
    def updater_willInstallUpdateOnQuit_immediateInstallationBlock_(self, updater, item, block):
        """A background download is ready and installs when the app ends
        (SPUAutomaticUpdateDriver.m:104-128). Recorded for every account
        (_end_all_for_install); NO lets Sparkle end this cycle, so its next
        check shows the update in its window (SPUUpdater.m:903-906) instead of
        WinZapp holding the install block with no window of its own."""
        try:
            fields = _item(item)
            tag = policy.item_tag(fields["version"], fields["display_version"])
            logging.info("[sparkle_mac] %s downloaded in the background: it installs when WinZapp quits",
                         tag or "the update")
            if tag:
                _record_armed(tag)
        except Exception:
            logging.exception("[sparkle_mac] install on quit: could not record it")
        return False

    @objc.typedSelector(b"v@:@q@")
    def updater_didFinishUpdateCycleForUpdateCheck_error_(self, updater, check, error):
        """Every update cycle ends here (SPUUpdaterDelegate.h:475): the moment
        a download that failed or was cancelled, or an install Sparkle gave up
        after Install was confirmed, gives the update slot back and reopens
        the accounts closed for it."""
        try:
            _forget_pending_show("the update cycle ended")
            if error is not None and error.code() not in (policy.SILENT_ABORT, policy.NO_UPDATE):
                logging.warning("[sparkle_mac] update cycle ended: %s", error.localizedDescription())
            if _state["outstanding"] is None and _state["slot"] is not None and (
                    not _state["installing"] or error is not None):
                # The download failed or was cancelled, or Sparkle gave up
                # after Install was confirmed: nothing will install.
                _update_abandoned()
        except Exception:
            logging.exception("[sparkle_mac] cycle end")


# -- the user driver's delegate: a scheduled update is announced -----------------

def announce_scheduled_update(item, downloaded=False):
    """A scheduled check found an update that Sparkle's window will show only
    when WinZapp is next activated (SPUStandardUserDriver.m:263-271, 316-332).
    Spoken, as WinZapp's own updater speaks an update while its window is
    hidden, and posted as a notification VoiceOver reads, in words that say
    how to act on it (neither can answer the update window itself); activating
    it opens Sparkle's window
    (checkForUpdates brings a pending update into focus, SPUUpdater.m:
    checkForUpdates -> showUpdateInFocus). An update already *downloaded*
    in the background is said as such: it installs when WinZapp quits, and
    the window only offers to install it now."""
    try:
        version = str(item.displayVersionString() or "")
        mw = _state["mw"]
        if downloaded:
            text = mw.i18n.t("mac_update_downloaded_reminder").format(new_version=version)
        else:
            text = mw.i18n.t("mac_update_available_reminder").format(new_version=version)
        logging.info("[sparkle_mac] scheduled check found %s: announcing it", version)
        mw.output(text, interrupt=True)
        from . import notify_mac
        notify_mac.post_plain(UPDATE_NOTIFICATION, mw.i18n.t("update_available_title"), text,
                              on_open=lambda: _recheck(True))
    except Exception:
        logging.exception("[sparkle_mac] could not announce the update")


def _app_is_active():
    try:
        from AppKit import NSApp
        return bool(NSApp().isActive())
    except Exception:
        return False


def _show_update_in_focus():
    """Sparkle's own way to bring its current window forward and key
    (SPUUserDriver.h:279, showUpdateInFocus; it activates WinZapp if needed,
    SPUStandardUserDriver.m showUpdateInFocus)."""
    try:
        driver = _state["driver"]
        if driver is not None:
            driver.showUpdateInFocus()
    except Exception:
        logging.exception("[sparkle_mac] could not bring Sparkle's window forward")


def announce_ready_to_install():
    """Sparkle shows "Ready to Install" without making it key (it only asks
    for attention, SPUStandardUserDriver.m showReadyToInstallAndRelaunch:),
    so WinZapp's own window keeps VoiceOver and the user does not learn that
    Sparkle is waiting. It is always said. The window is brought forward and
    made key when that takes focus from no one: WinZapp is already the active
    app, or the user started this check (then they are waiting for it).
    After a scheduled check, with another app in front, focus is not taken
    from it: a notification says it, and activating it brings the window."""
    try:
        mw = _state["mw"]
        version = provenance.tag_version(_state["offered"]) or "?"
        text = mw.i18n.t("mac_update_ready_to_install").format(new_version=version)
        mw.output(text, interrupt=True)
        if _app_is_active() or _state["user_initiated"]:
            logging.info("[sparkle_mac] Ready to Install brought to the front")
            _show_update_in_focus()
            return
        logging.info("[sparkle_mac] Ready to Install announced (WinZapp is in the background)")
        from . import notify_mac
        notify_mac.post_plain(UPDATE_NOTIFICATION, mw.i18n.t("update_available_title"), text,
                              on_open=_show_update_in_focus)
    except Exception:
        logging.exception("[sparkle_mac] could not announce Ready to Install")


def _forget_announcement():
    try:
        from . import notify_mac
        notify_mac.remove_plain(UPDATE_NOTIFICATION)
    except Exception:
        logging.debug("[sparkle_mac] could not remove the reminder", exc_info=True)


class WinZappSparkleUserDriverDelegate(NSObject):
    """SPUStandardUserDriverDelegate: gentle scheduled update reminders
    (SPUStandardUserDriverDelegate.h:94-189). Sparkle keeps showing the
    update itself; WinZapp only makes sure a blind user hears about it, and
    gives the window its own release notes (release_notes_text)."""

    @objc.typedSelector(b"Z@:")
    def supportsGentleScheduledUpdateReminders(self):
        return True

    @objc.typedSelector(b"Z@:@Z")
    def standardUserDriverShouldHandleShowingScheduledUpdate_andInImmediateFocus_(self, update, immediate):
        _state["immediate_focus"] = bool(immediate)
        return True

    @objc.typedSelector(b"v@:Z@@")
    def standardUserDriverWillHandleShowingUpdate_forUpdate_state_(self, handle, update, state):
        try:
            if state.userInitiated():
                return              # the user asked: Sparkle shows it at once, in front
            if _state["immediate_focus"] and _app_is_active():
                return              # shown now, in front of the user
            announce_scheduled_update(update, int(state.stage()) == policy.STAGE_INSTALLING)
        except Exception:
            logging.exception("[sparkle_mac] scheduled update reminder")

    @objc.typedSelector(b"@@:@@@@")
    def standardUserDriverWillShowReleaseNotesText_forUpdate_withBundleDisplayVersion_bundleVersion_(
            self, text, update, display_version, version):
        return release_notes_text(text, update)

    @objc.typedSelector(b"v@:@")
    def standardUserDriverDidReceiveUserAttentionForUpdate_(self, update):
        _forget_announcement()

    @objc.typedSelector(b"v@:")
    def standardUserDriverWillFinishUpdateSession(self):
        _forget_announcement()


# -- WinZapp's entry points -------------------------------------------------------

def _sync_automatic_checks():
    """WinZapp's "check for updates automatically" is Sparkle's scheduled
    check and its background download: applied at start and whenever the
    setting changes. (Sparkle's window has its own "Automatically download
    and install updates" box; what it sets lasts until this runs again.)"""
    updater = _state["updater"]
    if updater is None:
        return
    try:
        auto = policy.updates_enabled(_settings())
        if bool(updater.automaticallyChecksForUpdates()) != auto:
            updater.setAutomaticallyChecksForUpdates_(auto)
        if bool(updater.automaticallyDownloadsUpdates()) != auto:
            updater.setAutomaticallyDownloadsUpdates_(auto)
    except Exception:
        logging.exception("[sparkle_mac] could not apply the automatic check setting")


def _start(mw):
    """Load Sparkle and start its updater once; False when it cannot run.

    SPUUpdater with WinZapp's subclass of Sparkle's standard user driver is
    what SPUStandardUpdaterController wraps, minus the controller's alert when
    the updater fails to start: here a failure is logged and WinZapp's own
    updater takes over instead."""
    if _state["updater"] is not None:
        return True
    try:
        bundle = NSBundle.bundleWithPath_(framework_path())
        if bundle is None or not bundle.load():
            raise RuntimeError("Sparkle.framework did not load")
        objc.registerMetaDataForSelector(
            b"SPUUpdater", b"startUpdater:", {"arguments": {2: {"type_modifier": objc._C_OUT}}})
        host = NSBundle.mainBundle()
        _state["mw"] = mw
        delegate = WinZappSparkleDelegate.alloc().init()
        driver_delegate = WinZappSparkleUserDriverDelegate.alloc().init()
        driver = _user_driver_class().alloc().initWithHostBundle_delegate_(host, driver_delegate)
        updater = objc.lookUpClass("SPUUpdater").alloc() \
            .initWithHostBundle_applicationBundle_userDriver_delegate_(host, host, driver, delegate)
        started, error = updater.startUpdater_(None)
        if not started:
            raise RuntimeError(error.localizedDescription() if error is not None else "no reason given")
    except Exception:
        logging.exception("[sparkle_mac] Sparkle could not start; WinZapp's own updater is used")
        return False
    _state["updater"], _state["driver"], _state["delegate"] = updater, driver, delegate
    _state["driver_delegate"] = driver_delegate
    _sync_automatic_checks()
    armed_install()             # drops the record of an update since installed
    _chain_signals()
    logging.info("[sparkle_mac] Sparkle started (feed %s, alpha %s)",
                 updater.feedURL(), bool(policy.allowed_channels(_settings())))
    return True


def install():
    """Route WinZapp's update entry points to Sparkle (menubar_mac and
    updater_mac have run: the menu item is shown, UpdateChecker points at the
    Mac releases, which stays the fallback), the quit paths through
    on_quit(), and real_exit() through _end_all_for_install()."""
    if not enabled():
        return
    from main_window import session_lifecycle, settings, updates, window_chrome, window_lifecycle
    orig_start = updates.UpdatesMixin._start_update_checker
    orig_force = updates.UpdatesMixin._on_force_update

    def start_update_checker(self, force=False):
        if not _start(self):
            return orig_start(self, force)
        if force:
            _state["updater"].checkForUpdates()

    def on_force_update(self, event):
        if not _start(self):
            return orig_force(self, event)
        _state["updater"].checkForUpdates()

    updates.UpdatesMixin._start_update_checker = start_update_checker
    updates.UpdatesMixin._on_force_update = on_force_update

    # Every way WinZapp ends: real_exit() and another account's IPC quit both
    # tear down through _perform_shutdown(); a Mac quit event (Dock, logout,
    # Sparkle's own) through _on_query_end_session().
    orig_shutdown = window_lifecycle.WindowLifecycleMixin._perform_shutdown
    orig_query = session_lifecycle.SessionLifecycleMixin._on_query_end_session

    def perform_shutdown(self, *args, **kwargs):
        on_quit()
        return orig_shutdown(self, *args, **kwargs)

    def on_query_end_session(self, event):
        on_quit()
        return orig_query(self, event)

    window_lifecycle.WindowLifecycleMixin._perform_shutdown = perform_shutdown
    session_lifecycle.SessionLifecycleMixin._on_query_end_session = on_query_end_session

    # Ending one account while an update waits for the app to end ends them
    # all (_end_all_for_install); real_exit() is where an account chooses to
    # end itself, before any teardown. An account asked to quit by another
    # (ipc) does not pass here: the one asking does.
    orig_real_exit = window_lifecycle.WindowLifecycleMixin.real_exit

    def real_exit(self, *args, **kwargs):
        if _end_all_for_install(self):
            return None
        return orig_real_exit(self, *args, **kwargs)

    window_lifecycle.WindowLifecycleMixin.real_exit = real_exit

    # quit_all_accounts() (Exit, Cmd-Q) already asks every other account to
    # quit before its real_exit(): one that did not answer in time is not
    # asked (and waited for) a second time.
    orig_quit_all = window_chrome.WindowChromeMixin.quit_all_accounts

    def quit_all_accounts(self, *args, **kwargs):
        self._sparkle_ending_all = True
        return orig_quit_all(self, *args, **kwargs)

    window_chrome.WindowChromeMixin.quit_all_accounts = quit_all_accounts

    # The setting changed here (Settings dialog) or in another account.
    orig_choose = settings.SettingsMixin.choose_global_settings
    orig_pulled = settings.SettingsMixin._apply_pulled_global_settings

    def choose_global_settings(self, choices):
        try:
            return orig_choose(self, choices)
        finally:
            wx.CallAfter(_sync_automatic_checks)

    def apply_pulled_global_settings(self, pulled):
        try:
            return orig_pulled(self, pulled)
        finally:
            wx.CallAfter(_sync_automatic_checks)

    settings.SettingsMixin.choose_global_settings = choose_global_settings
    settings.SettingsMixin._apply_pulled_global_settings = apply_pulled_global_settings
    logging.info("[sparkle_mac] updates go through Sparkle")
