"""The Sparkle bridge (sparkle_mac) as Sparkle calls it.

Sparkle calls its delegate and its user driver from Objective-C: a BOOL
answer with an NSError written through an out pointer, a block to call
later. A selector signature PyObjC reads differently would turn "refuse this
update" into a crash or, worse, a YES. So the delegate is called here through
objc_msgSend with the C types of Sparkle 2.10.0's headers, not through
Python, and the tests check what Objective-C receives: the veto refuses each
failure, a download request is only ever the release's https zip (never a
file:// URL, which SPUDownloader.m:65-81 would refuse after nothing but
waste), "Ready to Install" asks the official repository again and answers
Skip (cancel) on anything but a fresh yes, quitting leaves a ready update to
install on quit, a background download ending one account ends them all, the
update window carries WinZapp's own release notes, and an exception refuses.
No window is created; the user
driver subclass is exercised against the real framework only when the build
has unpacked it (macos/cache), with its windows replaced.
"""

import ctypes
import json
import os
import signal
import sys
import threading
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import objc  # noqa: E402
from Foundation import (NSAttributedString, NSBundle, NSDictionary, NSMutableURLRequest,  # noqa: E402
                        NSObject, NSString, NSURL)

from winzapp_mac import provenance as P, sparkle_mac as sm, sparkle_policy as S  # noqa: E402

REPO = "rocco-labs/WinZapp_Python"
RUNNING = "v2.1.0.4250alpha"
TAG = "v2.1.0.4258alpha"
INFO = {"WinZappMacReleasesRepo": REPO, "WinZappReleaseTag": RUNNING}
ASSET = S.zip_url(REPO, TAG, sm.ARCH)
FRAMEWORK = os.path.join(ROOT, "macos", "cache", "sparkle-2.10.0", "Sparkle.framework")

_RealThread = threading.Thread      # the fixture makes sm's threads run inline
_RealBarrier = threading.Barrier
_REAL_MAKE_NOTES = sm._make_notes   # the fixture stubs it: no network in tests

_lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
_lib.sel_registerName.restype = ctypes.c_void_p
_lib.sel_registerName.argtypes = [ctypes.c_char_p]
_SEND = ctypes.cast(_lib.objc_msgSend, ctypes.c_void_p).value
_ID = ctypes.c_void_p


def _send(restype, obj, sel, *args):
    """objc_msgSend(obj, sel, *args) with each arg as (ctype, value)."""
    fn = ctypes.CFUNCTYPE(restype, _ID, _ID, *[t for t, _ in args])(_SEND)
    return fn(objc.pyobjc_id(obj), _lib.sel_registerName(sel), *[v for _, v in args])


def _obj(o):
    """A bare pointer: the caller keeps *o* referenced until the call returns."""
    return (_ID, objc.pyobjc_id(o))


class FakeAppcastItem(NSObject):
    """What the bridge reads of SUAppcastItem."""

    def versionString(self):
        return self._version

    def displayVersionString(self):
        return self._display

    def fileURL(self):
        return NSURL.URLWithString_(self._url)

    def deltaUpdates(self):
        return self._deltas

    def installationType(self):
        return self._type


def _item(tag=TAG, url=None, deltas=None, kind="application"):
    item = FakeAppcastItem.alloc().init()
    item._version, item._display = P.bundle_version(tag), P.tag_version(tag)
    item._url = url or S.zip_url(REPO, tag, sm.ARCH)
    item._deltas = NSDictionary.dictionaryWithDictionary_(deltas) if deltas else None
    item._type = kind
    return item


class _Window:
    def __init__(self):
        self.settings = {"general": {}}
        self.spoken = []

        class I18n:
            def t(self, key):
                return {"error": "{app_name} error"}.get(key, key)
        self.i18n = I18n()

    def output(self, text, interrupt=False):
        self.spoken.append(text)


