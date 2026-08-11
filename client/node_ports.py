"""Per-account WPPConnect Node port allocation (client/node_ports.py).

Multi-account isolation (revised architecture): instead of ONE shared Node on a
fixed port 6300 that every account's Chrome/Puppeteer session fought over — which
let two sessions race to resume on the same Node and pushed one to a QR re-pair,
and let the last-closing process taskkill a Node still serving another account —
EACH account now runs its OWN Node on its OWN port. Sessions are then fully
isolated: a process only ever starts/stops its own Node, and one account's resume
or shutdown can never disturb another's.

This module is the pure, testable core: pick a stable port for an account and
know which ports peers occupy. The actual socket bind / spawn lives in main.py.

Port model:
  * BASE_PORT (6300) keeps the historical default so a single-account install
    behaves exactly as before.
  * Each account persists its chosen port in its own settings (connection.wpp_port)
    so it is STABLE across launches — the same Node/userDataDir every time.
  * On first run (no saved port) allocate_port() picks the lowest free port in
    [BASE_PORT, BASE_PORT+MAX_ACCOUNTS) that no live peer already uses and that
    is_free() confirms is bindable, so two accounts never collide.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

BASE_PORT = 6300
MAX_ACCOUNTS = 50          # search window [6300, 6350) — far more than realistic
_LEGACY_PORT = 3417        # a stale default some old settings carry; never reuse


def sanitize_saved_port(port) -> Optional[int]:
    """Return a usable saved port, or None if the stored value is unusable.

    Guards against the legacy 3417 default and any non-int / out-of-range junk
    that could be sitting in an old settings.json.
    """
    if not isinstance(port, int) or isinstance(port, bool):
        return None
    if port == _LEGACY_PORT:
        return None
    if BASE_PORT <= port < BASE_PORT + MAX_ACCOUNTS:
        return port
    return None


def allocate_port(
    taken: Iterable[int],
    is_free: Callable[[int], bool] = lambda p: True,
) -> int:
    """Lowest free port in the search window not already claimed by a peer.

    ``taken``   ports other accounts have persisted / are using.
    ``is_free`` predicate confirming a port can actually be bound right now
                (injected so tests need no real sockets). A port that is taken
                by a peer OR fails is_free() is skipped.

    Falls back to BASE_PORT if nothing in the window is free (degenerate; the
    caller will still try to bind and surface a real error rather than guess).
    """
    taken_set = {p for p in taken if isinstance(p, int)}
    for port in range(BASE_PORT, BASE_PORT + MAX_ACCOUNTS):
        if port in taken_set:
            continue
        if is_free(port):
            return port
    return BASE_PORT


def deterministic_port(account_id: str) -> int:
    """A stable port derived from the account id, so two accounts pick DIFFERENT
    ports without coordinating and WITHOUT depending on launch order.

    A "lowest free port" scheme races: two accounts booting together both see
    only the other's stale 6300 and both then pick 6301. Hashing the id spreads
    them deterministically across the window; the rare hash collision is then
    resolved by probing (see allocate_port_for_account). A missing/blank id
    falls back to BASE_PORT (single-account / legacy)."""
    if not account_id:
        return BASE_PORT
    import hashlib
    h = int(hashlib.md5(account_id.encode("utf-8")).hexdigest(), 16)
    return BASE_PORT + (h % MAX_ACCOUNTS)


def allocate_port_for_account(
    account_id: str,
    taken: Iterable[int],
    is_free: Callable[[int], bool] = lambda p: True,
) -> int:
    """Deterministic per-account port, avoiding peer ports and unbindable ones.

    Starts at deterministic_port(account_id) — order-independent, so concurrent
    first launches never collide on the same 'lowest free' slot — then linearly
    probes forward (wrapping in the window) past any port a peer already took or
    that isn't bindable right now."""
    start = deterministic_port(account_id)
    taken_set = {p for p in taken if isinstance(p, int)}
    for i in range(MAX_ACCOUNTS):
        port = BASE_PORT + ((start - BASE_PORT + i) % MAX_ACCOUNTS)
        if port in taken_set:
            continue
        if is_free(port):
            return port
    return start


def resolve_account_port(
    account_id: str,
    saved_port,
    peer_ports: Iterable[int],
    is_free: Callable[[int], bool] = lambda p: True,
) -> int:
    """The port this account should use.

    Keeps a valid saved port (stable across launches) UNLESS a peer account has
    persisted the SAME port — the pre-per-account-port world left every account
    on 6300, so on the first launch after upgrading we must detect that clash
    and move the clashing accounts off it (deterministically, by id, so both
    ends of the clash don't stampede to the same replacement). A saved port free
    of peer clash is honoured even if is_free() is momentarily False (our own
    Node from a previous launch may still be winding down / already ours) —
    stability of the per-account Node/userDataDir matters more than an
    instantaneous free check. Only clashing / unsaved accounts allocate afresh.
    """
    valid = sanitize_saved_port(saved_port)
    peer_set = {p for p in peer_ports if isinstance(p, int)}
    if valid is not None and valid not in peer_set:
        return valid
    return allocate_port_for_account(account_id, peer_set, is_free)
