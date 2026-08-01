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


ALIVE = lambda pid, ct: True


def test_runtime_lease_create_and_list(tmp_path):
    gd = _gd(tmp_path)
    alive = lambda pid, ct: pid == 1111 and ct == 5.0
    lease = uc.try_create_runtime_lease(gd, pid=1111, create_time=5.0, is_alive=alive)
    assert lease is not None
    live = uc.live_runtime_leases(gd, is_alive=alive)
    assert any(l["pid"] == 1111 for l in live)
    uc.release_runtime_lease(gd, lease)
    assert all(l.get("pid") != 1111 for l in uc.live_runtime_leases(gd, is_alive=alive))


def test_dead_lease_filtered(tmp_path):
    gd = _gd(tmp_path)
    uc.try_create_runtime_lease(gd, pid=999999, create_time=1.0, is_alive=ALIVE)
    live = uc.live_runtime_leases(gd, is_alive=lambda pid, ct: False)
    assert live == []


def test_lease_alive_pid_reuse_guard():
    def fake(pid):
        return 100.0 if pid == 42 else None
    assert uc.lease_alive(42, 100.0, proc_create_time=fake) is True
    assert uc.lease_alive(42, 999.0, proc_create_time=fake) is False  # PID reuse
    assert uc.lease_alive(43, 100.0, proc_create_time=fake) is False


def test_begin_end_update_with_token(tmp_path):
    gd = _gd(tmp_path)
    assert uc.is_update_in_progress(gd) is False
    tok = uc.try_begin_update(gd, pid=222, create_time=9.0, is_alive=ALIVE)
    assert tok is not None and tok["owner_token"]
    alive = lambda pid, ct: pid == 222 and ct == 9.0
    assert uc.is_update_in_progress(gd, is_alive=alive) is True
    assert uc.end_update(gd, tok) is True
    assert uc.is_update_in_progress(gd, is_alive=alive) is False


def test_dead_owner_recovered(tmp_path):
    gd = _gd(tmp_path)
    uc.try_begin_update(gd, pid=888888, create_time=1.0, is_alive=ALIVE)
    assert uc.is_update_in_progress(gd, is_alive=lambda pid, ct: False) is False


def test_should_block_start():
    assert uc.should_block_start({"update_in_progress": True}) is True
    assert uc.should_block_start({"update_in_progress": False}) is False
    assert uc.should_block_start({}) is False


def test_should_block_update_with_live_leases():
    assert uc.should_block_update([{"pid": 1}]) is True
    assert uc.should_block_update([]) is False


def test_try_create_lease_blocked_during_update(tmp_path):
    gd = _gd(tmp_path)
    tok = uc.try_begin_update(gd, pid=500, create_time=1.0, is_alive=ALIVE)
    assert tok is not None
    assert uc.try_create_runtime_lease(gd, pid=501, create_time=2.0, is_alive=ALIVE) is None


def test_try_begin_update_refuses_when_accounts_live(tmp_path):
    gd = _gd(tmp_path)
    uc.try_create_runtime_lease(gd, pid=600, create_time=1.0, is_alive=ALIVE)
    assert uc.try_begin_update(gd, pid=601, create_time=2.0, is_alive=ALIVE) is None


def test_try_begin_update_refuses_second_live_updater(tmp_path):
    gd = _gd(tmp_path)
    tok = uc.try_begin_update(gd, pid=700, create_time=1.0, is_alive=ALIVE)
    assert tok is not None
    assert uc.try_begin_update(gd, pid=701, create_time=2.0, is_alive=ALIVE) is None


def test_end_update_requires_token(tmp_path):
    gd = _gd(tmp_path)
    uc.try_begin_update(gd, pid=800, create_time=1.0, is_alive=ALIVE)
    with pytest.raises(ValueError):
        uc.end_update(gd, None)  # token mandatory (GPT r3 #1)


def test_end_update_wrong_token_refused(tmp_path):
    gd = _gd(tmp_path)
    tok = uc.try_begin_update(gd, pid=800, create_time=1.0, is_alive=ALIVE)
    bad = {"owner_pid": 800, "owner_create_time": 1.0, "owner_token": "deadbeef"}
    assert uc.end_update(gd, bad) is False
    assert uc.is_update_in_progress(gd, is_alive=ALIVE) is True
    assert uc.end_update(gd, tok) is True


def test_stale_same_pid_token_cannot_end_new_update(tmp_path):
    """A token from an earlier run of the SAME pid must not end a newer update
    (GPT r3 #2 — owner_token identifies the specific install run)."""
    gd = _gd(tmp_path)
    old = uc.try_begin_update(gd, pid=900, create_time=1.0, is_alive=ALIVE)
    uc.end_update(gd, old)
    new = uc.try_begin_update(gd, pid=900, create_time=1.0, is_alive=ALIVE)
    assert uc.end_update(gd, old) is False  # stale token rejected
    assert uc.is_update_in_progress(gd, is_alive=ALIVE) is True
    assert uc.end_update(gd, new) is True