class _Now:
    """threading.Thread that runs its target at start(), in the test."""

    def __init__(self, target, **kw):
        self.target = target

    def start(self):
        self.target()


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(sm.updater_mac, "_info", lambda: dict(INFO))
    monkeypatch.setattr(sm.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(sm.wx, "CallLater", lambda ms, fn, *a, **k: None)
    monkeypatch.setattr(sm.wx, "MessageBox", lambda *a, **k: shown.append(a[0]))
    monkeypatch.setattr(sm.threading, "Thread", _Now)
    shown = []
    monkeypatch.setattr(sm, "_state", {"mw": _Window(), "updater": None, "driver": None,
                                       "delegate": None, "checking": "", "user_waiting": False,
                                       "offered": "", "offered_item": None, "outstanding": None,
                                       "slot": None, "installing": False, "closed_accounts": [],
                                       "quitting": False, "driver_delegate": None,
                                       "immediate_focus": False, "user_initiated": False})
    monkeypatch.setattr(sm, "SLOT_WAIT", 0)
    monkeypatch.setattr(sm, "_verdicts", {})
    # No network: WinZapp's notes are made empty unless a test says otherwise.
    monkeypatch.setattr(sm, "_notes", {})
    monkeypatch.setattr(sm, "_pending_show", {"token": None})
    monkeypatch.setattr(sm, "_make_notes", lambda tag, locale: "")
    sm._state["shown"] = shown
    return sm.WinZappSparkleDelegate.alloc().init()


def _proceed(delegate, item, check):
    err = ctypes.c_void_p(0)
    ok = _send(ctypes.c_bool, delegate, b"updater:shouldProceedWithUpdate:updateCheck:error:",
               _obj(delegate), _obj(item), (ctypes.c_long, check), (ctypes.POINTER(_ID), ctypes.byref(err)))
    return ok, (objc.objc_object(c_void_p=err.value) if err.value else None)


class TestTheVetoBeforeOffering:
    def test_first_sight_aborts_silently_and_asks_the_official_repository(self, bridge, monkeypatch):
        asked = []
        monkeypatch.setattr(sm, "_check_offer", lambda tag, check: asked.append((tag, check)))
        ok, err = _proceed(bridge, _item(), S.CHECK_USER)
        assert ok is False
        # The one code Sparkle's UI aborts on without an error window.
        assert err.code() == S.SILENT_ABORT and err.domain() == "SUSparkleErrorDomain"
        assert asked == [(TAG, S.CHECK_USER)]

    def test_a_confirmed_release_goes_through_once(self, bridge):
        sm._verdicts[TAG] = (sm.time.monotonic(), (True, "ok"))
        assert _proceed(bridge, _item(), S.CHECK_BACKGROUND) == (True, None)
        assert TAG not in sm._verdicts and sm._state["offered"] == TAG

    def test_a_refusal_reaches_sparkle_with_its_reason(self, bridge):
        sm._verdicts[TAG] = (sm.time.monotonic(), (False, "could not verify commit provenance: no such tag"))
        ok, err = _proceed(bridge, _item(), S.CHECK_USER)
        assert ok is False and err.code() == S.REFUSED
        assert "no such tag" in err.localizedDescription()

    def test_network_refusals_are_translated_before_crossing_the_objc_boundary(self, bridge, monkeypatch):
        strings = {"mac_update_verify_tag": "TAG:{reason}", "mac_update_verify_tls": "CERTIFICATE"}
        monkeypatch.setattr(sm._state["mw"].i18n, "t", lambda key: strings.get(key, key))
        detail = P.ProvenanceError("safe diagnostic", code="tls").detail("official_tag")
        sm._verdicts[TAG] = (sm.time.monotonic(), (False, detail))
        ok, error = _proceed(bridge, _item(), S.CHECK_USER)
        assert not ok and error.code() == S.REFUSED
        assert error.localizedDescription() == "TAG:CERTIFICATE"

    def test_refusal_is_shown_and_spoken_in_the_selected_language(self, bridge, monkeypatch):
        strings = {"error": "{app_name} error", "mac_update_verify_tag": "TAG:{reason}",
                   "mac_update_verify_tls": "CERTIFICATE"}
        monkeypatch.setattr(sm._state["mw"].i18n, "t", lambda key: strings.get(key, key))
        detail = P.ProvenanceError("safe diagnostic", code="tls").detail("official_tag")
        sm._show_refusal(detail)
        assert sm._state["shown"] == ["WinZapp error\n\nTAG:CERTIFICATE"]
        assert sm._state["mw"].spoken == sm._state["shown"]

    @pytest.mark.parametrize("item", [
        lambda: _item(url="https://evil.example/WinZapp-macOS-arm64.zip"),
        lambda: _item(url=ASSET.replace("https://", "http://")),
        lambda: _item(deltas={"2.1.0.42501": "x"}),
        lambda: _item(kind="package"),
    ])
    def test_anything_but_the_releases_full_zip_is_refused_without_asking(self, bridge, monkeypatch, item):
        monkeypatch.setattr(sm, "_check_offer", lambda *a: pytest.fail("asked about a foreign item"))
        sm._verdicts[TAG] = (sm.time.monotonic(), (True, "ok"))
        ok, err = _proceed(bridge, item(), S.CHECK_USER)
        assert ok is False and err.code() == S.REFUSED

    def test_an_old_answer_is_asked_again(self, bridge, monkeypatch):
        asked = []
        monkeypatch.setattr(sm, "_check_offer", lambda tag, check: asked.append(tag))
        sm._verdicts[TAG] = (sm.time.monotonic() - sm.VERDICT_TTL - 1, (True, "ok"))
        ok, err = _proceed(bridge, _item(), S.CHECK_USER)
        assert ok is False and err.code() == S.SILENT_ABORT and asked == [TAG]

    def test_an_exception_refuses(self, bridge, monkeypatch):
        def boom(*a):
            raise RuntimeError("bug")
        monkeypatch.setattr(sm.policy, "decide", boom)
        ok, err = _proceed(bridge, _item(), S.CHECK_USER)
        assert ok is False and err.code() == S.REFUSED

    def test_the_question_is_release_provenance_and_its_answer_comes_back_as_the_same_check(
            self, bridge, monkeypatch):
        seen, rechecks = [], []
        monkeypatch.setattr(sm.updater_mac, "release_provenance",
                            lambda version: seen.append(version) or (b"raw", "ok"))
        monkeypatch.setattr(sm, "_recheck", lambda user, attempt=0: rechecks.append(user))
        sm._check_offer(TAG, S.CHECK_BACKGROUND)
        assert seen == ["2.1.0.4258alpha"]
        assert sm._verdicts[TAG][1] == (True, "ok") and rechecks == [False]

    def test_a_refusal_the_user_asked_for_is_shown_one_a_schedule_found_is_not(self, bridge, monkeypatch):
        rechecks = []
        monkeypatch.setattr(sm.updater_mac, "release_provenance", lambda v: (None, "offline"))
        monkeypatch.setattr(sm, "_recheck", lambda user, attempt=0: rechecks.append(user))
        sm._check_offer(TAG, S.CHECK_BACKGROUND)
        assert sm._verdicts == {} and rechecks == []
        sm._check_offer(TAG, S.CHECK_USER)
        assert sm._verdicts[TAG][1] == (False, "offline") and rechecks == [True]


class TestTheDownloadRequest:
    def _download(self, delegate, item, url):
        request = NSMutableURLRequest.requestWithURL_(NSURL.URLWithString_(url))
        _send(None, delegate, b"updater:willDownloadUpdate:withRequest:",
              _obj(delegate), _obj(item), _obj(request))
        return str(request.URL().absoluteString())

    def test_the_offered_release_is_downloaded_from_its_https_asset(self, bridge):
        """What Sparkle fetches is the published asset itself, over https:
        never a file:// URL (SPUDownloader.m:65-81 refuses those)."""
        sm._state["offered"] = TAG
        got = self._download(bridge, _item(), ASSET)
        assert got == ASSET and got.startswith("https://")

    @pytest.mark.parametrize("case", ["not offered", "other url", "delta"])
    def test_anything_else_is_sent_where_it_fails(self, bridge, case):
        if case != "not offered":
            sm._state["offered"] = TAG
        url = {"other url": "https://evil.example/x.zip", "delta": ASSET + ".delta"}.get(case, ASSET)
        got = self._download(bridge, _item(), url)
        assert got == sm.REFUSED_DOWNLOAD and got.startswith("https://")

    def test_an_exception_refuses_the_download(self, bridge, monkeypatch):
        sm._state["offered"] = TAG
        monkeypatch.setattr(sm, "_item", lambda item: 1 / 0)
        assert self._download(bridge, _item(), ASSET) == sm.REFUSED_DOWNLOAD


class _Accounts:
    """Two account processes, as update_coord sees them, with its real
    liveness (no stub): this one (the test process) and acc2, a real second
    process of this interpreter, the way a second account is a second process
    of the app, which ends when it is asked to quit."""

    def __init__(self, monkeypatch, tmp_path, quits=True):
        pytest.importorskip("psutil")
        import subprocess
        import update_coord
        from winzapp_mac import coord_mac
        monkeypatch.setattr(update_coord, "_default_proc_matches_us", coord_mac.matches_us)
        self.uc, self.gd = update_coord, str(tmp_path)
        self.other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        time.sleep(0.2)
        update_coord.try_create_runtime_lease(self.gd)
        update_coord.try_create_runtime_lease(self.gd, pid=self.other.pid)
        self.quit_requests = []

        def request_quit(gd, account):
            self.quit_requests.append(account)
            if quits:
                self.other.kill()
                self.other.wait()
        import ipc
        monkeypatch.setattr(ipc, "request_quit", request_quit)
        monkeypatch.setattr(sm, "_other_accounts",
                            lambda mw: ["acc2"] if self.other.poll() is None else [])
        monkeypatch.setattr(sm, "SLOT_ATTEMPTS", 3)
        mw = sm._state["mw"]
        mw.global_dir, mw.account_id = self.gd, "acc1"

    def close(self):
        if self.other.poll() is None:
            self.other.kill()
            self.other.wait()

    def a_new_account_may_start(self):
        """main.py's start-up gate for a new account process."""
        return not self.uc.is_update_in_progress(self.gd)


@pytest.fixture
def accounts(monkeypatch, tmp_path):
    made = []

    def make(quits=True):
        made.append(_Accounts(monkeypatch, tmp_path, quits))
        return made[-1]
    yield make
    for a in made:
        a.close()


def _found(item=None):
    replies, shown = [], []
    sm.on_update_found(item or _item(), S.STAGE_NOT_DOWNLOADED, replies.append, shown.append)
    return replies, shown


class TestInstallChosenInTheUpdateWindow:
    def test_the_other_accounts_quit_and_none_can_start_before_sparkle_downloads(
            self, bridge, accounts):
        accounts = accounts()
        assert accounts.a_new_account_may_start()
        replies, shown = _found()
        assert replies == [] and len(shown) == 1         # the window got a wrapped reply
        shown[0](S.CHOICE_INSTALL)
        assert accounts.quit_requests == ["acc2"]
        assert replies == [S.CHOICE_INSTALL]              # only now does Sparkle download
        assert not accounts.a_new_account_may_start()     # held until the update is over
        assert "update_closing_other_accounts" in sm._state["mw"].spoken

    def test_an_account_that_will_not_quit_means_no_download(self, bridge, accounts):
        accounts = accounts(quits=False)
        replies, shown = _found()
        shown[0](S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_DISMISS]              # aborts, nothing downloaded
        assert accounts.a_new_account_may_start() and sm._state["slot"] is None
        assert "update_other_accounts_running" in sm._state["shown"][0]

    def test_a_failed_slot_never_spawns_an_account_that_did_not_quit(self, bridge, accounts, monkeypatch):
        accounts = accounts(quits=False)                 # a real process: spawn it first
        spawned = []
        monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
        replies, shown = _found()
        shown[0](S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_DISMISS] and spawned == []

    @pytest.mark.parametrize("choice", [S.CHOICE_SKIP, S.CHOICE_DISMISS])
    def test_skip_and_later_are_the_users_choice_and_quit_no_one(self, bridge, accounts, choice):
        accounts = accounts()
        replies, shown = _found()
        shown[0](choice)
        assert replies == [choice] and accounts.quit_requests == []

    @pytest.mark.parametrize("item", [
        lambda: _item(url="https://evil.example/WinZapp-macOS-arm64.zip"),
        lambda: _item(deltas={"2.1.0.42501": "x"}), lambda: _item(kind="package"),
        lambda: _item(tag="v2.1.0.4249alpha"),
    ])
    def test_a_resumed_item_is_checked_again_and_refused_without_a_window(self, bridge, item):
        """A resumed update skipped the veto (SPUBasicUpdateDriver.m:150)."""
        replies, shown = _found(item())
        assert replies == [S.CHOICE_DISMISS] and shown == []

    def test_an_update_downloaded_in_the_background_is_offered_to_install_now(self, bridge, monkeypatch):
        """Sparkle's next check after a background download shows it as
        downloaded (SPUUIBasedUpdateDriver.m:236-237); Install there installs
        and relaunches at once, after the other accounts quit."""
        monkeypatch.setattr(sm, "_other_accounts", lambda mw: [])
        monkeypatch.setattr(sm, "_claim_update_slot", lambda mw: {"owner_token": "t"})
        replies, shown = [], []
        sm.on_update_found(_item(), S.STAGE_INSTALLING, replies.append, shown.append)
        assert replies == [] and len(shown) == 1
        shown[0](S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_INSTALL]
        # installing: the slot stays held through the quit Sparkle sends next
        assert sm._state["installing"] is True and sm._state["mw"].spoken[-1] == "update_installing"

    def test_skipping_a_downloaded_update_forgets_it(self, bridge, tmp_path):
        """Skip there cancels its installer (SPUUIBasedUpdateDriver.m:297-298):
        no account must end the others for it any more."""
        sm._state["mw"].global_dir = str(tmp_path)
        sm._record_armed(TAG)
        replies, shown = [], []
        sm.on_update_found(_item(), S.STAGE_INSTALLING, replies.append, shown.append)
        shown[0](S.CHOICE_SKIP)
        assert replies == [S.CHOICE_SKIP]
        assert not (tmp_path / sm.accounts.ARMED_FILE).exists()

    def test_later_on_a_downloaded_update_keeps_it_for_the_quit(self, bridge, tmp_path):
        sm._state["mw"].global_dir = str(tmp_path)
        sm._record_armed(TAG)
        replies, shown = [], []
        sm.on_update_found(_item(), S.STAGE_INSTALLING, replies.append, shown.append)
        shown[0](S.CHOICE_DISMISS)
        assert replies == [S.CHOICE_DISMISS] and (tmp_path / sm.accounts.ARMED_FILE).exists()

    def test_a_state_sparkle_could_not_give_is_refused_not_offered_to_install_now(self, bridge):
        replies, shown = [], []
        sm.on_update_found(_item(), None, replies.append, shown.append)
        assert replies == [S.CHOICE_DISMISS] and shown == []

    def test_a_window_that_cannot_be_shown_refuses(self, bridge):
        replies = []

        def broken(reply):
            raise RuntimeError("no window")
        sm.on_update_found(_item(), S.STAGE_NOT_DOWNLOADED, replies.append, broken)
        assert replies == [S.CHOICE_DISMISS]


class TestReadyToInstall:
    """The last answer before Sparkle installs."""

    def _ready(self, monkeypatch, verdict, item=None):
        monkeypatch.setattr(sm.updater_mac, "release_provenance",
                            lambda version: (b"raw" if verdict[0] else None, verdict[1]))
        sm._state["offered"] = TAG
        sm._state["offered_item"] = sm._item(item or _item())
        sm._state["slot"] = {"owner_token": "t"}
        released = []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: released.append(True))
        replies, shown = [], []
        sm.on_ready_to_install(replies.append, shown.append)
        return replies, shown[0], released

    def test_a_fresh_yes_installs_and_only_then_says_installing(self, bridge, monkeypatch):
        replies, user, released = self._ready(monkeypatch, (True, "ok"))
        assert "update_installing" not in sm._state["mw"].spoken
        user(S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_INSTALL] and released == []
        assert sm._state["mw"].spoken[-1] == "update_installing" and sm._state["installing"]

    @pytest.mark.parametrize("verdict", [
        (False, "could not verify commit provenance: the official repository has no such tag"),
        (False, "could not verify commit provenance: GitHub unreachable or rate-limited, try again later"),
    ])
    def test_a_withdrawn_tag_or_unreachable_github_cancels(self, bridge, monkeypatch, verdict):
        replies, user, released = self._ready(monkeypatch, verdict)
        user(S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_SKIP] and released == [True]
        assert verdict[1] in sm._state["shown"][0]

    def test_the_item_is_checked_again_too(self, bridge, monkeypatch):
        replies, user, released = self._ready(monkeypatch, (True, "ok"), item=_item(kind="package"))
        user(S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_SKIP]

    def test_a_crash_in_the_check_cancels(self, bridge, monkeypatch):
        replies, user, released = self._ready(monkeypatch, (True, "ok"))
        monkeypatch.setattr(sm.policy, "decide", lambda *a: 1 / 0)
        user(S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_SKIP]

    @pytest.mark.parametrize("choice", [S.CHOICE_DISMISS, S.CHOICE_SKIP])
    def test_anything_but_install_cancels(self, bridge, monkeypatch, choice):
        replies, user, released = self._ready(monkeypatch, (True, "ok"))
        user(choice)
        assert replies == [S.CHOICE_SKIP] and released == [True]

    def test_an_install_of_a_release_never_offered_here_cancels(self, bridge):
        replies, shown = [], []
        sm.on_ready_to_install(replies.append, shown.append)
        shown[0](S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_SKIP]

    def test_a_window_that_cannot_be_shown_cancels(self, bridge):
        replies = []

        def broken(reply):
            raise RuntimeError("no window")
        sm.on_ready_to_install(replies.append, broken)
        assert replies == [S.CHOICE_SKIP]

    def test_two_answers_race_and_sparkle_gets_exactly_one(self, bridge, monkeypatch):
        """A cancel and the check's end answer the same reply from two
        threads: the lock lets one through."""
        replies, user, released = self._ready(monkeypatch, (True, "ok"))
        reply = sm._state["outstanding"]
        barrier = _RealBarrier(2, timeout=5)

        def quit_now():
            barrier.wait()
            sm.on_ready_choice(S.CHOICE_SKIP, reply)

        def check_ends():
            barrier.wait()
            sm._ready_checked(reply, TAG, sm._state["offered_item"], (True, "ok"))
        threads = [_RealThread(target=f) for f in (quit_now, check_ends)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        assert len(replies) == 1


class TestReadyToInstallIsHeard:
    """Sparkle shows "Ready to Install" without making it key, so WinZapp's
    window kept VoiceOver: it is said, and brought forward when that takes
    focus from no one."""

    @pytest.fixture
    def ready(self, bridge, monkeypatch):
        from winzapp_mac import notify_mac
        posted, focused = [], []
        monkeypatch.setattr(notify_mac, "post_plain",
                            lambda ident, title, body, on_open=None: posted.append((ident, title, body, on_open)))

        class Driver:
            def showUpdateInFocus(self):
                focused.append(True)
        sm._state["driver"] = Driver()
        sm._state["offered"] = TAG
        sm._state["mw"].i18n.t = lambda key: {"mac_update_ready_to_install": "ready {new_version}"}.get(key, key)
        return posted, focused

    def _reach_ready(self, monkeypatch, active, user):
        monkeypatch.setattr(sm, "_app_is_active", lambda: active)
        sm._state["user_initiated"] = user
        sm.on_ready_to_install(lambda c: None, lambda r: None)

    @pytest.mark.parametrize("active,user", [(True, False), (True, True), (False, True)])
    def test_brought_forward_when_that_takes_focus_from_no_one(self, ready, monkeypatch, active, user):
        posted, focused = ready
        self._reach_ready(monkeypatch, active, user)
        assert sm._state["mw"].spoken == ["ready 2.1.0.4258alpha"]
        assert focused == [True] and posted == []

    def test_after_a_scheduled_check_in_the_background_it_is_announced_not_focused(self, ready, monkeypatch):
        posted, focused = ready
        self._reach_ready(monkeypatch, active=False, user=False)
        assert sm._state["mw"].spoken == ["ready 2.1.0.4258alpha"] and focused == []
        ident, title, body, on_open = posted[0]
        assert (ident, title, body) == (sm.UPDATE_NOTIFICATION, "update_available_title", "ready 2.1.0.4258alpha")
        on_open()
        assert focused == [True]

    def test_the_check_kind_comes_from_the_update_window(self, bridge):
        sm.on_update_found(_item(), S.STAGE_NOT_DOWNLOADED, lambda c: None, lambda r: None,
                           user_initiated=True)
        assert sm._state["user_initiated"] is True
        sm.on_update_found(_item(), S.STAGE_NOT_DOWNLOADED, lambda c: None, lambda r: None)
        assert sm._state["user_initiated"] is False


class TestQuitting:
    def test_quitting_at_ready_to_install_leaves_the_install_to_sparkle(self, bridge, monkeypatch, caplog):
        """Sparkle installs a prepared update when the app ends
        (AppInstaller.m:731-744): nothing is answered, and the slot stays
        held until this process is gone, so no account starts under it."""
        import logging as _logging
        caplog.set_level(_logging.INFO)
        released, replies = [], []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: released.append(True))
        sm._state["slot"], sm._state["offered"] = {"owner_token": "t"}, TAG
        sm.on_ready_to_install(replies.append, lambda r: None)
        sm.on_quit()
        assert replies == [] and released == [] and sm._state["outstanding"] is not None
        assert "Sparkle installs v2.1.0.4258alpha on quit" in caplog.text

    def test_quitting_at_ready_to_install_reopens_nothing(self, bridge, monkeypatch):
        """The cycle Sparkle ends during the quit must not start the closed
        accounts again, nor speak, during a shutdown."""
        spawned = []
        monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
        sm._state["closed_accounts"] = ["acc2"]
        sm._state["slot"] = {"owner_token": "t"}
        sm._state["offered"] = TAG
        sm._state["outstanding"] = lambda choice: None
        sm.on_quit()                                     # Cmd+Q / logout / SIGTERM
        sm._update_abandoned()
        assert spawned == []
        assert "mac_update_reopened_other_accounts" not in sm._state["mw"].spoken

    def test_the_cycle_end_gives_an_unused_slot_back(self, bridge, monkeypatch):
        released = []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: released.append(True))
        sm._state["slot"] = {"owner_token": "t"}
        _send(None, bridge, b"updater:didFinishUpdateCycleForUpdateCheck:error:",
              _obj(bridge), (ctypes.c_long, 0), (_ID, None))
        assert released == [True]
        released.clear()
        sm._state["installing"] = True                   # Install confirmed: held until we exit
        _send(None, bridge, b"updater:didFinishUpdateCycleForUpdateCheck:error:",
              _obj(bridge), (ctypes.c_long, 0), (_ID, None))
        assert released == []

    def test_every_quit_path_goes_through_on_quit_first(self, bridge, monkeypatch):
        from main_window import session_lifecycle, settings, updates, window_chrome, window_lifecycle
        for owner, name in ((updates.UpdatesMixin, "_start_update_checker"),
                            (updates.UpdatesMixin, "_on_force_update"),
                            (window_lifecycle.WindowLifecycleMixin, "_perform_shutdown"),
                            (window_lifecycle.WindowLifecycleMixin, "real_exit"),
                            (window_chrome.WindowChromeMixin, "quit_all_accounts"),
                            (session_lifecycle.SessionLifecycleMixin, "_on_query_end_session"),
                            (settings.SettingsMixin, "choose_global_settings"),
                            (settings.SettingsMixin, "_apply_pulled_global_settings")):
            monkeypatch.setattr(owner, name, getattr(owner, name))      # restored after the test
        monkeypatch.setattr(window_chrome.WindowChromeMixin, "quit_all_accounts",
                            lambda self: order.append("quit all"))
        order = []
        monkeypatch.setattr(window_lifecycle.WindowLifecycleMixin, "_perform_shutdown",
                            lambda self: order.append("teardown") or True)
        monkeypatch.setattr(window_lifecycle.WindowLifecycleMixin, "real_exit",
                            lambda self: order.append("real_exit"))
        monkeypatch.setattr(session_lifecycle.SessionLifecycleMixin, "_on_query_end_session",
                            lambda self, event: order.append("query"))
        monkeypatch.setattr(sm, "enabled", lambda: True)
        monkeypatch.setattr(sm, "on_quit", lambda: order.append("on_quit"))
        ends_all = [False]
        monkeypatch.setattr(sm, "_end_all_for_install",
                            lambda mw: order.append("end all?") or ends_all[0])
        sm.install()
        window_lifecycle.WindowLifecycleMixin._perform_shutdown(object())
        session_lifecycle.SessionLifecycleMixin._on_query_end_session(object(), None)
        window_lifecycle.WindowLifecycleMixin.real_exit(object())
        ends_all[0] = True                               # it took this exit over
        window_lifecycle.WindowLifecycleMixin.real_exit(object())
        assert order == ["on_quit", "teardown", "on_quit", "query",
                         "end all?", "real_exit", "end all?"]
        # Exit / Cmd-Q already asks every account: its real_exit() does not
        # ask (and wait for) one that did not answer a second time.
        account = type("Account", (), {})()
        window_chrome.WindowChromeMixin.quit_all_accounts(account)
        assert order[-1] == "quit all" and account._sparkle_ending_all is True


