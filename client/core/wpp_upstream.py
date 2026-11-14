"""The newest WPPConnect Server release upstream, for the users who asked for it.

By default WinZapp only offers the server its build was pinned to and the
releases the maintainers approved for that pin (core/wpp_approved.py): the
patches in client/api_patches/ follow the server by hand, and a release they
were not ported to can break features. Settings > Advanced > "Show every
WPPConnect Server update" puts back what WinZapp did before the approved list
existed: the newest upstream release is offered too, still never below the pin.

The tag read from GitHub goes into a download URL, so only a plain "X.Y.Z"
(with an optional leading v) is ever accepted, exactly as an approved entry.

Pure functions plus one fetch, no wx, so the selection is tested directly.
"""

import logging

from core.wpp_approved import _release

#: Install-wide (app_settings._GENERAL_GLOBAL): the api/ folder is shared by
#: every account, so one account cannot run a different server than another.
SETTING = "wpp_all_updates"

LATEST_RELEASE_URL = (
    "https://api.github.com/repos/wppconnect-team/wppconnect-server/releases/latest")


def enabled(settings) -> bool:
    """Whether every upstream release is offered; off unless set to True."""
    general = (settings or {}).get("general") if isinstance(settings, dict) else None
    return isinstance(general, dict) and general.get(SETTING) is True


def newest_tag(*tags) -> str:
    """The newest of *tags* as "vX.Y.Z", "" when none is a plain release.
    A malformed tag (a branch name, a pre-release, a path) is ignored."""
    best = None
    for tag in tags:
        version = _release(tag)
        if version is not None and (best is None or version > best):
            best = version
    return f"v{best}" if best is not None else ""


def fetch_latest_tag(user_agent: str, timeout: float = 15) -> str:
    """The newest upstream release's tag ("v2.10.60"), "" when it cannot be
    read or is not a plain release. Never raises: a missing answer only means
    nothing beyond the approved list is offered this time."""
    try:
        from core import tls_trust
        resp = tls_trust.get(LATEST_RELEASE_URL,
                             headers={"User-Agent": user_agent}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        tag = data.get("tag_name") if isinstance(data, dict) else None
    except Exception as exc:
        logging.warning("[wpp_upstream] Could not read the newest WPPConnect "
                        "Server release: %s", type(exc).__name__)
        return ""
    return newest_tag(tag)
