"""Self-updates for the macOS app.

WinZapp's UpdateChecker (client/updater.py) is reused as it is — release
selection across the stable and alpha channels, the "update available"
dialog with its changelog, the auto-update and alpha settings. Only where
the Mac differs is replaced:

* Releases come from the repository that publishes the macOS builds
  (Info.plist WinZappMacReleasesRepo, set by the release workflow), and the
  asset is WinZapp-macOS-<arch>.zip.
* Integrity: the zip must match the release's SHA256SUMS.txt, and the app
  inside must be signed by the same Apple Developer team as the running app
  and pass Gatekeeper (notarized). Gabriel's release keys cannot sign builds
  published elsewhere, so the Apple signature is what is trusted here.
* Provenance: the release must also carry WinZapp-macOS-provenance-<arch>.json
  that DECLARES an official tag and commit, and the updater checks that this
  tag exists in gabrielhhaber/WinZapp_Python and points at that commit
  (provenance.py). That is a declaration checked against our repository, not
  proof that the zip was built from the commit; the stronger guarantee needs
  an attestation from a workflow of the official repository, or a maintainer
  signature over the zip hash as on Windows. Any failure to verify, offline
  or rate-limited included, installs nothing.
* The running version is the official tag the app was built from (Info.plist
  WinZappReleaseTag). A build without it (a development build) offers and
  installs no update.
* Installing: a small helper waits for WinZapp to quit, swaps the app bundle
  in place and opens the new one.

Only builds whose Info.plist names that repository (the signed release
builds) check for updates. Without it the updater is off: there is no
default repository to fall back to.
"""

import logging
import os
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading

import wx

from . import provenance, provenance_messages

ARCH = platform.machine()   # arm64 / x86_64


def _bundle_path():
    exe = os.path.realpath(sys.executable)          # .../WinZapp.app/Contents/MacOS/WinZapp
    return os.path.dirname(os.path.dirname(os.path.dirname(exe)))


def _info():
    try:
        with open(os.path.join(_bundle_path(), "Contents", "Info.plist"), "rb") as fh:
            return plistlib.load(fh)
    except Exception:
        return {}


def releases_repo(info):
    """The owner/name the Mac releases come from, or "" when the build
    names none (or something that is not a GitHub repository)."""
    repo = info.get("WinZappMacReleasesRepo")
    return repo if provenance.valid_repo(repo) else ""


def enabled():
    """On only for a release build: it names a releases repository and the
    official tag it was built from (the running version for every "newer"
    comparison). Without the tag nothing could tell a downgrade from an
    update, so it fails closed."""
    info = _info()
    return bool(getattr(sys, "frozen", False) and releases_repo(info)
                and provenance.running_release_tag(info))


def asset_name():
    return f"WinZapp-macOS-{ARCH}.zip"


def find_zip_asset(assets):
    want = asset_name().lower()
    for asset in assets or []:
        if (asset.get("name") or "").lower() == want:
            return asset.get("browser_download_url", "")
    return ""


def team_id(app_path):
    r = subprocess.run(["codesign", "-dv", "--verbose=2", app_path], capture_output=True, text=True)
    for line in (r.stderr or "").splitlines():
        if line.startswith("TeamIdentifier="):
            value = line.split("=", 1)[1].strip()
            return None if value in ("", "not set") else value
    return None