class _Ending:
    """The account calling real_exit(): what _end_all_for_install uses of it."""

    def __init__(self, gd):
        self.global_dir, self.account_id = gd, "acc1"
        self.spoken, self.quit_all = [], []

        class I18n:
            def t(self, key):
                return key
        self.i18n = I18n()

    def output(self, text, interrupt=False):
        self.spoken.append(text)

    def quit_all_accounts(self):
        self.quit_all.append(True)


class TestAnUpdateDownloadedInTheBackground:
    """Sparkle's automatic driver downloads a release that passed the veto and
    leaves its installer waiting for the app to end; that installer watches
    one account process only (InstallerProgressAppController.m:298)."""

    def _will_install_on_quit(self, delegate, item):
        return _send(ctypes.c_bool, delegate,
                     b"updater:willInstallUpdateOnQuit:immediateInstallationBlock:",
                     _obj(delegate), _obj(item), (_ID, None))

    def test_it_is_recorded_for_every_account_and_sparkle_ends_the_cycle(self, bridge, tmp_path):
        sm._state["mw"].global_dir = str(tmp_path)
        item = _item()
        # NO: Sparkle ends the cycle, its next check shows the update.
        assert self._will_install_on_quit(bridge, item) is False
        record = json.loads((tmp_path / sm.accounts.ARMED_FILE).read_text())
        assert record == {"tag": TAG}

    def test_an_item_that_names_no_tag_is_not_recorded(self, bridge, tmp_path):
        sm._state["mw"].global_dir = str(tmp_path)
        item = _item()
        item._display = "not a version"
        assert self._will_install_on_quit(bridge, item) is False
        assert not (tmp_path / sm.accounts.ARMED_FILE).exists()

    @pytest.mark.parametrize("tag, running, want", [
        (TAG, True, TAG),
        (TAG, None, TAG),               # launchd could not be asked: the record counts
        (TAG, False, ""),               # cancelled or finished
        (RUNNING, True, ""),            # installed: the app runs it now
    ])
    def test_a_record_counts_only_while_it_holds(self, bridge, tmp_path, monkeypatch, tag, running, want):
        sm._state["mw"].global_dir = str(tmp_path)
        monkeypatch.setattr(sm, "_installer_running", lambda: running)
        sm._record_armed(tag)
        assert sm.armed_install() == want
        assert (tmp_path / sm.accounts.ARMED_FILE).exists() is bool(want)

    def test_launchd_is_asked_about_sparkles_installer_job(self, bridge, monkeypatch):
        monkeypatch.setattr(sm.updater_mac, "_info",
                            lambda: dict(INFO, CFBundleIdentifier="com.example.winzapp"))
        asked = []

        class Done:
            returncode, stdout = 0, '{\n\t"PID" = 4242;\n};'
        monkeypatch.setattr(sm.subprocess, "run", lambda cmd, **kw: asked.append(cmd) or Done())
        assert sm._installer_running() is True
        assert asked == [["launchctl", "list", "com.example.winzapp-sparkle-updater"]]
        monkeypatch.setattr(sm.subprocess, "run", lambda cmd, **kw: 1 / 0)
        assert sm._installer_running() is None

    def test_ending_one_account_ends_them_all_and_reopens_the_others(self, bridge, tmp_path, monkeypatch):
        mw = _Ending(str(tmp_path))
        spawned = []
        monkeypatch.setattr(sm, "armed_install", lambda mw=None: TAG)
        monkeypatch.setattr(sm, "_other_accounts", lambda mw: ["acc2", "acc3"])
        monkeypatch.setattr(sm, "_installer_job", lambda: "com.example.winzapp-sparkle-updater")
        monkeypatch.setattr(sm.subprocess, "Popen",
                            lambda cmd, **kw: spawned.append((cmd, kw.get("start_new_session"))))
        assert sm._end_all_for_install(mw) is True
        assert mw.quit_all == [True] and mw.spoken == ["update_closing_other_accounts"]
        (cmd, detached), = spawned
        assert detached is True and cmd[:2] == ["/bin/sh", "-c"]
        assert cmd[-2:] == ["acc2", "acc3"] and "com.example.winzapp-sparkle-updater" in cmd
        assert str(os.getpid()) in cmd
        # quit_all_accounts() comes back to real_exit() once the others are gone
        assert sm._end_all_for_install(mw) is False and len(spawned) == 1

    @pytest.mark.parametrize("armed, others", [("", ["acc2"]), (TAG, [])])
    def test_otherwise_only_this_account_ends(self, bridge, tmp_path, monkeypatch, armed, others):
        mw = _Ending(str(tmp_path))
        monkeypatch.setattr(sm, "armed_install", lambda mw=None: armed)
        monkeypatch.setattr(sm, "_other_accounts", lambda mw: others)
        monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: pytest.fail("spawned"))
        assert sm._end_all_for_install(mw) is False and mw.quit_all == []

    def test_a_failure_lets_this_account_end_as_it_would(self, bridge, tmp_path, monkeypatch):
        monkeypatch.setattr(sm, "armed_install", lambda mw=None: 1 / 0)
        assert sm._end_all_for_install(_Ending(str(tmp_path))) is False


