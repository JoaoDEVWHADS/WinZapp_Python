"""Tests for core.token_vault — DPAPI-based at-rest protection for the
WPPConnect session token.

Real round-trips through win32crypt.CryptProtectData/CryptUnprotectData are
only meaningful on Windows with a loaded user profile, so this whole module
is skipped (not failed) wherever DPAPI genuinely isn't available — the
module itself is designed to degrade the same way in production (see
MainWindow._set_wa_token()'s plaintext fallback).
"""

import base64

import pytest

from core import token_vault

pytestmark = pytest.mark.skipif(
    not token_vault.is_available(),
    reason="win32crypt/DPAPI not available on this platform",
)


class TestProtectUnprotectRoundTrip:
    def test_round_trips_a_token(self):
        token = "abc123:hashvalue-with-slashes_and-dashes"
        protected = token_vault.protect_token(token)
        assert protected  # non-empty
        assert protected != token  # actually encrypted, not passed through
        assert token_vault.unprotect_token(protected) == token

    def test_protected_value_is_valid_base64(self):
        protected = token_vault.protect_token("some-token")
        # Must not raise — protect_token() promises a JSON-safe base64 string.
        base64.b64decode(protected)

    def test_empty_token_protects_to_empty_string(self):
        assert token_vault.protect_token("") == ""

    def test_unicode_token_round_trips(self):
        token = "tökén-with-ünïcode:🔒"
        protected = token_vault.protect_token(token)
        assert token_vault.unprotect_token(protected) == token


class TestUnprotectFailureModes:
    """unprotect_token() must never raise — a bad blob is exactly as safe
    as "no token saved", which callers already handle gracefully."""

    def test_empty_string_returns_empty(self):
        assert token_vault.unprotect_token("") == ""

    def test_garbage_base64_returns_empty(self):
        assert token_vault.unprotect_token("not-a-real-blob!!!") == ""

    def test_valid_base64_but_not_a_dpapi_blob_returns_empty(self):
        garbage = base64.b64encode(b"just some random bytes, not DPAPI").decode()
        assert token_vault.unprotect_token(garbage) == ""

    def test_tampered_blob_returns_empty(self):
        protected = token_vault.protect_token("a-real-token")
        raw = bytearray(base64.b64decode(protected))
        raw[-1] ^= 0xFF  # flip the last byte
        tampered = base64.b64encode(bytes(raw)).decode()
        assert token_vault.unprotect_token(tampered) == ""
