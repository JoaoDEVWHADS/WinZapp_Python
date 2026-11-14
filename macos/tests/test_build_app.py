"""build_app.py's calls to Apple's servers: a failure must say what Apple
answered, a timeout is retried, and a rejected notarization stops the build
with Apple's log instead of an unexplained stapler error. Nothing is signed
or sent to Apple here; subprocess.run is faked.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS build")

import build_app  # noqa: E402

# What notarytool 1.x printed for real submissions (2026-10-01).
ACCEPTED = '{"status":"Accepted","message":"Processing complete","id":"e886e6f2-8b8a-4e58-b54d-0800fe399e79"}\n'
INVALID = '{"status":"Invalid","id":"84a9b45d-6600-4fb8-85bb-ccb44d5f1226","message":"Processing complete"}\n'
TIMED_OUT = 'Error: HTTPError(statusCode: nil, error: Error Domain=NSURLErrorDomain Code=-1001 "The request timed out.")'


class FakeRun:
    """Answers each subprocess.run call with the next (returncode, stdout, stderr)."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(list(cmd))
        code, out, err = self.answers.pop(0) if self.answers else (0, "", "")
        return subprocess.CompletedProcess(cmd, code, out, err)


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(build_app.time, "sleep", lambda s: None)


def test_notary_status_reads_the_submission():
    assert build_app.notary_status(ACCEPTED) == ("e886e6f2-8b8a-4e58-b54d-0800fe399e79", "Accepted")
    assert build_app.notary_status(INVALID)[1] == "Invalid"


def test_notary_status_without_an_answer():
    assert build_app.notary_status("") == (None, None)
    assert build_app.notary_status("not json\n") == (None, None)


def test_a_failed_codesign_prints_apples_message(monkeypatch, capsys, no_wait):
    fake = FakeRun(*[(1, "", "The timestamp service is not available.")] * 3)
    monkeypatch.setattr(build_app.subprocess, "run", fake)
    with pytest.raises(subprocess.CalledProcessError):
        build_app.run_apple(["codesign", "x.node"], quiet=True)
    out = capsys.readouterr().out
    assert out.count("The timestamp service is not available.") == 3
    assert "attempt 3/3 failed" in out
    assert len(fake.calls) == 3


def test_a_timeout_is_retried_and_then_succeeds(monkeypatch, capsys, no_wait):
    fake = FakeRun((1, "", "The timestamp service is not available."), (0, "", ""))
    monkeypatch.setattr(build_app.subprocess, "run", fake)
    assert build_app.run_apple(["codesign", "x.node"], quiet=True).returncode == 0
    assert len(fake.calls) == 2


def test_a_quiet_success_prints_nothing(monkeypatch, capsys):
    monkeypatch.setattr(build_app.subprocess, "run", FakeRun((0, "", "x.node: replacing existing signature")))
    build_app.run_apple(["codesign", "x.node"], quiet=True)
    assert capsys.readouterr().out == ""


@pytest.fixture
def notary_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WINZAPP_NOTARY_KEY", str(tmp_path / "key.p8"))
    monkeypatch.setenv("WINZAPP_NOTARY_KEY_ID", "KEYID")
    monkeypatch.setenv("WINZAPP_NOTARY_ISSUER", "ISSUER")
    monkeypatch.setattr(build_app, "BUILD", str(tmp_path))
    ran = []

    def run(cmd, **kw):
        ran.append(list(cmd))
        if cmd[0] == "ditto":
            open(cmd[-1], "w").close()      # the archive notarize() removes at the end

    monkeypatch.setattr(build_app, "run", run)
    return ran


def test_notarization_retries_when_apple_is_not_reached(monkeypatch, notary_env, no_wait):
    fake = FakeRun((1, "", TIMED_OUT), (0, ACCEPTED, ""))
    monkeypatch.setattr(build_app.subprocess, "run", fake)
    assert build_app.notarize() is True
    assert [c[2] for c in fake.calls] == ["submit", "submit"]
    assert any(c[:3] == ["xcrun", "stapler", "staple"] for c in notary_env)


def test_notarization_gives_up_after_the_last_attempt(monkeypatch, notary_env, no_wait, capsys):
    monkeypatch.setattr(build_app.subprocess, "run", FakeRun(*[(1, "", TIMED_OUT)] * 3))
    with pytest.raises(SystemExit, match="could not be reached"):
        build_app.notarize()
    assert "The request timed out." in capsys.readouterr().out
    assert not any("stapler" in c for c in notary_env)