class TestReleaseNotes:
    """WinZapp's own notes in Sparkle's window (sparkle_notes.py)."""

    def test_the_window_opens_with_winzapps_notes_ready(self, bridge, monkeypatch):
        made = []
        monkeypatch.setattr(sm, "_make_notes", lambda tag, locale: made.append((tag, locale)) or "What changed")
        replies, shown = _found()
        assert made == [(TAG, "en-US")] and len(shown) == 1
        assert sm._notes[(TAG, "en-US")] == "What changed"
        _found()                                         # made once per tag and language
        assert len(made) == 1

    def test_notes_that_are_late_do_not_hold_the_window_or_open_it_twice(self, bridge, monkeypatch):
        monkeypatch.setattr(sm, "_make_notes", lambda tag, locale: "late notes")
        later = []
        monkeypatch.setattr(sm.wx, "CallLater", lambda ms, fn, *a: later.append(fn))
        works = []
        monkeypatch.setattr(sm.threading, "Thread",
                            lambda target, **kw: type("T", (), {"start": lambda self: works.append(target)})())
        replies, shown = _found()
        assert shown == []
        later[0]()                                       # NOTES_WAIT_MS passed
        assert len(shown) == 1
        works[0]()                                       # the notes arrive after all
        assert len(shown) == 1 and (TAG, "en-US") in sm._notes

    def test_a_check_that_ended_while_its_notes_were_fetched_opens_no_window(self, bridge, monkeypatch):
        """The user closed "Checking for updates" (or Sparkle aborted) during
        the wait: no window for a dead check, its reply left alone, and so no
        Install that would close the other accounts and hold the slot."""
        later = []
        monkeypatch.setattr(sm.wx, "CallLater", lambda ms, fn, *a: later.append(fn))
        works = []
        monkeypatch.setattr(sm.threading, "Thread",
                            lambda target, **kw: type("T", (), {"start": lambda self: works.append(target)})())
        replies, shown = _found()
        _send(None, bridge, b"updater:didFinishUpdateCycleForUpdateCheck:error:",
              _obj(bridge), (ctypes.c_long, 0), (_ID, None))
        later[0]()
        works[0]()
        assert shown == [] and replies == []

    def test_sparkle_dismissing_the_session_drops_the_waiting_window(self, bridge, monkeypatch):
        monkeypatch.setattr(sm.wx, "CallLater", lambda ms, fn, *a: None)
        works = []
        monkeypatch.setattr(sm.threading, "Thread",
                            lambda target, **kw: type("T", (), {"start": lambda self: works.append(target)})())
        replies, shown = _found()
        sm._forget_pending_show("Sparkle ended the update session")   # dismissUpdateInstallation
        works[0]()
        assert shown == [] and replies == []
        replies, shown = _found()                        # the next check opens its window
        works[1]()
        assert len(shown) == 1

    def test_notes_that_could_not_be_made_are_asked_for_again(self, bridge, monkeypatch):
        made = []
        monkeypatch.setattr(sm, "_make_notes", lambda tag, locale: made.append(tag) or "")
        _found()
        _found()
        assert made == [TAG, TAG] and sm._notes == {}

    def _driver_delegate_says(self, original, item):
        driver_delegate = sm.WinZappSparkleUserDriverDelegate.alloc().init()
        display = NSString.stringWithString_("2.1.0.4250alpha").nsstring()
        version = NSString.stringWithString_("2.1.0.42501").nsstring()
        got = _send(_ID, driver_delegate,
                    b"standardUserDriverWillShowReleaseNotesText:forUpdate:withBundleDisplayVersion:bundleVersion:",
                    _obj(original), _obj(item), _obj(display), _obj(version))
        return objc.objc_object(c_void_p=got) if got else None

    def test_sparkle_gets_winzapps_notes_in_its_own_font(self, bridge):
        from AppKit import NSFont, NSFontAttributeName
        font = NSFont.systemFontOfSize_(13)
        original = NSAttributedString.alloc().initWithString_attributes_(
            "V2.1.0.0 the appcast's", {NSFontAttributeName: font})
        sm._notes[(TAG, "en-US")] = "Release notes:\n\n- Calls."
        item = _item()
        got = self._driver_delegate_says(original, item)
        assert got.string() == "Release notes:\n\n- Calls."
        assert got.attributesAtIndex_effectiveRange_(0, None)[0][NSFontAttributeName] == font

    def test_without_them_the_appcasts_notes_stay(self, bridge):
        original = NSAttributedString.alloc().initWithString_("the appcast's")
        item = _item()
        assert self._driver_delegate_says(original, item) is None
        sm._notes[(TAG, "en-US")] = ""                   # made, but nothing to say
        assert self._driver_delegate_says(original, item) is None

    def test_notes_are_made_from_the_running_tag_and_the_users_language(self, bridge, monkeypatch):
        monkeypatch.setattr(sm, "_make_notes", _REAL_MAKE_NOTES)
        calls = []
        monkeypatch.setattr(sm.sparkle_notes, "offer_notes",
                            lambda running, tag, locale, t, fetch, installed:
                            calls.append((running, tag, locale)) or "x")
        sm._state["mw"].i18n.language = "pl"
        assert sm._make_notes(TAG, sm._locale()) == "x"
        assert calls == [(RUNNING, TAG, "pl")]
        monkeypatch.setattr(sm.sparkle_notes, "offer_notes", lambda *a: 1 / 0)
        assert sm._make_notes(TAG, "pl") == ""


