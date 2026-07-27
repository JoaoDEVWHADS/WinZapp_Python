"""Tests for MainWindow._get_wa_token()/_set_wa_token() — the migration from
plaintext settings["privateinfo"]["WA_token"] to DPAPI-protected storage
(settings["privateinfo"]["WA_token_protected"], core/token_vault.py).

token_vault's actual DPAPI calls are monkeypatched here with a simple
reversible transform so these tests exercise the migration/fallback LOGIC
(which field wins, when a plaintext copy gets removed, what happens when
protection is unavailable or a blob fails to unprotect) without depending on
a real Windows user profile — that's covered separately by
tests/test_token_vault.py.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the methods under test are exercised as plain functions against a small
stub — same approach as tests/test_sender_names.py.
"""

import pytest

from core import token_vault
from main import MainWindow


class _Stub:
    """Minimal stand-in for MainWindow for token storage/migration."""

    _get_wa_token = MainWindow._get_wa_token
    _set_wa_token = MainWindow._set_wa_token

    def __init__(self, privateinfo=None):
        self.settings = {"privateinfo": dict(privateinfo or {})}
        self.save_calls = 0

    def save_settings(self):
        self.save_calls += 1


@pytest.fixture
def fake_dpapi(monkeypatch):
    """Reversible fake standing in for real DPAPI: protect() just tags the
    string so tests can assert a value really went through it, without
    touching win32crypt at all."""
    monkeypatch.setattr(token_vault, "is_available", lambda: True)
    monkeypatch.setattr(token_vault, "protect_token", lambda t: f"PROTECTED({t})" if t else "")
    monkeypatch.setattr(
        token_vault, "unprotect_token",
        lambda b: b[len("PROTECTED("):-1] if b.startswith("PROTECTED(") else "",
    )
    return monkeypatch


class TestSetWaTokenWithDpapiAvailable:
    def test_stores_protected_form_and_no_plaintext(self, fake_dpapi):
        mw = _Stub()
        mw._set_wa_token("secret-token:hash")
        pi = mw.settings["privateinfo"]
        assert pi["WA_token_protected"] == "PROTECTED(secret-token:hash)"
        assert "WA_token" not in pi
        assert mw.save_calls == 1

    def test_overwrites_a_pre_existing_plaintext_copy(self, fake_dpapi):
        mw = _Stub({"WA_token": "old-plaintext-token"})
        mw._set_wa_token("new-token")
        pi = mw.settings["privateinfo"]
        assert pi["WA_token_protected"] == "PROTECTED(new-token)"
        assert "WA_token" not in pi

    def test_empty_token_clears_both_fields(self, fake_dpapi):
        mw = _Stub({"WA_token_protected": "PROTECTED(x)", "WA_token": "y"})
        mw._set_wa_token("")
        pi = mw.settings["privateinfo"]
        assert "WA_token_protected" not in pi
        assert pi["WA_token"] == ""


class TestSetWaTokenWithoutDpapi:
    def test_falls_back_to_plaintext(self, monkeypatch):
        monkeypatch.setattr(token_vault, "is_available", lambda: False)
        mw = _Stub()
        mw._set_wa_token("secret-token")
        pi = mw.settings["privateinfo"]
        assert pi["WA_token"] == "secret-token"
        assert "WA_token_protected" not in pi


class TestGetWaToken:
    def test_reads_back_a_protected_token(self, fake_dpapi):
        mw = _Stub({"WA_token_protected": "PROTECTED(abc)"})
        assert mw._get_wa_token() == "abc"

    def test_migrates_legacy_plaintext_token_on_first_read(self, fake_dpapi):
        mw = _Stub({"WA_token": "legacy-plaintext-token"})

        token = mw._get_wa_token()

        assert token == "legacy-plaintext-token"
        pi = mw.settings["privateinfo"]
        # Migration happened: protected form now stored, plaintext gone.
        assert pi["WA_token_protected"] == "PROTECTED(legacy-plaintext-token)"
        assert "WA_token" not in pi
        assert mw.save_calls == 1

    def test_no_token_anywhere_returns_empty(self, fake_dpapi):
        mw = _Stub()
        assert mw._get_wa_token() == ""

    def test_corrupted_protected_blob_falls_back_to_legacy_field(self, monkeypatch):
        """A protected value that fails to unprotect (wrong user/machine,
        corruption) must not be treated as a crash or as a real token —
        only as a signal to fall back exactly like unprotect_token() itself
        promises."""
        monkeypatch.setattr(token_vault, "is_available", lambda: True)
        monkeypatch.setattr(token_vault, "unprotect_token", lambda b: "")
        monkeypatch.setattr(token_vault, "protect_token", lambda t: f"PROTECTED({t})" if t else "")
        mw = _Stub({"WA_token_protected": "some-corrupted-blob"})

        assert mw._get_wa_token() == ""

    def test_second_read_after_migration_uses_protected_field_only(self, fake_dpapi):
        mw = _Stub({"WA_token": "legacy-token"})
        mw._get_wa_token()  # triggers migration
        mw.save_calls = 0  # reset to prove the second read doesn't re-save

        token = mw._get_wa_token()

        assert token == "legacy-token"
        assert mw.save_calls == 0