def test_corrupt_update_state_fails_closed(tmp_path):
    gd = _gd(tmp_path)
    open(os.path.join(gd, "update_state.json"), "w").write("{ broken")
    assert uc.is_update_in_progress(gd) is True


def test_type_invalid_owner_pid_fails_closed(tmp_path):
    gd = _gd(tmp_path)
    import json
    open(os.path.join(gd, "update_state.json"), "w").write(
        json.dumps({"update_in_progress": True, "owner_pid": {}, "owner_create_time": 1.0})
    )
    # owner_pid={} must not raise; must fail closed (GPT r3 #3)
    assert uc.is_update_in_progress(gd) is True


def test_corrupt_lease_counts_as_live(tmp_path):
    gd = _gd(tmp_path)
    d = os.path.join(gd, "runtime")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "garbage"), "w").write("{ not json")
    live = uc.live_runtime_leases(gd, is_alive=lambda pid, ct: False)
    assert len(live) == 1 and live[0].get("_corrupt") is True


def test_type_invalid_lease_counts_as_live(tmp_path):
    gd = _gd(tmp_path)
    d = os.path.join(gd, "runtime")
    os.makedirs(d, exist_ok=True)
    import json
    open(os.path.join(d, "bad"), "w").write(json.dumps({"pid": True, "create_time": "NaN"}))
    live = uc.live_runtime_leases(gd, is_alive=lambda pid, ct: False)
    assert len(live) == 1 and live[0].get("_corrupt") is True


def test_leftover_tmp_ignored(tmp_path):
    gd = _gd(tmp_path)
    d = os.path.join(gd, "runtime")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "x.tmp"), "w").write("partial")
    live = uc.live_runtime_leases(gd, is_alive=ALIVE)
    assert live == []


# ── GPT r4 hardening ─────────────────────────────────────────────────────────
def test_try_ops_reject_invalid_identity(tmp_path):
    gd = _gd(tmp_path)
    for bad_pid, bad_ct in [(0, 1.0), (-1, 1.0), (True, 1.0), (10, float("nan")), (10, -1.0)]:
        with pytest.raises(ValueError):
            uc.try_create_runtime_lease(gd, pid=bad_pid, create_time=bad_ct, is_alive=ALIVE)
        with pytest.raises(ValueError):
            uc.try_begin_update(gd, pid=bad_pid, create_time=bad_ct, is_alive=ALIVE)


def test_state_missing_owner_token_is_corrupt(tmp_path):
    gd = _gd(tmp_path)
    import json
    open(os.path.join(gd, "update_state.json"), "w").write(
        json.dumps({"update_in_progress": True, "owner_pid": 5, "owner_create_time": 1.0})
    )
    # in-progress without a valid owner_token -> corrupt -> fail-closed
    assert uc.is_update_in_progress(gd) is True


def test_ct_unknown_sentinel_is_alive():
    # unknown create_time (sentinel 0.0) must count as alive (fail-closed)
    assert uc.lease_alive(123, 5.0, proc_create_time=lambda pid: 0.0) is True
    assert uc.lease_alive(123, 5.0, proc_create_time=lambda pid: None) is False


# ── GPT r5 hardening ─────────────────────────────────────────────────────────
def test_valid_ct_rejects_negative_and_huge():
    assert uc._valid_ct(-1.0) is False
    assert uc._valid_ct(float("inf")) is False
    assert uc._valid_ct(10 ** 400) is False  # would OverflowError in isfinite
    assert uc._valid_ct(0) is True
    assert uc._valid_ct(123.5) is True


def test_release_lease_rejects_path_traversal(tmp_path):
    gd = _gd(tmp_path)
    tok = uc.try_begin_update(gd, pid=10, create_time=1.0, is_alive=ALIVE)
    assert tok is not None
    uc.release_runtime_lease(gd, "../update_state.json")
    uc.release_runtime_lease(gd, "/etc/passwd")
    uc.release_runtime_lease(gd, "a/b")
    # state file survived the traversal attempts
    assert uc.is_update_in_progress(gd, is_alive=ALIVE) is True


def test_state_dir_instead_of_file_is_corrupt(tmp_path):
    gd = _gd(tmp_path)
    os.mkdir(os.path.join(gd, "update_state.json"))  # a directory, not a file
    assert uc.is_update_in_progress(gd) is True  # corrupt -> fail-closed