class TestWhenTheUpdateDoesNotInstall:
    """Items closed for an update that then does not install come back."""

    def _closed(self, monkeypatch):
        spawned, order = [], []
        monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: spawned.append(cmd))
        monkeypatch.setattr(sm, "_release_update_slot",
                            lambda: order.append("slot") or sm._state.update(slot=None))
        sm._state["closed_accounts"] = ["acc2", "acc3"]
        sm._state["slot"] = {"owner_token": "t"}
        return spawned, order

    def test_a_failed_download_gives_the_slot_back_and_reopens_the_accounts(self, bridge, monkeypatch):
        spawned, order = self._closed(monkeypatch)
        err = sm._error(2001, "network")                  # SUDownloadError
        _send(None, bridge, b"updater:didFinishUpdateCycleForUpdateCheck:error:",
              _obj(bridge), (ctypes.c_long, 0), _obj(err))
        assert order == ["slot"]
        assert [c[c.index("--account") + 1] for c in spawned] == ["acc2", "acc3"]
        assert all("--background" in c for c in spawned)
        assert "mac_update_reopened_other_accounts" in sm._state["mw"].spoken
        assert sm._state["closed_accounts"] == []

    def test_sparkle_giving_up_after_install_was_confirmed_resets_it(self, bridge, monkeypatch):
        spawned, order = self._closed(monkeypatch)
        sm._state["installing"] = True
        err = sm._error(4005, "installation failed")      # SUInstallationError
        _send(None, bridge, b"updater:didFinishUpdateCycleForUpdateCheck:error:",
              _obj(bridge), (ctypes.c_long, 0), _obj(err))
        assert sm._state["installing"] is False and order == ["slot"] and len(spawned) == 2

    def test_a_refused_last_check_reopens_them_too(self, bridge, monkeypatch):
        spawned, order = self._closed(monkeypatch)
        monkeypatch.setattr(sm.updater_mac, "release_provenance", lambda v: (None, "withdrawn"))
        sm._state["offered"], sm._state["offered_item"] = TAG, sm._item(_item())
        replies, shown = [], []
        sm.on_ready_to_install(replies.append, shown.append)
        shown[0](S.CHOICE_INSTALL)
        assert replies == [S.CHOICE_SKIP] and order == ["slot"] and len(spawned) == 2

    def test_the_slot_goes_back_before_the_accounts_start(self, bridge, monkeypatch):
        """They would exit at start-up while the slot is held (main.py)."""
        order = []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: order.append("slot"))
        monkeypatch.setattr(sm.subprocess, "Popen", lambda cmd, **kw: order.append("spawn"))
        sm._state["closed_accounts"] = ["acc2"]
        sm._update_abandoned()
        assert order == ["slot", "spawn"]