def test_a_rejected_app_prints_apples_log_and_stops(monkeypatch, notary_env, capsys):
    log = '"message": "The executable does not have the hardened runtime enabled."'
    fake = FakeRun((0, INVALID, ""), (0, log, ""))
    monkeypatch.setattr(build_app.subprocess, "run", fake)
    with pytest.raises(SystemExit, match="Invalid"):
        build_app.notarize()
    assert fake.calls[1][:4] == ["xcrun", "notarytool", "log", "84a9b45d-6600-4fb8-85bb-ccb44d5f1226"]
    assert "hardened runtime" in capsys.readouterr().out
    assert not any("stapler" in c for c in notary_env)


def test_a_release_bundle_is_versioned_by_its_tag():
    """A release is built from the tag's clean checkout, whose version.py is
    the unstamped placeholder: the tag is the version, numbers only (Apple
    specifies integers in CFBundleShortVersionString)."""
    assert build_app.bundle_version(("v2.1.0.4050alpha", "a" * 40)) == "2.1.0.4050"
    assert build_app.bundle_version(("v2.1.0.4055beta", "a" * 40)) == "2.1.0.4055"
    assert build_app.bundle_version(("v2.1.0.4060", "a" * 40)) == "2.1.0.4060"


def test_a_development_bundle_keeps_version_py(monkeypatch):
    monkeypatch.syspath_prepend(build_app.CLIENT)   # restores sys.path, bundle_version's insert included
    from version import __version__
    assert build_app.bundle_version(None) == __version__


# -- Sparkle ---------------------------------------------------------------------

KEY = "Zm9vYmFyYmF6cXV4Zm9vYmFyYmF6cXV4Zm9vYmFyYmE="      # 32 bytes, base64
SOURCE = ("v2.1.0.4258alpha", "a" * 40)


def test_no_sparkle_key_means_no_sparkle_keys(monkeypatch):
    """Without a key the build updates as it always has (updater_mac)."""
    monkeypatch.delenv("WINZAPP_SPARKLE_PUBLIC_KEY", raising=False)
    assert build_app.sparkle_plist(SOURCE) == {}
    assert build_app.sparkle_plist(None) == {}


@pytest.mark.parametrize("key,base,source", [
    (KEY, "https://rocco-labs.github.io/WinZapp_Python", None),     # no release tag
    ("not-a-key", "https://rocco-labs.github.io/WinZapp_Python", SOURCE),
    (KEY, "", SOURCE), (KEY, "http://rocco-labs.github.io/WinZapp_Python", SOURCE),
    (KEY, "https://rocco-labs.github.io/WinZapp_Python/", SOURCE),
])
def test_a_sparkle_build_that_cannot_hold_stops(monkeypatch, key, base, source):
    monkeypatch.setenv("WINZAPP_SPARKLE_PUBLIC_KEY", key)
    monkeypatch.setenv("WINZAPP_SPARKLE_FEED_BASE", base)
    with pytest.raises(SystemExit):
        build_app.sparkle_plist(source)


def test_the_plist_a_sparkle_build_writes_turns_sparkle_on_at_run_time(monkeypatch):
    """build_app and sparkle_mac read the same keys from one place."""
    monkeypatch.setenv("WINZAPP_SPARKLE_PUBLIC_KEY", KEY)
    monkeypatch.setenv("WINZAPP_SPARKLE_FEED_BASE", "https://rocco-labs.github.io/WinZapp_Python")
    keys = build_app.sparkle_plist(SOURCE, arch="arm64")
    assert keys["SUFeedURL"] == "https://rocco-labs.github.io/WinZapp_Python/appcast-arm64.xml"
    assert keys["SURequireSignedFeed"] and keys["SUVerifyUpdateBeforeExtraction"]
    assert keys["SUAllowsAutomaticUpdates"] is True and keys["SUAutomaticallyUpdate"] is True
    # Sparkle's windows in WinZapp's languages, read from language_map.json.
    assert keys["CFBundleLocalizations"][0] == "en"
    assert {"pt-BR", "pt-PT", "es", "pl", "tr", "ro"} <= set(keys["CFBundleLocalizations"])
    policy = build_app.load_sparkle_policy()
    prov = build_app.load_provenance()
    info = dict(keys, WinZappReleaseTag=SOURCE[0], CFBundleVersion=prov.bundle_version(SOURCE[0]))
    assert policy.configured(info)
    assert not policy.configured(dict(info, CFBundleVersion="2.1.0.4258"))


