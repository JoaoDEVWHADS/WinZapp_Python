"""Which connection engine a stored WhatsApp session belongs to.

A session (the token in ``privateinfo``, the ``paired`` flag, an entry in
``sessions.json``) exists on exactly one engine: WPPConnect's browser profile,
the neonize bridge's database, or a custom server. Starting another engine with
that token asks it for a session it has never seen. The bridge answers by
minting a pairing code, and the client reads that as a corrupted profile or a
logout, then wipes or abandons a session that was fine on the other engine.

Two pieces of state keep the engines apart. ``privateinfo["session_engine"]``
names the engine the live token and ``paired`` flag belong to. A session store
entry carries an ``engine`` too. When the engine of this start differs from the
stored one, the old session is parked under ``privateinfo["engine_sessions"]``
(untouched, so switching back resumes it) and the account starts unpaired on the
new engine. Pure functions, no wx.
"""

from core import connection_engine as engines

# Fallback owner of a session with no token to tell by: the bundled
# WPPConnect, the only engine there was before the engine was recorded.
LEGACY_ENGINE = engines.WPPCONNECT

# The keys of ``privateinfo`` that describe the live session. The local
# database is not among them: it belongs to the account, not to an engine.
SESSION_KEYS = ("WA_token_protected", "WA_token", "paired", "WA_phone_number")

ENGINE_KEY = "session_engine"
PARKED_KEY = "engine_sessions"

UNCHANGED = "unchanged"
PARKED = "parked"
RESTORED = "restored"


def _is_bridge_token(token) -> bool:
    """Whether a session token was minted by the neonize bridge: its signature
    is a SHA-256 hex digest, where WPPConnect's is a bcrypt hash ($2b$10$...)."""
    signature = (token or "").partition(":")[2]
    return len(signature) == 64 and all(c in "0123456789abcdef" for c in signature)


def infer_engine(token, current: str) -> str:
    """The engine a session saved before the engine was recorded belongs to.

    The token says which it was made by. A bcrypt token is WPPConnect's, or --
    when this process is on a custom server -- that server's, which is how
    installs that used a custom API before the engine setting keep their
    session. Without a token there is nothing to tell apart: it is the current
    engine's."""
    if not token:
        return current
    if _is_bridge_token(token):
        return engines.NEONIZE
    return engines.CUSTOM if current == engines.CUSTOM else LEGACY_ENGINE


def entry_engine(entry, current: str = LEGACY_ENGINE) -> str:
    """The engine a ``sessions.json`` entry belongs to; ``entry`` is a store
    entry as ``SessionStore.list()`` returns it (token decrypted)."""
    engine = (entry or {}).get("engine")
    if engine in engines.ENGINES:
        return engine
    return infer_engine((entry or {}).get("token"), current)


def has_session(private_info: dict) -> bool:
    """Whether ``privateinfo`` describes a session at all."""
    return bool(private_info.get("WA_token_protected")
                or (private_info.get("WA_token") or "").strip()
                or private_info.get("paired"))


def reconcile(private_info: dict, current: str, token: str = "") -> str:
    """Make ``private_info`` agree with the engine this process runs on.

    ``token`` is the stored session token, used only when no engine was
    recorded yet (``infer_engine``).

    Returns ``UNCHANGED`` when it already did (or no session was involved, in
    which case stale session keys are simply dropped), ``PARKED`` when the
    session of another engine was set aside and the account now starts
    unpaired, and ``RESTORED`` when that engine had a session parked earlier
    and it is back.
    """
    owner = private_info.get(ENGINE_KEY)
    if owner not in engines.ENGINES:
        owner = infer_engine(token, current) if has_session(private_info) else current
    if owner == current:
        private_info[ENGINE_KEY] = current
        return UNCHANGED

    parked = private_info.setdefault(PARKED_KEY, {})
    had_session = has_session(private_info)
    if had_session:
        parked[owner] = {key: private_info.pop(key) for key in SESSION_KEYS
                         if key in private_info}
    else:
        for key in SESSION_KEYS:
            private_info.pop(key, None)
    private_info[ENGINE_KEY] = current
    restored = parked.pop(current, None)
    if not parked:
        private_info.pop(PARKED_KEY, None)
    if restored:
        private_info.update(restored)
        return RESTORED
    return PARKED if had_session else UNCHANGED