class TestQuitPaths:
    def test_a_quit_during_the_download_gives_the_slot_back(self, bridge, monkeypatch):
        released = []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: released.append(True))
        sm._state["slot"] = {"owner_token": "t"}                       # no Ready reply yet
        sm.on_quit()
        assert released == [True]

    def test_after_install_was_confirmed_the_slot_stays_held(self, bridge, monkeypatch):
        released = []
        monkeypatch.setattr(sm, "_release_update_slot", lambda: released.append(True))
        sm._state["slot"], sm._state["installing"] = {"owner_token": "t"}, True
        sm.on_quit()
        assert released == []

    @pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
    def test_sigint_and_sigterm_cancel_first_then_chain(self, bridge, monkeypatch, sig):
        """main.py's handler ends in os._exit(0), past every quit path."""
        order = []
        saved = {s_: signal.getsignal(s_) for s_ in (signal.SIGINT, signal.SIGTERM)}
        try:
            signal.signal(sig, lambda signum, frame: order.append("main.py handler"))
            monkeypatch.setattr(sm, "on_quit", lambda: order.append("on_quit"))
            sm._chain_signals()
            signal.getsignal(sig)(sig, None)
            assert order == ["on_quit", "main.py handler"]
        finally:
            for s_, handler in saved.items():
                signal.signal(s_, handler)


class FakeUpdateState(NSObject):
    """What the reminder reads of SPUUserUpdateState."""

    def userInitiated(self):
        return self._user

    def stage(self):
        return getattr(self, "_stage", S.STAGE_NOT_DOWNLOADED)


