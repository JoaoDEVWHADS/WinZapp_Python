"""A fixed port for the bundled WPPConnect Server: Settings > Advanced.

By default each account's Node gets a port of its own in
[node_ports.BASE_PORT, +MAX_ACCOUNTS), chosen and kept by
MainWindow._resolve_wpp_port(); a saved port outside that window is dropped.
That leaves no way to move the API off 6300 for good: another program that
already listens there, or a second, separate copy of WinZapp (its own data
folder, so it cannot see this one's accounts), each pick it again.

A fixed port, set per account, wins over that allocation for the bundled API
only (a custom API keeps the Connection page's port). 0 means automatic. It
takes effect the next time the account starts, since the Node of this run is
already listening.

Held by something else at start (`keep_fixed()`), it is not used for that
run: WinZapp would otherwise "reuse" that program as its API
(ensure_wpp_running() sees something listening) and, finding no process of its
own on the port at exit, kill it if it is a node.exe. That includes another
account of this install, whose Node answers /winzapp/identity just like ours:
a port another account has saved is never taken. The automatic port is used
instead (never the rejected one, even when it was saved last run) and the fixed
one is tried again at the next start. A port that is busy but answers with our
installation id, with no other account on it, is this account's own Node from
a run still winding down: reused.
"""

SECTION = "advanced"
KEY = "local_api_port"

#: Below 1024 needs administrator rights on some systems; the Connection
#: page's port has always been held to the same range.
MIN_PORT = 1024
MAX_PORT = 65535


def parse_port(value):
    """The port in *value* (an int or the text of a field), or None when it is
    not a whole number in [MIN_PORT, MAX_PORT]."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
        value = int(value)
    if isinstance(value, int) and MIN_PORT <= value <= MAX_PORT:
        return value
    return None


def keep_fixed(port, peer_ports, is_free, runs_our_api) -> bool:
    """Whether the fixed *port* can be used this run.

    Not when another account of this install has it (*peer_ports*). Otherwise
    when it is free, or busy with a WinZapp Node of this install. *is_free* and
    *runs_our_api* are asked lazily, in that order: the identity request is
    only made for a busy port (a refused localhost connect costs about a second
    on Windows, at startup)."""
    if port in set(peer_ports or ()):
        return False
    return bool(is_free(port) or runs_our_api(port))


def identity_is_ours(identity, installation_id: str) -> bool:
    """Whether a /winzapp/identity answer is a WinZapp Node of this install."""
    return (isinstance(identity, dict) and identity.get("protocol_version") == 1
            and bool(installation_id) and identity.get("installation_id") == installation_id)


def fixed_port(settings):
    """The fixed port this account asked for, or None for automatic (no
    setting, 0, or a hand-edited value that is not a usable port)."""
    section = settings.get(SECTION) if isinstance(settings, dict) else None
    return parse_port(section.get(KEY)) if isinstance(section, dict) else None
