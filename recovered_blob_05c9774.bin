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

# ── Update URLs ───────────────────────────────────────────────────────────────

UPDATE_VERSION_URL = os.environ.get(
    "WINZAPP_VERSION_URL",
    "https://raw.githubusercontent.com/JoaoDEVWHADS/WinZapp_Python/main/version.json",
)

UPDATE_CHANGELOG_URL = os.environ.get(
    "WINZAPP_CHANGELOG_URL",
    "https://raw.githubusercontent.com/JoaoDEVWHADS/WinZapp_Python/main/changelog.txt",
)

UPDATE_ZIP_URL = os.environ.get(
    "WINZAPP_ZIP_URL",
    "https://github.com/JoaoDEVWHADS/WinZapp_Python/releases/latest/download/WinZapp.zip",
)
