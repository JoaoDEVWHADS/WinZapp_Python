""""Já existe uma janela de atualização aberta em outra conta" with one account.

Reported: some people, often with a single paired account, were told by
Help > Check for updates that another account's update dialog was open.

psutil is not a dependency, so every installed WinZapp takes the ctypes
fallback in update_coord._default_proc_create_time(), which returned the 0.0
"alive, create_time unknown" sentinel for every live process. Every lease and
prompt claim was therefore recorded with create_time 0.0 — measured: all 30
runtime leases of a source install carry "_0.0_" in their names — and
lease_alive() accepts 0.0 for ANY process that holds the pid. The prompt claim
is deliberately left on disk across an accepted update (the owner exits into
the installer), and Windows reuses pids quickly: on another install, pids of
WinZapps long gone were sitting under svchost, RuntimeBroker, msedgewebview2
and a Dell audio service. The first time such a process took the old pid, the
stale claim read as alive, for as long as that process lived.

Fixed twice over: the fallback reads the real creation time (GetProcessTimes),
and the prompt claim — which only ever guards against a second dialog — is
held only on a positive (pid, create_time) match. Install leases keep failing
closed (tests/test_update_coord.py::test_ct_unknown_sentinel_is_alive).
"""

import json
import os
import sys
import time

import pytest

import update_coord as uc

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="ctypes Windows fallback")


@pytest.fixture
def no_psutil(monkeypatch):
    monkeypatch.setitem(sys.modules, "psutil", None)


class TestRealCreateTimeWithoutPsutil:
    @windows_only
    def test_a_live_process_reports_its_real_creation_time(self, no_psutil):
        ct = uc._default_proc_create_time(os.getpid())
        assert isinstance(ct, float)
        assert ct != uc._CT_UNKNOWN
        assert 0 < ct <= time.time()
        # Stable: it identifies THIS process, so it must not drift.
        assert uc._default_proc_create_time(os.getpid()) == ct

    @windows_only
    def test_two_different_processes_report_different_times(self, no_psutil):
        parent = uc._default_proc_create_time(os.getppid())
        own = uc._default_proc_create_time(os.getpid())
        if parent in (None, uc._CT_UNKNOWN):
            pytest.skip("parent process not readable on this host")
        assert parent != own

    @windows_only
    def test_a_pid_that_does_not_exist_is_dead(self, no_psutil):
        assert uc._default_proc_create_time(4_000_000_000) is None

    @windows_only
    def test_a_new_identity_is_recorded_with_the_real_time(self, no_psutil):
        pid, ct = uc._resolve_identity(None, None)
        assert pid == os.getpid()
        assert ct not in (0.0, uc._CT_UNKNOWN)


class TestPromptOwnerAlive:
    def test_the_same_process_is_alive(self):
        assert uc.prompt_owner_alive(42, 1000.5, proc_create_time=lambda pid: 1000.5) is True

    def test_a_reused_pid_is_not_the_owner(self):
        """An unrelated process now holds the pid: its creation time differs."""
        assert uc.prompt_owner_alive(42, 1000.5, proc_create_time=lambda pid: 2000.0) is False

    def test_a_dead_pid_is_not_the_owner(self):
        assert uc.prompt_owner_alive(42, 1000.5, proc_create_time=lambda pid: None) is False

    def test_an_unreadable_creation_time_does_not_hold_the_prompt(self):
        """Unlike install leases: the worst case is a second dialog."""
        assert uc.prompt_owner_alive(42, 1000.5, proc_create_time=lambda pid: uc._CT_UNKNOWN) is False

    def test_a_claim_recorded_as_unknown_by_an_older_build_is_never_trusted(self):
        assert uc.prompt_owner_alive(42, 0.0, proc_create_time=lambda pid: 1000.5) is False

    def test_install_leases_still_fail_closed(self):
        assert uc.lease_alive(42, 0.0, proc_create_time=lambda pid: 1000.5) is True
        assert uc.lease_alive(42, 1000.5, proc_create_time=lambda pid: uc._CT_UNKNOWN) is True


def _write_claim(gd, owner_pid, owner_create_time):
    with open(os.path.join(gd, "update_prompt.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "1.1.1.0", "claimed_at": int(time.time()),
                   "owner_pid": owner_pid, "owner_create_time": owner_create_time,
                   "owner_token": "0123456789abcdef0123456789abcdef"}, f)


@pytest.fixture
def gd(tmp_path):
    d = tmp_path / "global"
    d.mkdir()
    return str(d)


class TestTheStuckClaim:
    @windows_only
    def test_a_stale_claim_on_a_reused_pid_no_longer_blocks(self, gd, no_psutil):
        """The reported state: a claim left by a finished update, recorded as
        0.0, whose pid is now held by some other live process."""
        live_other_process = os.getppid()
        _write_claim(gd, live_other_process, 0.0)

        token = uc.try_claim_update_prompt(gd, "1.2.0.0", pid=222, create_time=2.0)

        assert token is not None
        # Read the file, not update_prompt_holder(): pid 222 is a fake with no
        # process behind it, so the holder check would rightly clear it.
        with open(os.path.join(gd, "update_prompt.json"), encoding="utf-8") as f:
            assert json.load(f)["owner_pid"] == 222

    @windows_only
    def test_a_claim_with_a_wrong_creation_time_no_longer_blocks(self, gd, no_psutil):
        _write_claim(gd, os.getppid(), 12345.0)
        assert uc.try_claim_update_prompt(gd, "1.2.0.0", pid=222, create_time=2.0) is not None

    @windows_only
    def test_a_genuinely_open_dialog_still_blocks_another_process(self, gd, no_psutil):
        """This process really holds the prompt: another account must wait."""
        own = uc.try_claim_update_prompt(gd, "1.2.0.0")
        assert own is not None
        assert uc.try_claim_update_prompt(gd, "1.2.0.0", pid=222, create_time=2.0) is None
