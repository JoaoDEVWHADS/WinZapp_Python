"""Tests for MainWindow._is_bad_contact_name().

Regression coverage: contacts started showing up as "Unknown User" in the
chat list — WhatsApp's newer username feature apparently uses that exact
placeholder for a contact it can't fully resolve. _is_bad_contact_name()
only exact-matched the bare "unknown", so "Unknown User" (and any similar
"Unknown ..." variant) slipped through as if it were a real saved name.
"""

import pytest

from main import MainWindow

is_bad = MainWindow._is_bad_contact_name


class TestKnownBadNames:
    @pytest.mark.parametrize("name", [
        "", None, "5511999999999", "+55 11 99999-9999",
        "Contato sem nome", "unnamed", "Unnamed Contact",
        "no name", "desconhecido",
    ])
    def test_already_recognized_bad_names(self, name):
        assert is_bad(name) is True


class TestUnknownUserVariants:
    """The exact regression: WhatsApp's username-feature placeholder."""

    @pytest.mark.parametrize("name", [
        "Unknown User",
        "unknown user",
        "Unknown Contact",
        "UNKNOWN",
        "unknown",
    ])
    def test_unknown_variants_are_bad(self, name):
        assert is_bad(name) is True


class TestRealNamesAreKept:
    @pytest.mark.parametrize("name", [
        "Ana Silva", "Bruno", "Maria da Cunha", "José Carlos",
    ])
    def test_real_names_are_not_bad(self, name):
        assert is_bad(name) is False