class TestScheduledUpdateReminders:
    """Sparkle's standard window waits for WinZapp to be activated
    (SPUStandardUserDriver.m:263-271, 316-332); a blind user must hear that
    an update is there, as WinZapp's own updater says it."""

    @pytest.fixture
    def reminders(self, bridge, monkeypatch):
        from winzapp_mac import notify_mac
        posted, removed = [], []
        monkeypatch.setattr(notify_mac, "post_plain",
                            lambda ident, title, body, on_open=None: posted.append((ident, title, body, on_open)))
        monkeypatch.setattr(notify_mac, "remove_plain", lambda ident: removed.append(ident))
        sm._state["mw"].i18n.t = lambda key: {"mac_update_available_reminder": "new {new_version}"}.get(key, key)
        return sm.WinZappSparkleUserDriverDelegate.alloc().init(), posted, removed

    def _will_show(self, driver_delegate, user, immediate, stage=S.STAGE_NOT_DOWNLOADED):
        item = _item()          # held: _obj() passes a bare pointer
        _send(ctypes.c_bool, driver_delegate,
              b"standardUserDriverShouldHandleShowingScheduledUpdate:andInImmediateFocus:",
              _obj(item), (ctypes.c_bool, immediate))
        state = FakeUpdateState.alloc().init()
        state._user, state._stage = user, stage
        _send(None, driver_delegate, b"standardUserDriverWillHandleShowingUpdate:forUpdate:state:",
              (ctypes.c_bool, True), _obj(item), _obj(state))

    def test_gentle_reminders_are_declared(self, reminders):
        driver_delegate, _, _ = reminders
        assert _send(ctypes.c_bool, driver_delegate, b"supportsGentleScheduledUpdateReminders") is True
        # and Sparkle keeps showing the update itself
        item = _item()
        assert _send(ctypes.c_bool, driver_delegate,
                     b"standardUserDriverShouldHandleShowingScheduledUpdate:andInImmediateFocus:",
                     _obj(item), (ctypes.c_bool, False)) is True

    def test_a_deferred_scheduled_update_is_spoken_and_notified(self, reminders, monkeypatch):
        driver_delegate, posted, _ = reminders
        rechecks = []
        monkeypatch.setattr(sm, "_recheck", lambda user, attempt=0: rechecks.append(user))
        self._will_show(driver_delegate, user=False, immediate=False)
        assert sm._state["mw"].spoken == ["new 2.1.0.4258alpha"]
        ident, title, body, on_open = posted[0]
        assert (ident, title, body) == (sm.UPDATE_NOTIFICATION, "update_available_title", "new 2.1.0.4258alpha")
        on_open()                               # activating it opens Sparkle's window
        assert rechecks == [True]

    def test_an_update_downloaded_in_the_background_says_it_installs_on_quit(self, reminders):
        driver_delegate, posted, _ = reminders
        sm._state["mw"].i18n.t = lambda key: {
            "mac_update_downloaded_reminder": "downloaded {new_version}"}.get(key, key)
        self._will_show(driver_delegate, user=False, immediate=False, stage=S.STAGE_INSTALLING)
        assert sm._state["mw"].spoken == ["downloaded 2.1.0.4258alpha"]
        assert posted[0][2] == "downloaded 2.1.0.4258alpha"

    def test_a_check_the_user_asked_for_is_not_announced(self, reminders):
        driver_delegate, posted, _ = reminders
        self._will_show(driver_delegate, user=True, immediate=False)
        assert posted == [] and sm._state["mw"].spoken == []

    def test_the_reminder_goes_once_the_user_attends_to_the_update(self, reminders):
        driver_delegate, _, removed = reminders
        item = _item()
        _send(None, driver_delegate, b"standardUserDriverDidReceiveUserAttentionForUpdate:", _obj(item))
        _send(None, driver_delegate, b"standardUserDriverWillFinishUpdateSession")
        assert removed == [sm.UPDATE_NOTIFICATION, sm.UPDATE_NOTIFICATION]


def test_every_successful_step_is_logged(bridge, accounts, monkeypatch, caplog):
    """A run can be read from log.log alone."""
    import logging as _logging
    caplog.set_level(_logging.INFO)
    monkeypatch.setattr(sm.updater_mac, "release_provenance", lambda v: (
        P.build_provenance(TAG, "c" * 40, {"WinZapp-macOS-arm64.zip": "a" * 64}), "ok"))
    assert sm._ask(TAG) == (True, "ok")
    accounts = accounts()
    replies, shown = _found()
    shown[0](S.CHOICE_INSTALL)
    request = NSMutableURLRequest.requestWithURL_(NSURL.URLWithString_(ASSET))
    delegate, item = sm._state["delegate"] or sm.WinZappSparkleDelegate.alloc().init(), _item()
    _send(None, delegate, b"updater:willDownloadUpdate:withRequest:", _obj(delegate), _obj(item), _obj(request))
    _send(None, delegate, b"updater:didDownloadUpdate:", _obj(delegate), _obj(item))
    ready = []
    sm.on_ready_to_install(lambda choice: None, ready.append)
    ready[0](S.CHOICE_INSTALL)
    text = caplog.text
    for line in ("official tag at commit cccccccccccc", "appcast item checks pass", "Install chosen",
                 "other accounts asked to quit", "update slot claimed", "download started",
                 "download finished", "Ready to Install", "last check OK", "Install handed to Sparkle"):
        assert line in text, line


class TestScheduledChecks:
    def _may(self, delegate, check):
        err = ctypes.c_void_p(0)
        ok = _send(ctypes.c_bool, delegate, b"updater:mayPerformUpdateCheck:error:",
                   _obj(delegate), (ctypes.c_long, check), (ctypes.POINTER(_ID), ctypes.byref(err)))
        return ok, err.value

    def test_the_user_can_always_check(self, bridge):
        sm._state["mw"].settings = {"general": {"updates_enabled": False}}
        assert self._may(bridge, S.CHECK_USER) == (True, None)

    def test_off_in_settings_means_no_scheduled_check(self, bridge):
        sm._state["mw"].settings = {"general": {"updates_enabled": False}}
        ok, err = self._may(bridge, S.CHECK_BACKGROUND)
        assert ok is False and err

    def test_one_account_runs_the_scheduled_checks(self, bridge, monkeypatch):
        sm._state["mw"].global_dir = "/nonexistent"
        import update_coord
        monkeypatch.setattr(update_coord, "try_claim_update_prompt", lambda *a, **k: None)
        assert self._may(bridge, S.CHECK_BACKGROUND)[0] is False
        monkeypatch.setattr(update_coord, "try_claim_update_prompt", lambda gd, v, name: {"t": 1}
                            if name == S.CLAIM_FILE else None)
        assert self._may(bridge, S.CHECK_BACKGROUND)[0] is True

    def test_an_exception_refuses_the_check(self, bridge, monkeypatch):
        monkeypatch.setattr(sm, "_settings", lambda: 1 / 0)
        assert self._may(bridge, S.CHECK_BACKGROUND)[0] is False

    def test_the_alpha_setting_is_the_alpha_channel(self, bridge):
        sm._state["mw"].settings = {"general": {"alpha_updates_enabled": True}}
        got = objc.objc_object(c_void_p=_send(_ID, bridge, b"allowedChannelsForUpdater:", _obj(bridge)))
        assert set(got) == {"alpha"}
        sm._state["mw"].settings = {"general": {}}
        got = objc.objc_object(c_void_p=_send(_ID, bridge, b"allowedChannelsForUpdater:", _obj(bridge)))
        assert set(got) == set()

    def test_turning_automatic_checks_on_or_off_applies_at_once(self, bridge, monkeypatch):
        """The one switch: scheduled checks and their background download."""
        class Updater:
            auto = downloads = False

            def automaticallyChecksForUpdates(self):
                return self.auto

            def setAutomaticallyChecksForUpdates_(self, value):
                self.auto = value

            def automaticallyDownloadsUpdates(self):
                return self.downloads

            def setAutomaticallyDownloadsUpdates_(self, value):
                self.downloads = value
        sm._state["updater"] = Updater()
        sm._state["mw"].settings = {"general": {"updates_enabled": True}}
        sm._sync_automatic_checks()
        assert sm._state["updater"].auto is True and sm._state["updater"].downloads is True
        sm._state["mw"].settings = {"general": {"updates_enabled": False}}
        sm._sync_automatic_checks()
        assert sm._state["updater"].auto is False and sm._state["updater"].downloads is False


