"""Tests for client/update_coord.py — updater coordination (runtime leases +
update_state), the TOCTOU-safe protocol that gates start vs update install.
"""

import os

import pytest

import update_coord as uc


def _gd(tmp_path):
    gd = str(tmp_path / "global")
    os.makedirs(gd, exist_ok=True)
    return gd


def test_runtime_lease_create_and_list(tmp_path):
    gd = _gd(tmp_path)
    lease = uc.create_runtime_lease(gd, pid=1111, create_time=5.0)
    alive = lambda pid, ct: pid == 1111 and ct == 5.0
    live = uc.live_runtime_leases(gd, is_alive=alive)
    assert any(l["pid"] == 1111 for l in live)
    uc.release_runtime_lease(gd, lease)
    assert all(l["pid"] != 1111 for l in uc.live_runtime_leases(gd, is_alive=alive))


def test_dead_lease_filtered(tmp_path):
    gd = _gd(tmp_path)
    # A lease whose (pid, create_time) is not alive must be ignored + swept.
    uc.create_runtime_lease(gd, pid=999999, create_time=1.0)
    # Our fake liveness checker says nothing is alive
    live = uc.live_runtime_leases(gd, is_alive=lambda pid, ct: False)
    assert live == []


def test_lease_alive_pid_reuse_guard():
    # Same pid but different create_time -> NOT the same process (PID reuse).
    def fake_proc_create_time(pid):
        return 100.0 if pid == 42 else None
    assert uc.lease_alive(42, 100.0, proc_create_time=fake_proc_create_time) is True
    assert uc.lease_alive(42, 999.0, proc_create_time=fake_proc_create_time) is False
    assert uc.lease_alive(43, 100.0, proc_create_time=fake_proc_create_time) is False


def test_update_state_begin_end(tmp_path):
    gd = _gd(tmp_path)
    assert uc.is_update_in_progress(gd) is False
    uc.begin_update(gd, pid=222, create_time=9.0)
    alive = lambda pid, ct: pid == 222 and ct == 9.0
    assert uc.is_update_in_progress(gd, is_alive=alive) is True
    uc.end_update(gd)
    assert uc.is_update_in_progress(gd, is_alive=alive) is False


def test_update_state_dead_owner_recovered(tmp_path):
    gd = _gd(tmp_path)
    uc.begin_update(gd, pid=888888, create_time=1.0)
    # Owner is dead -> is_update_in_progress must recover (return False)
    assert uc.is_update_in_progress(gd, is_alive=lambda pid, ct: False) is False


def test_should_block_start(tmp_path):
    assert uc.should_block_start({"update_in_progress": True}) is True
    assert uc.should_block_start({"update_in_progress": False}) is False
    assert uc.should_block_start({}) is False


def test_should_block_update_with_live_leases():
    assert uc.should_block_update([{"pid": 1}]) is True
    assert uc.should_block_update([]) is False
