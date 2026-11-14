"""Which recorded WinZapp process is still alive, on the Mac (coord_mac).

Measured on a real install: without psutil every runtime lease recorded 0.0
for its creation time, normal quits (os._exit) never released them, and
update_coord's lease_alive() accepted a 0.0 lease for ANY process holding the
pid, with nothing off Windows able to prove the pid was not WinZapp. 35
leaked leases, one now a system daemon's pid: every update refused "another
account is running", and a stale update in progress could make every launch
exit at once. These tests use real processes and update_coord's own liveness
code, nothing stubbed: a leaked lease whose pid is now another program is
dead, a live account process is alive, the start-up gate and the update slot
follow.
"""

import os
import subprocess
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client"), os.path.join(ROOT, ".pydeps")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

import update_coord  # noqa: E402

from winzapp_mac import coord_mac  # noqa: E402


@pytest.fixture
def daemon():
    """Another program (not WinZapp) holding a pid, as ctkahp did."""
    proc = subprocess.Popen(["/bin/sleep", "60"])
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def account():
    """Another WinZapp process: this interpreter, as a second account would be
    this app's executable."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(0.2)
    yield proc
    proc.kill()
    proc.wait()


@pytest.fixture
def mac_layer(monkeypatch):
    """What coord_mac.install() does, undone after the test."""
    monkeypatch.setattr(update_coord, "_default_proc_matches_us", coord_mac.matches_us)


def _dead_pid():
    proc = subprocess.Popen(["/usr/bin/true"])
    proc.wait()
    return proc.pid


@pytest.mark.parametrize("hide_psutil", [False, True])
def test_another_program_is_not_us_and_we_are(monkeypatch, daemon, hide_psutil):
    """With psutil (what the app ships) and without it (ps), on real pids."""
    if hide_psutil:
        monkeypatch.setitem(sys.modules, "psutil", None)
    assert coord_mac.matches_us(daemon.pid) is False
    assert coord_mac.matches_us(os.getpid()) is True
    assert coord_mac.matches_us(_dead_pid()) is False


def test_a_leaked_lease_on_a_reused_pid_is_dead(tmp_path, mac_layer, daemon):
    """update_coord's own lease_alive (what main.py's start-up gate and every
    lease listing use) reaps it once the Mac layer is in."""
    gd = str(tmp_path)
    update_coord.try_create_runtime_lease(gd, pid=daemon.pid, create_time=0.0)
    assert update_coord.live_runtime_leases(gd) == []


def test_a_stale_update_in_progress_does_not_block_every_launch(tmp_path, mac_layer, daemon):
    gd = str(tmp_path)
    update_coord._write_state(gd, {"update_in_progress": True, "owner_pid": daemon.pid,
                                   "owner_create_time": 0.0, "owner_token": "a" * 32})
    assert update_coord.is_update_in_progress(gd) is False
    assert update_coord.try_create_runtime_lease(gd) is not None      # a new account starts


def test_a_live_account_is_alive(tmp_path, mac_layer, account):
    pytest.importorskip("psutil")
    gd = str(tmp_path)
    update_coord.try_create_runtime_lease(gd, pid=account.pid)
    assert [l["pid"] for l in update_coord.live_runtime_leases(gd)] == [account.pid]


def test_the_strict_rule_for_the_update_slot(account, daemon):
    psutil = pytest.importorskip("psutil")
    assert coord_mac.lease_alive(account.pid, psutil.Process(account.pid).create_time())
    assert not coord_mac.lease_alive(account.pid, 0.0)                 # recorded before psutil
    assert not coord_mac.lease_alive(daemon.pid, psutil.Process(daemon.pid).create_time())
    assert not coord_mac.lease_alive(account.pid, 12345.0)             # the pid was reused


def test_leaked_leases_no_longer_block_the_update_slot(tmp_path, mac_layer, daemon):
    """The reported failure: leaked 0.0 leases (one on a daemon's pid) made
    try_begin_update refuse forever."""
    pytest.importorskip("psutil")
    gd = str(tmp_path)
    update_coord.try_create_runtime_lease(gd)                          # this account
    update_coord.try_create_runtime_lease(gd, pid=daemon.pid, create_time=0.0)
    update_coord.try_create_runtime_lease(gd, pid=_dead_pid(), create_time=0.0)
    token = update_coord.try_begin_update(gd, is_alive=coord_mac.lease_alive)
    assert token is not None
    assert update_coord.end_update(gd, token)


def test_a_running_account_still_blocks_it(tmp_path, mac_layer, account):
    pytest.importorskip("psutil")
    gd = str(tmp_path)
    update_coord.try_create_runtime_lease(gd)
    update_coord.try_create_runtime_lease(gd, pid=account.pid)
    assert update_coord.try_begin_update(gd, is_alive=coord_mac.lease_alive) is None
    account.kill()
    account.wait()
    assert update_coord.try_begin_update(gd, is_alive=coord_mac.lease_alive) is not None


def test_without_psutil_the_0_rule_is_off_and_our_own_lease_stays_alive(monkeypatch, daemon):
    """If psutil ever failed to import, every lease (ours too) would be 0.0:
    the strict rule must not read live accounts as gone."""
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert not coord_mac.can_measure()
    assert coord_mac.lease_alive(os.getpid(), 0.0)
    assert not coord_mac.lease_alive(daemon.pid, 0.0)                   # not WinZapp: still dead


def test_psutil_ships_with_the_mac_build():
    sys.path.insert(0, os.path.join(ROOT, "macos"))
    import build_app
    assert any(r.startswith("psutil==") for r in build_app.MAC_EXTRA)
