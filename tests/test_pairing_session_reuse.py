"""Tests for whether a stored WPPConnect token may be reused for a new pairing.

_bg_pairing_flow() persists WA_token as soon as WPPConnect emits a pairing code
— well before the pairing completes. The reuse check used to accept any stored
token for a matching number, which broke the cancel-and-retry flow outright:

  1. "Continuar" → code ABCD1234 appears, WA_token is persisted.
  2. "Cancelar pareamento" → cleanup_pairing_session() calls /close-session and
     WPPConnect drops that token from clientsArray.
  3. "Continuar" again → the stale token still matched, so the flow reused it
     and called /start-session on a session that no longer existed. No code was
     ever emitted; the dialog sat on "Conectando..." for the full 90 s wait.

The same applies when the app is killed mid-pairing, where no cleanup runs at
all. Requiring `paired` — which is only ever set once WhatsApp is genuinely
linked — is what separates "a session worth reusing" from "a token left over
from an attempt that never finished".

Connect is a plain class, so the check is exercised directly.
"""

import pytest

from ui.dialogs.connect import Connect


can_reuse = Connect._can_reuse_existing_session

PHONE = "5511999999999"


def _priv(**overrides):
    """A privateinfo dict for a fully paired account, before overrides."""
    base = {
        "WA_phone_number": PHONE,
        "WA_token": "0000000000000000000000000000dead:$2b$10$abc",
        "paired": True,
    }
    base.update(overrides)
    return base


def test_reuses_a_genuinely_paired_session():
    assert can_reuse(_priv(), PHONE) is True


def test_rejects_a_token_from_a_cancelled_pairing():
    """The reported bug: code shown, cancelled, retried. WA_token is present
    because it was persisted optimistically, but pairing never completed."""
    assert can_reuse(_priv(paired=False), PHONE) is False


def test_rejects_when_paired_key_is_absent_entirely():
    """cleanup_pairing_session() pops the key rather than setting it False."""
    priv = _priv()
    del priv["paired"]
    assert can_reuse(priv, PHONE) is False


def test_rejects_a_different_number():
    assert can_reuse(_priv(), "5521888888888") is False


def test_rejects_when_no_token_is_stored():
    assert can_reuse(_priv(WA_token=""), PHONE) is False


def test_rejects_an_empty_privateinfo():
    assert can_reuse({}, PHONE) is False


def test_rejects_a_missing_privateinfo():
    assert can_reuse(None, PHONE) is False


def test_rejects_an_empty_phone_number():
    """An empty field must never match an empty stored number."""
    assert can_reuse(_priv(WA_phone_number=""), "") is False


@pytest.mark.parametrize("stored,typed", [
    ("+55 11 99999-9999", "5511999999999"),
    ("5511999999999", "+55 (11) 99999-9999"),
    ("+55 11 99999-9999", "+55 11 99999-9999"),
])
def test_number_comparison_ignores_formatting(stored, typed):
    """The stored number keeps whatever formatting the user typed; both sides
    are normalised to digits before comparing."""
    assert can_reuse(_priv(WA_phone_number=stored), typed) is True
