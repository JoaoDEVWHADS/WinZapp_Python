"""
Runtime configuration loaded from environment / .env file.

Values can be overridden by placing a .env file next to WinZapp.exe
(or next to this file in dev mode) with KEY=VALUE lines.
"""

import os
from app_paths import _outer_exe_dir

# ── Load .env file ────────────────────────────────────────────────────────────

def _load_dotenv():
    env_path = os.path.join(_outer_exe_dir(), ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key   = key.strip()
                value = value.strip()
                # Don't override values already set in the real environment
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass

_load_dotenv()

# ── Update source: GitHub Releases ───────────────────────────────────────────
# Override WINZAPP_GITHUB_REPO in .env to point at a fork.

GITHUB_REPO = os.environ.get("WINZAPP_GITHUB_REPO", "gabrielhhaber/WinZapp_Python")

# The releases LISTING (despite the historical name). Newest-first, paginated —
# it returns 30 entries unless per_page says otherwise, and it includes
# prereleases and drafts.
GITHUB_API_LATEST_RELEASE = (
    f"https://api.github.com/repos/{GITHUB_REPO}/releases"
)

# The single latest STABLE release. GitHub defines this endpoint as the newest
# release that is neither a draft nor a prerelease, which is exactly the stable
# channel — and, critically, it is not affected by paging. Since alpha builds
# are published for every commit on main (and marked prerelease), they would
# otherwise eventually fill the entire first page of the listing above and push
# the newest stable release out of it, silently stranding every user on the
# stable channel. See UpdateChecker._fetch_releases() in updater.py.
GITHUB_API_LATEST_STABLE_RELEASE = f"{GITHUB_API_LATEST_RELEASE}/latest"