@pytest.mark.skipif(not os.path.isdir(FRAMEWORK), reason="Sparkle not unpacked (run build_app.py)")
def test_the_user_driver_subclass_receives_and_answers_sparkles_blocks(bridge, monkeypatch):
    """Against Sparkle 2.10.0 itself: the subclass's overrides get Sparkle's
    reply blocks as callables and an answer reaches the block. The standard
    windows are replaced by the test, so nothing is shown."""
    assert NSBundle.bundleWithPath_(FRAMEWORK).load()
    cls = sm._user_driver_class()
    driver = cls.alloc().initWithHostBundle_delegate_(NSBundle.mainBundle(), None)
    got = []

    def answer(reply, show):
        reply(S.CHOICE_SKIP)
    monkeypatch.setattr(sm, "on_ready_to_install", answer)
    # PyObjC turns the callable into an Objective-C block (the metadata
    # _user_driver_class registered), the call is dispatched by the runtime to
    # the Python override, which gets that block back and answers it.
    driver.showReadyToInstallAndRelaunch_(lambda choice: got.append(choice))
    assert got == [S.CHOICE_SKIP]
    monkeypatch.setattr(sm, "on_update_found",
                        lambda item, stage, reply, show, user_initiated=False:
                        got.append((stage, user_initiated)) or reply(S.CHOICE_DISMISS))
    state = objc.lookUpClass("SPUUserUpdateState").alloc()
    if state.respondsToSelector_(b"initWithStage:userInitiated:"):
        state = state.initWithStage_userInitiated_(S.STAGE_INSTALLING, True)
        item = _item()
        driver.showUpdateFoundWithAppcastItem_state_reply_(item, state, lambda c: got.append(c))
        assert got == [S.CHOICE_SKIP, (S.STAGE_INSTALLING, True), S.CHOICE_DISMISS]


@pytest.mark.skipif(not os.path.isdir(FRAMEWORK), reason="Sparkle not unpacked (run build_app.py)")
@pytest.mark.parametrize("protocol, owner, selector", [
    ("SPUUpdaterDelegate", sm.WinZappSparkleDelegate,
     b"updater:willInstallUpdateOnQuit:immediateInstallationBlock:"),
    ("SPUStandardUserDriverDelegate", sm.WinZappSparkleUserDriverDelegate,
     b"standardUserDriverWillShowReleaseNotesText:forUpdate:withBundleDisplayVersion:bundleVersion:"),
])
def test_the_new_delegate_methods_have_sparkles_own_types(protocol, owner, selector):
    """Sparkle calls these with the types its protocols declare; a method
    PyObjC registered with others would read its arguments wrongly. (BOOL is
    "B" in Sparkle's build and "Z" in PyObjC's spelling, the same C type.)"""
    assert NSBundle.bundleWithPath_(FRAMEWORK).load()
    _, want = objc.protocolNamed(protocol).descriptionForInstanceMethod_(selector)
    got = owner.instanceMethodSignatureForSelector_(selector)
    types = [got.methodReturnType()] + [got.getArgumentTypeAtIndex_(i) for i in range(got.numberOfArguments())]
    assert b"".join(types).replace(b"Z", b"B") == want.replace(b"Z", b"B")


@pytest.mark.skipif(not os.path.isdir(FRAMEWORK), reason="Sparkle not unpacked (run build_app.py)")
def test_the_user_driver_subclass_drops_a_waiting_window_when_sparkle_dismisses(bridge):
    """dismissUpdateInstallation reaches the override, then Sparkle's own."""
    assert NSBundle.bundleWithPath_(FRAMEWORK).load()
    try:            # made once per process: the class may exist from another test
        cls = objc.lookUpClass("WinZappSparkleUserDriver")
    except objc.nosuchclass_error:
        cls = sm._user_driver_class()
    driver = cls.alloc().initWithHostBundle_delegate_(NSBundle.mainBundle(), None)
    sm._pending_show["token"] = object()
    driver.dismissUpdateInstallation()
    assert sm._pending_show["token"] is None


def test_off_without_sparkle_keys(monkeypatch):
    """A build without the keys (every build until the release workflow sets
    WINZAPP_SPARKLE_PUBLIC_KEY) keeps updater_mac, untouched."""
    from main_window import updates
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sm.updater_mac, "_info", lambda: dict(INFO))
    before = updates.UpdatesMixin._on_force_update
    assert not sm.enabled()
    sm.install()
    assert updates.UpdatesMixin._on_force_update is before


def test_a_sparkle_that_cannot_start_falls_back_to_winzapps_updater(monkeypatch):
    from main_window import session_lifecycle, settings, updates, window_lifecycle
    from main_window import window_chrome
    for owner, name in ((window_lifecycle.WindowLifecycleMixin, "_perform_shutdown"),
                        (window_lifecycle.WindowLifecycleMixin, "real_exit"),
                        (window_chrome.WindowChromeMixin, "quit_all_accounts"),
                        (session_lifecycle.SessionLifecycleMixin, "_on_query_end_session"),
                        (settings.SettingsMixin, "choose_global_settings"),
                        (settings.SettingsMixin, "_apply_pulled_global_settings")):
        monkeypatch.setattr(owner, name, getattr(owner, name))
    called = []
    monkeypatch.setattr(sm, "enabled", lambda: True)
    monkeypatch.setattr(sm, "_start", lambda mw: False)
    monkeypatch.setattr(updates.UpdatesMixin, "_on_force_update", lambda self, e: called.append("old"))
    monkeypatch.setattr(updates.UpdatesMixin, "_start_update_checker",
                        lambda self, force=False: called.append(("old start", force)))
    sm.install()
    updates.UpdatesMixin._on_force_update(object(), None)
    updates.UpdatesMixin._start_update_checker(object(), True)
    assert called == ["old", ("old start", True)]


def test_other_accounts_use_the_strict_liveness_rule_of_the_slot_claim(monkeypatch):
    """A leaked lease the slot claim calls dead must not make the update wait
    for an account that is no longer running."""
    import node_coord
    from winzapp_mac import coord_mac
    seen = {}

    def live_node_leases(gd, is_alive):
        seen["is_alive"] = is_alive
        return [{"account_id": "acc1"}, {"account_id": "acc2"},
                {"account_id": "acc3", "_corrupt": True}]
    monkeypatch.setattr(node_coord, "live_node_leases", live_node_leases)
    mw = type("MW", (), {"global_dir": "gd", "account_id": "acc1"})()
    assert sm._other_accounts(mw) == ["acc2"]
    assert seen["is_alive"] is coord_mac.lease_alive
