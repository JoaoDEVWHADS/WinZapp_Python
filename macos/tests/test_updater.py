"""macOS self-updates (updater_mac)."""

import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

from winzapp_mac import updater_mac as um  # noqa: E402


def test_picks_this_macs_zip():
    assets = [{"name": "WinZapp.zip", "browser_download_url": "win"},
              {"name": "WinZapp-macOS-arm64.zip", "browser_download_url": "arm"},
              {"name": "WinZapp-macOS-x86_64.zip", "browser_download_url": "intel"}]
    assert um.find_zip_asset(assets) == {"arm64": "arm", "x86_64": "intel"}[um.ARCH]


def test_windows_zip_is_never_taken():
    assert um.find_zip_asset([{"name": "WinZapp.zip", "browser_download_url": "win"}]) == ""


def test_release_selection_uses_the_mac_asset(monkeypatch):
    import updater
    monkeypatch.setattr(updater, "find_zip_asset", um.find_zip_asset)
    releases = [{"tag_name": "v2.0.0.5", "assets": [{"name": "WinZapp.zip"}]},
                {"tag_name": "v2.0.0.4", "assets": [{"name": um.asset_name(),
                                                      "browser_download_url": "u"}]}]
    assert updater.select_release(releases, include_alpha=False)["tag_name"] == "v2.0.0.4"


def _app(tmp, name):
    app = os.path.join(tmp, name, "WinZapp.app", "Contents", "MacOS")
    os.makedirs(app)
    exe = os.path.join(app, "WinZapp")
    subprocess.run(["cp", "/usr/bin/true", exe], check=True)
    return os.path.dirname(os.path.dirname(app))


def test_an_unsigned_or_foreign_app_is_refused(tmp_path):
    running = _app(str(tmp_path), "a")
    new = _app(str(tmp_path), "b")
    subprocess.run(["codesign", "--force", "--sign", "-", new], check=True, capture_output=True)
    ok, detail = um.verify_app(new, running)
    assert not ok


def test_swap_script_replaces_the_app_after_winzapp_exits(tmp_path):
    current = os.path.join(tmp_path, "WinZapp.app")
    staged = current + ".update"
    os.makedirs(current)
    os.makedirs(staged)
    open(os.path.join(staged, "new"), "w").close()
    script = os.path.join(tmp_path, "swap.sh")
    body = um._SWAP_SCRIPT.replace('open "$3"', ':')    # don't launch anything in a test
    open(script, "w").write(body)
    os.chmod(script, 0o755)
    waiter = subprocess.Popen(["sleep", "0.3"])
    swap = subprocess.Popen([script, str(waiter.pid), staged, current])
    waiter.wait()          # reaped, as launchd reaps a quitting WinZapp
    assert swap.wait(timeout=10) == 0
    assert os.path.exists(os.path.join(current, "new"))
    assert not os.path.exists(staged) and not os.path.exists(current + ".old")


def test_no_releases_repository_means_no_updates():
    assert um.releases_repo({}) == ""
    assert um.releases_repo({"WinZappMacReleasesRepo": ""}) == ""
    assert um.releases_repo({"WinZappMacReleasesRepo": "not a repo"}) == ""
    assert um.releases_repo({"WinZappMacReleasesRepo": "owner/name/extra"}) == ""
    assert um.releases_repo({"WinZappMacReleasesRepo": "owner/WinZapp_Python"}) == "owner/WinZapp_Python"


def test_updater_stays_off_without_a_releases_repository(monkeypatch):
    import updater
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(um, "_info", lambda: {"WinZappMacUpdates": True})
    before = (updater.GITHUB_API_LATEST_RELEASE, updater.UpdateChecker._do_install)
    assert not um.enabled()
    um.install()
    assert (updater.GITHUB_API_LATEST_RELEASE, updater.UpdateChecker._do_install) == before


def test_an_unverifiable_release_is_not_installed(monkeypatch):
    """Offline, rate-limited or missing provenance: no raw, a reason, no install."""
    monkeypatch.setattr(um, "_info", lambda: {"WinZappMacReleasesRepo": "rocco-labs/WinZapp_Python", "WinZappReleaseTag": "v2.0.0.1"})

    def offline(url):
        raise um.provenance.ProvenanceError("request failed: URLError")
    monkeypatch.setattr(um.provenance, "fetch_release_asset", offline)
    raw, detail = um.release_provenance("2.0.0.9")
    assert raw is None and "could not verify" in detail


def test_release_asset_failures_keep_their_stage_for_translation(monkeypatch):
    monkeypatch.setattr(um, "_info", lambda: {"WinZappMacReleasesRepo": "rocco-labs/WinZapp_Python",
                                             "WinZappReleaseTag": "v3.0.0.4557alpha"})
    def failed(url):
        raise um.provenance.ProvenanceError("safe diagnostic", code="tls")
    monkeypatch.setattr(um.provenance, "fetch_release_asset", failed)
    raw, detail = um.release_provenance("3.0.0.4573alpha")
    assert raw is None and (detail.code, detail.stage) == ("tls", "verification_file")


def test_legacy_error_dialog_translates_verification_failures_without_a_window(monkeypatch):
    from types import SimpleNamespace
    shown, ended = [], []
    strings = {"error": "{app_name} error", "mac_update_verify_file": "FILE:{reason}",
               "mac_update_verify_tls": "CERTIFICATE"}
    detail = um.provenance.ProvenanceError("safe diagnostic", code="tls").detail("verification_file")
    stub = SimpleNamespace(_version="3.0.0.4573alpha",
                           _mw=SimpleNamespace(i18n=SimpleNamespace(t=lambda k: strings.get(k, k))),
                           EndModal=ended.append)
    monkeypatch.setattr(um.wx, "CallAfter", lambda fn: fn())
    monkeypatch.setattr(um.wx, "MessageBox", lambda text, *a: shown.append(text))
    um.MacUpdateProgress._fail(stub, detail)
    assert shown == ["WinZapp error\n\nFILE:CERTIFICATE"] and ended == [um.wx.ID_CANCEL]


def test_the_provenance_url_is_built_from_the_release_repo_and_tag(monkeypatch):
    seen = []
    monkeypatch.setattr(um, "_info", lambda: {"WinZappMacReleasesRepo": "rocco-labs/WinZapp_Python", "WinZappReleaseTag": "v2.0.0.1"})
    monkeypatch.setattr(um.provenance, "fetch_release_asset",
                        lambda url: seen.append(url) or b"{}")
    raw, _ = um.release_provenance("2.0.0.9")
    assert raw is None      # "{}" is not a provenance
    assert seen == ["https://github.com/rocco-labs/WinZapp_Python/releases/download/v2.0.0.9/"
                    + um.provenance.provenance_name(um.ARCH)]


def test_a_build_without_its_release_tag_offers_no_update(monkeypatch):
    """A development build cannot tell a downgrade from an update: off, and
    even a direct call refuses."""
    import updater
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(um, "_info", lambda: {"WinZappMacReleasesRepo": "rocco-labs/WinZapp_Python"})
    before = updater.UpdateChecker._do_install
    assert not um.enabled()
    um.install()
    assert updater.UpdateChecker._do_install == before
    raw, detail = um.release_provenance("2.0.0.9")
    assert raw is None and "no release tag" in detail
