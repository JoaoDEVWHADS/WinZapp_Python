"""Tests for client/node_coord.py — shared WPPConnect Node coordination.

Pure/injectable logic: instance identity + health, per-account leases, and the
start/adopt/stop state machine (starting/ready/stopping) with crash recovery.
No real Node/HTTP/psutil — all effects are injected.
"""

import json
import os

import pytest

import node_coord as nc


def _gd(tmp_path):
    gd = str(tmp_path / "global")
    os.makedirs(gd, exist_ok=True)
    return gd


# ── leases ───────────────────────────────────────────────────────────────────
def test_add_and_list_node_lease(tmp_path):
    gd = _gd(tmp_path)
    nc.add_node_lease(gd, "a" * 32, pid=100, create_time=1.0)
    live = nc.live_node_leases(gd, is_alive=lambda p, c: True)
    assert any(l["account_id"] == "a" * 32 for l in live)


def test_dead_node_lease_swept(tmp_path):
    gd = _gd(tmp_path)
    nc.add_node_lease(gd, "a" * 32, pid=100, create_time=1.0)
    assert nc.live_node_leases(gd, is_alive=lambda p, c: False) == []


def test_release_node_lease(tmp_path):
    gd = _gd(tmp_path)
    nc.add_node_lease(gd, "a" * 32, pid=100, create_time=1.0)
    nc.release_node_lease(gd, "a" * 32)
    assert nc.live_node_leases(gd, is_alive=lambda p, c: True) == []


def test_corrupt_node_lease_counts_live(tmp_path):
    gd = _gd(tmp_path)
    d = os.path.join(gd, "node_leases")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "bad"), "w").write("{ nope")
    live = nc.live_node_leases(gd, is_alive=lambda p, c: False)
    assert len(live) == 1 and live[0].get("_corrupt")


# ── should_stop_node ─────────────────────────────────────────────────────────
def test_should_stop_node_only_when_last_lease_ours(tmp_path):
    # our account is the only live lease -> we may stop the node
    assert nc.should_stop_node(["a" * 32], releasing="a" * 32) is True
    # another account still holds a lease -> must NOT stop
    assert nc.should_stop_node(["a" * 32, "b" * 32], releasing="a" * 32) is False
    # no leases at all -> nothing to stop
    assert nc.should_stop_node([], releasing="a" * 32) is False


# ── identity / health ────────────────────────────────────────────────────────
def test_identity_match_and_mismatch():
    want = {"installation_id": "inst", "instance_id": "X", "protocol_version": 1}
    assert nc.identity_matches(want, {"installation_id": "inst", "instance_id": "X",
                                      "protocol_version": 1, "pid": 7}) is True
    # different instance_id -> not our node (someone else on the port)
    assert nc.identity_matches(want, {"installation_id": "inst", "instance_id": "Y",
                                      "protocol_version": 1, "pid": 7}) is False
    assert nc.identity_matches(want, None) is False


# ── instance marker state machine + recovery ─────────────────────────────────
def test_starting_marker_has_deadline(tmp_path):
    gd = _gd(tmp_path)
    nc.write_instance_marker(gd, state="starting", instance_id="X",
                             pid=None, create_time=None, startup_deadline=999.0)
    m = nc.read_instance_marker(gd)
    assert m["state"] == "starting" and m["startup_deadline"] == 999.0


def test_recover_starting_past_deadline_is_stale(tmp_path):
    gd = _gd(tmp_path)
    nc.write_instance_marker(gd, state="starting", instance_id="X",
                             pid=None, create_time=None, startup_deadline=0.0)
    # now well past deadline, no identity available -> stale, must not adopt
    action = nc.plan_startup(gd, now=100.0, probe_identity=lambda: None,
                             is_alive=lambda p, c: False)
    assert action["action"] == "start_new"


def test_ready_matching_identity_is_adopted(tmp_path):
    gd = _gd(tmp_path)
    nc.write_instance_marker(gd, state="ready", instance_id="X",
                             pid=200, create_time=2.0)
    ident = {"installation_id": nc.installation_id(gd), "instance_id": "X",
             "protocol_version": nc.PROTOCOL_VERSION, "pid": 200}
    action = nc.plan_startup(gd, now=5.0, probe_identity=lambda: ident,
                             is_alive=lambda p, c: True)
    assert action["action"] == "adopt"


def test_stopping_marker_never_adopted(tmp_path):
    gd = _gd(tmp_path)
    nc.write_instance_marker(gd, state="stopping", instance_id="X",
                             pid=200, create_time=2.0)
    # A node marked stopping must be finished + cleared, then start fresh — never
    # adopted (GPT r5 #4).
    action = nc.plan_startup(gd, now=5.0, probe_identity=lambda: None,
                             is_alive=lambda p, c: False)
    assert action["action"] == "start_new"


def test_no_marker_starts_new(tmp_path):
    gd = _gd(tmp_path)
    action = nc.plan_startup(gd, now=1.0, probe_identity=lambda: None,
                             is_alive=lambda p, c: False)
    assert action["action"] == "start_new"


def test_installation_id_stable(tmp_path):
    gd = _gd(tmp_path)
    a = nc.installation_id(gd)
    b = nc.installation_id(gd)
    assert a == b and len(a) >= 8
