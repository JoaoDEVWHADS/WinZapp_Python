"""
Secure at-rest storage for the WPPConnect session token (client/core/token_vault.py)
====================================================================================
settings.json is an ordinary file in the per-install data directory with no
special ACLs — any process running as the same Windows user can read it. Until
this module existed, the WPPConnect session token (WA_token) sat in that file
as plain JSON, so anyone who could read settings.json — malware running as the
user, a backup, a support screen-share — had it outright.

Uses the SAME per-install Fernet key that already protects DB message
payloads (secret.key in data_path(), see MainWindow.retrieve_secret_key())
rather than an OS-tied mechanism like Windows DPAPI. DPAPI was tried first,
but it encrypts a blob so it only decrypts under the exact Windows user
account (and machine) that protected it — which would have permanently
broken a deliberately supported case: copying the whole WinZapp data folder
(settings.json AND secret.key together) to another device to carry a paired
session over. Fernet with a key that travels alongside the data in the same
folder keeps that portable: copy the folder, the token still decrypts,
wherever it lands.

This does not, and cannot, defend against a fully compromised machine: an
attacker who can read settings.json can almost always also read secret.key
sitting right next to it in the same folder, and decrypt exactly like this
module does. What it does raise the bar against is the far more common case
of settings.json alone being read, screenshotted, or shared — a backup that
only grabs one file, a support bundle, a screen-share of the settings
folder — without secret.key riding along with it.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken


def protect_token(plain_token: str, key: bytes) -> str:
    """Encrypt plain_token with the per-install Fernet key and return it as
    a string safe to store directly in JSON (Fernet's own output is already
    URL-safe base64). Returns "" for an empty/falsy input.
    """
    if not plain_token:
        return ""
    return Fernet(key).encrypt(plain_token.encode("utf-8")).decode("ascii")


def unprotect_token(protected: str, key: bytes) -> str:
    """Reverse protect_token(). Never raises — returns "" if the value is
    missing, corrupted, or was encrypted under a different key (e.g. a
    settings.json copied without its matching secret.key). Callers treat
    that exactly like "no token saved", which safely falls back to showing
    the pairing dialog again instead of crashing.
    """
    if not protected or not key:
        return ""
    try:
        return Fernet(key).decrypt(protected.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as e:
        logging.warning("[token_vault] Failed to unprotect stored token: %s", e)
        return ""
