"""Tests for per-account Node port allocation (client/node_ports.py)."""

import node_ports as np


def test_base_port_is_historical_default():
    assert np.BASE_PORT == 6300


def test_sanitize_rejects_legacy_and_junk():
    assert np.sanitize_saved_port(3417) is None      # stale legacy default
    assert np.sanitize_saved_port(None) is None
    assert np.sanitize_saved_port("6300") is None     # not an int
    assert np.sanitize_saved_port(True) is None       # bool is not a port
    assert np.sanitize_saved_port(80) is None         # out of window
    assert np.sanitize_saved_port(6300) == 6300
    assert np.sanitize_saved_port(6305) == 6305


def test_deterministic_port_is_stable_and_in_window():
    a = np.deterministic_port("account-A")
    assert a == np.deterministic_port("account-A")     # stable
    assert np.BASE_PORT <= a < np.BASE_PORT + np.MAX_ACCOUNTS
    assert np.deterministic_port("") == np.BASE_PORT    # legacy/blank


def test_deterministic_ports_differ_by_account():
    # Order-independent: two distinct ids should (almost always) differ. Both
    # ids used here hash to different slots — the core anti-race property.
    assert np.deterministic_port("aaa") != np.deterministic_port("bbb")


def test_allocate_for_account_avoids_peer_and_probes():
    aid = "acct"
    home = np.deterministic_port(aid)
    # Peer already on our home port → we move forward to home+1.
    assert np.allocate_port_for_account(aid, taken=[home]) == np.BASE_PORT + (
        (home - np.BASE_PORT + 1) % np.MAX_ACCOUNTS)
    # Home port not bindable → also move on.
    busy = {home}
    assert np.allocate_port_for_account(aid, taken=[], is_free=lambda p: p not in busy) != home


def test_resolve_keeps_valid_saved_port():
    assert np.resolve_account_port("A", 6304, peer_ports=[6300, 6301]) == 6304


def test_resolve_keeps_saved_even_if_not_free_now():
    # Our own Node from last launch may still hold the port; stability wins.
    assert np.resolve_account_port("A", 6304, peer_ports=[], is_free=lambda p: False) == 6304


def test_resolve_moves_off_port_a_peer_already_took():
    # THE upgrade case: both accounts had 6300 saved. This account sees a peer
    # on 6300 → must move to its own deterministic port, not stay and collide.
    got = np.resolve_account_port("acct", 6300, peer_ports=[6300])
    assert got != 6300


def test_resolve_two_upgraded_accounts_get_distinct_ports():
    # Simulate the real migration: both saved 6300. Resolved independently
    # (order-independent, deterministic) they must not land on the same port.
    a = np.resolve_account_port("id-alpha", 6300, peer_ports=[6300])
    b = np.resolve_account_port("id-beta", 6300, peer_ports=[6300])
    assert a != b


def test_resolve_allocates_when_no_saved_port():
    got = np.resolve_account_port("acct", None, peer_ports=[6300])
    assert got != 6300
    assert np.BASE_PORT <= got < np.BASE_PORT + np.MAX_ACCOUNTS


def test_resolve_reallocates_legacy_port():
    # Legacy 3417 is treated as unsaved → gets a real window port.
    got = np.resolve_account_port("acct", 3417, peer_ports=[])
    assert np.BASE_PORT <= got < np.BASE_PORT + np.MAX_ACCOUNTS