def _fake_sparkle(root):
    """Sparkle.framework's layout, symlinks included."""
    fw = os.path.join(root, "Sparkle.framework")
    b = os.path.join(fw, "Versions", "B")
    for d in ("XPCServices/Installer.xpc/Contents/MacOS", "Updater.app/Contents/MacOS", "Resources"):
        os.makedirs(os.path.join(b, d))
    for f in ("Sparkle", "Autoupdate", "Updater.app/Contents/MacOS/Updater",
              "XPCServices/Installer.xpc/Contents/MacOS/Installer"):
        with open(os.path.join(b, f), "wb") as fh:
            fh.write(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
    os.symlink("B", os.path.join(fw, "Versions", "Current"))
    for name in ("Sparkle", "Autoupdate", "Updater.app", "XPCServices", "Resources"):
        os.symlink(os.path.join("Versions", "Current", name), os.path.join(fw, name))
    return root


def test_sparkle_is_embedded_without_its_xpc_services(monkeypatch, tmp_path):
    app = tmp_path / "WinZapp.app"
    monkeypatch.setattr(build_app, "FRAMEWORKS", str(app / "Contents" / "Frameworks"))
    fw = build_app.embed_sparkle(_fake_sparkle(str(tmp_path / "src")))
    assert os.path.isfile(os.path.join(fw, "Versions", "B", "Sparkle"))
    assert os.path.islink(os.path.join(fw, "Sparkle"))
    assert not os.path.lexists(os.path.join(fw, "XPCServices"))
    assert not os.path.lexists(os.path.join(fw, "Versions", "B", "XPCServices"))


def test_developer_id_signs_sparkle_as_documented_before_the_app(monkeypatch, tmp_path):
    """Sparkle's helpers and the framework are signed as bundles, each with
    the hardened runtime and a timestamp, after everything inside the app and
    before the app; the generic walk never signs a file inside them."""
    app = tmp_path / "WinZapp.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    (macos / "WinZapp").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
    (macos / "lib.dylib").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 12)
    monkeypatch.setattr(build_app, "APP", str(app))
    monkeypatch.setattr(build_app, "BUILD", str(tmp_path))
    monkeypatch.setattr(build_app, "FRAMEWORKS", str(app / "Contents" / "Frameworks"))
    fw = build_app.embed_sparkle(_fake_sparkle(str(tmp_path / "src")))
    signed = []
    monkeypatch.setattr(build_app, "run_apple", lambda cmd, **kw: signed.append(cmd))
    monkeypatch.setattr(build_app, "run", lambda cmd, **kw: signed.append(cmd))
    build_app.sign_developer_id("Developer ID Application: Test (TEAM)")
    targets = [c[-1] for c in signed]
    b = os.path.join(fw, "Versions", "B")
    assert targets == [str(macos / "lib.dylib"), os.path.join(b, "Autoupdate"),
                       os.path.join(b, "Updater.app"), fw, str(app)]
    for cmd in signed:
        assert "--options" in cmd and cmd[cmd.index("--options") + 1] == "runtime"
        assert "--timestamp" in cmd and "--deep" not in cmd


def test_a_build_without_a_working_psutil_stops(monkeypatch):
    """coord_mac needs it; build_app checks it with the build's own Python."""
    monkeypatch.setattr(build_app.subprocess, "run",
                        FakeRun((1, "", "ModuleNotFoundError: No module named 'psutil'")))
    with pytest.raises(SystemExit, match="psutil"):
        build_app.check_psutil()


def test_psutil_for_another_architecture_stops(monkeypatch):
    other = {"arm64": "x86_64", "x86_64": "arm64"}[build_app.ARCH]
    monkeypatch.setattr(build_app.subprocess, "run",
                        FakeRun((0, "/p/_psutil_osx.abi3.so\n", ""), (0, other + "\n", "")))
    with pytest.raises(SystemExit, match="not " + build_app.ARCH):
        build_app.check_psutil()


def test_the_real_psutil_in_pydeps_passes(capsys):
    if not os.path.isdir(os.path.join(build_app.PYDEPS, "psutil")):
        pytest.skip("no .pydeps (run build_app.py)")
    build_app.check_psutil()
    assert "psutil OK" in capsys.readouterr().out
