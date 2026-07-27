"""Tests for core.token_vault — Fernet-based at-rest protection for the
WPPConnect session token, using the same per-install key that already
backs DB payload encryption (secret.key).

DPAPI was tried first but rejected: it ties the encrypted blob to one
Windows user/machine, which would permanently break copying the whole
WinZapp data folder to another device to carry a paired session over — a
deliberately supported use case. Fernet with a key that travels alongside
settings.json in the same folder keeps that portable, which is exactly
what these tests assert: the same (key, protected-value) pair decrypts
correctly regardless of "which machine" it's simulated on, and a
DIFFERENT key (standing in for "settings.json copied without secret.key")
fails safely instead of crashing.
"""

import pytest
from cryptography.fernet import Fernet

from core import token_vault


@pytest.fixture
def key():
    return Fernet.generate_key()


class TestProtectUnprotectRoundTrip:
    def test_round_trips_a_token(self, key):
        token = "abc123:hashvalue-with-slashes_and-dashes"
        protected = token_vault.protect_token(token, key)
        assert protected  # non-empty
        assert protected != token  # actually encrypted, not passed through
        assert token_vault.unprotect_token(protected, key) == token

    def test_empty_token_protects_to_empty_string(self, key):
        assert token_vault.protect_token("", key) == ""

    def test_unicode_token_round_trips(self, key):
        token = "tökén-with-ünïcode:🔒"
        protected = token_vault.protect_token(token, key)
        assert token_vault.unprotect_token(protected, key) == token

    def test_portable_across_a_different_process_with_the_same_key(self, key):
        """Simulates the whole point of switching away from DPAPI: the same
        key value (as if secret.key were copied to another machine) must
        decrypt a value protected "elsewhere", with no dependency on the
        current user/machine identity."""
        protected = token_vault.protect_token("a-real-session-token", key)
        # A fresh, independent call — nothing here ties to "this machine".
        assert token_vault.unprotect_token(protected, bytes(key)) == "a-real-session-token"


class TestUnprotectFailureModes:
    """unprotect_token() must never raise — a bad value or wrong key is
    exactly as safe as "no token saved", which callers already handle
    gracefully by re-showing the pairing dialog."""

    def test_empty_string_returns_empty(self, key):
        assert token_vault.unprotect_token("", key) == ""

    def test_garbage_value_returns_empty(self, key):
        assert token_vault.unprotect_token("not-a-real-fernet-token!!!", key) == ""

    def test_wrong_key_returns_empty(self, key):
        """Settings.json copied WITHOUT its matching secret.key — the
        scenario this module is meant to fail safely on, not crash on."""
        protected = token_vault.protect_token("a-real-token", key)
        other_key = Fernet.generate_key()
        assert token_vault.unprotect_token(protected, other_key) == ""

    def test_tampered_value_returns_empty(self, key):
        protected = token_vault.protect_token("a-real-token", key)
        tampered = protected[:-4] + ("A" if protected[-4] != "A" else "B") + protected[-3:]
        assert token_vault.unprotect_token(tampered, key) == ""

    def test_no_key_returns_empty(self):
        assert token_vault.unprotect_token("something", b"") == ""
