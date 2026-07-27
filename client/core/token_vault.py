"""
Secure at-rest storage for the WPPConnect session token (client/core/token_vault.py)
====================================================================================
settings.json is an ordinary file in the per-install data directory with no
special ACLs — any process running as the same Windows user can read it. Until
this module existed, the WPPConnect session token (WA_token) sat in that file
as plain JSON, so anyone who could read settings.json — malware running as the
user, a backup, a support screen-share — had it outright.

This does not, and cannot, defend against a fully compromised machine: an
attacker with code execution as the same Windows user can call
CryptUnprotectData() themselves, exactly like this module does. What it does
raise the bar against is the far more common case: a file simply being read,
copied elsewhere, or included in a backup/support bundle. A DPAPI blob is
worthless outside the Windows user profile it was protected under — copy
settings.json to another machine, another user account, or a live-boot
filesystem read, and CryptUnprotectData() fails.

Windows DPAPI (win32crypt.CryptProtectData/CryptUnprotectData) was chosen over
layering another Fernet key on top of the existing one (client/core/utils.py):
that key already sits in a plain file (secret.key) right next to the data it
protects, so it adds obfuscation but not a meaningfully different secret
boundary. DPAPI's protection comes from the OS itself, derived from the user's
own login credentials — a genuinely different (and stronger) trust boundary,
not just "another key file to also go looking for".
"""

import base64
import logging

try:
    import win32crypt
    _DPAPI_AVAILABLE = True
except ImportError:
    _DPAPI_AVAILABLE = False

# Additional entropy mixed into the DPAPI call. This is NOT a secret on its
# own (it lives in this source file) — its purpose is only to scope the blob
# so nothing else on the machine can blindly CryptUnprotectData() it with no
# extra argument and get a hit; the real protection is DPAPI's own per-user
# master key, which this entropy value cannot substitute for or weaken.
_ENTROPY = b"WinZapp.WA_token.v1"
_DESCRIPTION = "WinZapp WPPConnect session token"


def is_available() -> bool:
    """True if DPAPI protection can actually be used (Windows + pywin32)."""
    return _DPAPI_AVAILABLE


def protect_token(plain_token: str) -> str:
    """Encrypt plain_token with DPAPI, tied to the current Windows user
    account, and return it base64-encoded so it's safe to store as a JSON
    string. Returns "" for an empty/falsy input. Raises RuntimeError if
    DPAPI isn't available — callers must have a plaintext fallback for that
    case (see MainWindow._set_wa_token()).
    """
    if not plain_token:
        return ""
    if not _DPAPI_AVAILABLE:
        raise RuntimeError("win32crypt not available — DPAPI protection unsupported on this platform")
    blob = win32crypt.CryptProtectData(
        plain_token.encode("utf-8"), _DESCRIPTION, _ENTROPY, None, None, 0
    )
    return base64.b64encode(blob).decode("ascii")


def unprotect_token(protected_b64: str) -> str:
    """Reverse protect_token(). Never raises — returns "" if the blob is
    missing, corrupted, or was protected under a different Windows user
    account/machine (e.g. settings.json copied elsewhere). Callers treat
    that exactly like "no token saved", which safely falls back to showing
    the pairing dialog again instead of crashing.
    """
    if not protected_b64 or not _DPAPI_AVAILABLE:
        return ""
    try:
        blob = base64.b64decode(protected_b64)
        _, plain = win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, 0)
        return plain.decode("utf-8")
    except Exception as e:
        logging.warning("[token_vault] Failed to unprotect stored token: %s", e)
        return ""
