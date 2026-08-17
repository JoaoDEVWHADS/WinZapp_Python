"""Tests for core.utils.format_number().

Regression for GitHub issue #35: shared contacts' phone numbers were shown
using Brazilian DDD/dash formatting ("+55 DD XXXXX-XXXX") even for
non-Brazilian numbers. E.164 country codes are prefix-free, so a genuine
phone number matching "55" really is Brazilian — but a malformed/unusual
digit string (e.g. an id that isn't actually a full phone number) can still
coincidentally start with "55" without being a real Brazilian number.
format_number() used to force the DDD/dash split on it regardless of length,
producing a string that *looked* like a valid Brazilian number. It now only
applies that shape when the local part is a realistic 10 or 11 digits (DDD +
8 or 9-digit number); anything else falls back to the plain "+55 <digits>"
form instead of fabricating a fake area code/dash grouping.
"""

from core.utils import format_number


class TestBrazilianNumbers:
    def test_mobile_9_digit_number(self):
        assert format_number("5511987654321@s.whatsapp.net") == "+55 11 98765-4321"

    def test_landline_8_digit_number(self):
        assert format_number("551187654321@s.whatsapp.net") == "+55 11 8765-4321"

    def test_ddd_only(self):
        assert format_number("5511@s.whatsapp.net") == "+55 11"

    def test_country_code_only(self):
        assert format_number("55@s.whatsapp.net") == "+55"


class TestOtherCountries:
    def test_united_states(self):
        assert format_number("12025551234@s.whatsapp.net") == "+1 2025551234"

    def test_united_kingdom(self):
        assert format_number("447911123456@s.whatsapp.net") == "+44 7911123456"

    def test_portugal(self):
        assert format_number("351912345678@s.whatsapp.net") == "+351 912345678"


class TestMalformedFiftyFivePrefixedNumbers:
    """The core regression: a "55"-prefixed digit string of the WRONG
    length for a real Brazilian number must never be force-shaped into a
    fake "+55 DD XXXXX-XXXX" pattern."""

    def test_too_short_local_part_falls_back_to_generic_format(self):
        result = format_number("559876543@s.whatsapp.net")
        assert result == "+55 9876543"
        # No fabricated DDD/dash grouping.
        assert "-" not in result

    def test_wrong_length_local_part_falls_back_to_generic_format(self):
        result = format_number("55987654321@s.whatsapp.net")
        assert result == "+55 987654321"
        assert "-" not in result


class TestLidAndUnknownIds:
    def test_lid_suffixed_jid_returns_bare_digits(self):
        assert format_number("123456789012345@lid") == "123456789012345"

    def test_long_digit_string_without_lid_suffix_is_treated_as_lid_like(self):
        assert format_number("12345678901234@s.whatsapp.net") == "12345678901234"

    def test_unknown_country_code_falls_back_to_plus_digits(self):
        # No real dial code starts with "0".
        assert format_number("099999999@s.whatsapp.net") == "+099999999"

    def test_empty_input_is_returned_unchanged(self):
        assert format_number("") == ""