def verify_app(new_app, running_app):
    """(ok, detail): same Developer team as the running app, intact
    signature, and accepted by Gatekeeper (notarized)."""
    expected = team_id(running_app)
    if not expected:
        return False, "the running app has no Developer ID signature to compare against"
    got = team_id(new_app)
    if got != expected:
        return False, f"signed by team {got!r}, expected {expected!r}"
    r = subprocess.run(["codesign", "--verify", "--deep", "--strict", new_app],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, "signature check failed: " + (r.stderr or "").strip()[-300:]
    r = subprocess.run(["spctl", "--assess", "--type", "execute", new_app],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, "Gatekeeper rejected it: " + (r.stderr or "").strip()[-300:]
    return True, "ok"


_SWAP_SCRIPT = """#!/bin/sh
# Wait for WinZapp (pid $1) to quit, put the new app in place, open it.
while kill -0 "$1" 2>/dev/null; do sleep 0.5; done
rm -rf "$3.old"
mv "$3" "$3.old" && mv "$2" "$3" && rm -rf "$3.old"
open "$3"
"""


def _download(url, dest, progress):
    """Size- and time-capped (provenance.download_file), partial file removed
    on failure."""
    provenance.download_file(url, dest, progress)


def release_provenance(version):
    """(raw, detail): the provenance file of release *version* once it is
    verified against the official repository, or (None, why not). Done before
    the download, so an unverifiable release costs nothing. sparkle_mac asks
    the same question before Sparkle may offer a release, and again just
    before Sparkle installs it."""
    running_tag = provenance.running_release_tag(_info())
    if not running_tag:
        return None, "could not verify commit provenance: this build has no release tag"
    tag = "v" + version
    if not provenance.is_release_tag(tag):
        return None, "could not verify commit provenance: not a release tag"
    url = (f"https://github.com/{releases_repo(_info())}/releases/download/"
           f"{tag}/{provenance.provenance_name(ARCH)}")
    try:
        raw = provenance.fetch_release_asset(url)
    except provenance.ProvenanceError as exc:
        return None, exc.detail("verification_file")
    ok, detail = provenance.verify_release(
        raw, tag, running_tag, provenance.fetch_official,
        running_commit=_info().get(provenance.SOURCE_COMMIT_KEY) or "")
    return (raw if ok else None), detail


class MacUpdateProgress(wx.Dialog):
    """Download, verify and install, with its state in plain text and
    spoken through WinZapp's own speech at each stage."""

    def __init__(self, main_window, version, zip_url, sha256sums_url):
        i18n = main_window.i18n
        super().__init__(main_window, title=i18n.t("update_available_title"))
        self._mw, self._version = main_window, version
        self._zip_url, self._sums_url = zip_url, sha256sums_url
        self.installed = False
        sizer = wx.BoxSizer(wx.VERTICAL)
        self._status = wx.StaticText(self, label=version)
        self._gauge = wx.Gauge(self, range=100)
        sizer.Add(self._status, 0, wx.ALL | wx.EXPAND, 10)
        sizer.Add(self._gauge, 0, wx.ALL | wx.EXPAND, 10)
        self.SetSizerAndFit(sizer)
        self._last_spoken = -1
        threading.Thread(target=self._work, daemon=True).start()

    def _say(self, text):
        def ui():
            self._status.SetLabel(text)
            try:
                self._mw.output(text)
            except Exception:
                pass
        wx.CallAfter(ui)

    def _progress(self, pct):
        wx.CallAfter(self._gauge.SetValue, pct)
        if pct // 25 != self._last_spoken:
            self._last_spoken = pct // 25
            self._say(f"{pct}%")

    def _fail(self, detail):
        logging.error("[updater_mac] update to %s failed: %s", self._version, detail)
        i18n = self._mw.i18n

        def ui():
            message = provenance_messages.user_detail(detail, i18n.t)
            wx.MessageBox(f"{i18n.t('error').format(app_name='WinZapp')}\n\n{message}",
                          i18n.t("update_available_title"), wx.OK | wx.ICON_ERROR, self)
            self.EndModal(wx.ID_CANCEL)
        wx.CallAfter(ui)

    def _work(self):
        from updater import _verify_sha256sums
        work = tempfile.mkdtemp(prefix="winzapp-update-")
        handed_over = False        # swap.sh lives in work until it has run
        try:
            zpath = os.path.join(work, asset_name())
            raw, detail = release_provenance(self._version)
            if raw is None:
                return self._fail(detail)
            _download(self._zip_url, zpath, self._progress)
            ok, detail = _verify_sha256sums(zpath, asset_name(), self._sums_url,
                                            stable_keys=(), alpha_keys=())
            if not ok or not self._sums_url:
                return self._fail(detail if not ok else "the release has no SHA256SUMS.txt")
            ok, detail = provenance.check_artifact(raw, asset_name(), zpath)
            if not ok:
                return self._fail(detail)
            subprocess.run(["ditto", "-x", "-k", zpath, work], check=True)
            new_app = os.path.join(work, "WinZapp.app")
            running = _bundle_path()
            ok, detail = verify_app(new_app, running)
            if not ok:
                return self._fail(detail)
            staged = running + ".update"
            if os.path.exists(staged):
                shutil.rmtree(staged)
            subprocess.run(["ditto", new_app, staged], check=True)
            script = os.path.join(work, "swap.sh")
            with open(script, "w") as fh:
                fh.write(_SWAP_SCRIPT)
            os.chmod(script, 0o755)
            subprocess.Popen([script, str(os.getpid()), staged, running],
                             start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            handed_over = True
            self.installed = True
            wx.CallAfter(self.EndModal, wx.ID_OK)
        except Exception as exc:
            self._fail(str(exc))
        finally:
            if not handed_over:
                shutil.rmtree(work, ignore_errors=True)


def _do_install(self, new_version, zip_url, sha256sums_url="", signature_url="", is_alpha=False):
    dlg = MacUpdateProgress(self._mw, new_version, zip_url, sha256sums_url)
    dlg.ShowModal()
    installed = dlg.installed
    dlg.Destroy()
    if installed:
        logging.info("[updater_mac] %s staged — quitting so it can be installed", new_version)
        wx.CallAfter(self._mw.quit_all_accounts)


def install():
    """Point WinZapp's own updater at the Mac releases (menubar_mac leaves
    it on only when enabled() is true)."""
    if not enabled():
        if releases_repo(_info()) and not provenance.running_release_tag(_info()):
            logging.warning("[updater_mac] no valid %s in Info.plist: updates are off "
                            "(a development build cannot tell a downgrade from an update)",
                            provenance.RELEASE_TAG_KEY)
        return
    repo = releases_repo(_info())
    import config
    import updater
    base = f"https://api.github.com/repos/{repo}/releases"
    for mod in (config, updater):
        mod.GITHUB_API_LATEST_RELEASE = base
        mod.GITHUB_API_LATEST_STABLE_RELEASE = f"{base}/latest"
    updater.find_zip_asset = find_zip_asset
    updater._find_signature_asset = lambda assets: ""
    updater.UpdateChecker._do_install = _do_install
