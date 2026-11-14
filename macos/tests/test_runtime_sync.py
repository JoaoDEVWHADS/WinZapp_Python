"""Installing the bundled server runtime after an update (paths_mac.sync_runtime).

Measured on 2.1.0 (2026-10-15), the first launch after every update spent
5.3 s cloning the runtime file by file, 1.9 s deleting the old one before
the app could go on, and 5.5 s downloading chrome-headless-shell again
because api/.cache was left behind with the old runtime. These build two
small runtimes on disk and install one over the other; no Node is touched
(the stale-Node stop is stubbed, it would look for the real install's).
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

from winzapp_mac import paths_mac  # noqa: E402

SHELL = "chrome-headless-shell"
REVISIONS = """exports.PUPPETEER_REVISIONS = Object.freeze({
    chrome: '%s',
    'chrome-headless-shell': '%s',
    firefox: 'stable_150.0.2',
});
"""


def _write(path, text=""):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def _bundle(tmp_path, stamp, pin="148.0.7778.97", name="bundle"):
    b = tmp_path / name
    _write(str(b / "STAMP"), stamp + "\n")
    _write(str(b / "node" / "node"), "#!node")
    _write(str(b / "api" / "start.js"), "// " + stamp)
    if pin:
        _write(str(b / "api" / "node_modules" / "puppeteer-core" / "lib" / "cjs" / "puppeteer"
                   / "revisions.js"), REVISIONS % (pin, pin))
    return str(b)


def _shell(api, version):
    path = os.path.join(api, ".cache", SHELL, "mac_arm-" + version, "chrome-headless-shell-mac-arm64",
                        SHELL)
    _write(path, "binary")
    return path


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mac, "_stop_stale_node", lambda *a, **k: None)
    rm = []
    real_popen = subprocess.Popen

    def popen(cmd, **kw):
        proc = real_popen(cmd, **kw)
        rm.append(proc)
        return proc

    monkeypatch.setattr(paths_mac.subprocess, "Popen", popen)
    rt = str(tmp_path / "support" / "runtime")
    yield rt
    for proc in rm:
        proc.wait(timeout=30)


def _installed(rt, old_stamp, tmp_path, pin="148.0.7778.97"):
    assert paths_mac.sync_runtime(_bundle(tmp_path, old_stamp, pin, name="old-" + old_stamp), rt)
    return os.path.join(rt, "api")


def test_the_browser_survives_an_update_that_pins_the_same_version(runtime, tmp_path):
    shell = _shell(_installed(runtime, "v1", tmp_path), "148.0.7778.97")
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2"), runtime)
    assert open(os.path.join(runtime, "STAMP")).read().strip() == "v2"
    assert os.path.isfile(shell)


def test_a_new_pin_drops_the_old_browser_so_the_new_one_downloads(runtime, tmp_path):
    api = _installed(runtime, "v1", tmp_path)
    shell = _shell(api, "148.0.7778.97")
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2", pin="149.0.7800.1"), runtime)
    assert not os.path.exists(shell)
    # Nothing usable left, which is what makes WinZapp fetch the pinned one.
    assert os.listdir(os.path.join(api, ".cache", SHELL)) == []


def test_old_versions_do_not_pile_up(runtime, tmp_path):
    api = _installed(runtime, "v1", tmp_path)
    stale = _shell(api, "140.0.7000.1")
    current = _shell(api, "148.0.7778.97")
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2"), runtime)
    assert os.path.isfile(current) and not os.path.exists(stale)


def test_an_unreadable_pin_prunes_nothing(runtime, tmp_path):
    api = _installed(runtime, "v1", tmp_path)
    shell = _shell(api, "140.0.7000.1")
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2", pin=None), runtime)
    assert os.path.isfile(shell)


def test_a_bundled_browser_wins_and_carried_ones_join_it(runtime, tmp_path):
    api = _installed(runtime, "v1", tmp_path)
    _write(os.path.join(api, ".cache", SHELL, "mac_arm-148.0.7778.97", "marker"), "old")
    _write(os.path.join(api, ".cache", "chrome", "mac_arm-148.0.7778.97", "marker"), "old")
    bundle = _bundle(tmp_path, "v2")
    _write(os.path.join(bundle, "api", ".cache", SHELL, "mac_arm-148.0.7778.97", "marker"), "new")
    assert paths_mac.sync_runtime(bundle, runtime)
    assert open(os.path.join(api, ".cache", SHELL, "mac_arm-148.0.7778.97", "marker")).read() == "new"
    assert open(os.path.join(api, ".cache", "chrome", "mac_arm-148.0.7778.97", "marker")).read() == "old"


def test_the_servers_own_folders_still_carry_over(runtime, tmp_path):
    api = _installed(runtime, "v1", tmp_path)
    _write(os.path.join(api, "log", "wppconnect.log"), "kept")
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2"), runtime)
    assert open(os.path.join(api, "log", "wppconnect.log")).read() == "kept"


def test_the_old_runtime_is_deleted_in_the_background(runtime, tmp_path, monkeypatch):
    _installed(runtime, "v1", tmp_path)
    spawned = []
    monkeypatch.setattr(paths_mac.subprocess, "Popen", lambda cmd, **kw: spawned.append((cmd, kw)))
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v2"), runtime)
    # Startup went on with the old runtime only renamed aside...
    (cmd, kw), = spawned
    assert cmd[:2] == ["rm", "-rf"] and kw["start_new_session"]
    trash = cmd[2]
    assert trash.startswith(runtime + ".trash-")
    assert open(os.path.join(trash, "STAMP")).read().strip() == "v1"
    assert not os.path.exists(runtime + ".old")
    # ...and what an interrupted delete leaves is swept by the next launch.
    spawned.clear()
    assert not paths_mac.sync_runtime(_bundle(tmp_path, "v2"), runtime)
    assert [c for c, _ in spawned] == [["rm", "-rf", trash]]


def test_the_background_delete_finishes(runtime, tmp_path):
    old = os.path.join(os.path.dirname(runtime), "runtime.old")
    _write(os.path.join(old, "api", "node_modules", "x", "index.js"))
    proc = paths_mac._discard(old, runtime)
    assert not os.path.exists(old)
    assert proc.wait(timeout=30) == 0
    assert not [n for n in os.listdir(os.path.dirname(runtime)) if ".trash-" in n]
    assert paths_mac._discard(old, runtime) is None


def test_a_tree_is_cloned_whole(runtime, tmp_path, monkeypatch):
    calls = []
    real = paths_mac._clonefile
    monkeypatch.setattr(paths_mac, "_clonefile", lambda s, d: calls.append(s) or real(s, d))
    monkeypatch.setattr(paths_mac.subprocess, "run",
                        lambda *a, **k: pytest.fail("cp ran though clonefile worked"))
    bundle = _bundle(tmp_path, "v1")
    assert paths_mac.sync_runtime(bundle, runtime)
    assert calls == [bundle]
    assert open(os.path.join(runtime, "api", "start.js")).read() == "// v1"


def test_without_clonefile_the_runtime_is_still_copied(runtime, tmp_path, monkeypatch):
    monkeypatch.setattr(paths_mac, "_clonefile", lambda s, d: False)
    assert paths_mac.sync_runtime(_bundle(tmp_path, "v1"), runtime)
    assert open(os.path.join(runtime, "node", "node")).read() == "#!node"


def test_pins_are_read_from_puppeteer_core(tmp_path):
    api = os.path.join(_bundle(tmp_path, "v1", pin="148.0.7778.97"), "api")
    assert paths_mac.pinned_browser_versions(api) == {SHELL: {"148.0.7778.97"},
                                                      "chrome": {"148.0.7778.97"}}
    assert paths_mac.pinned_browser_versions(str(tmp_path / "nothing")) == {}
