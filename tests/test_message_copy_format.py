"""Tests for locale-aware copied-message timestamps."""

from datetime import datetime

import pytest

from core.message_copy_format import format_copied_message


@pytest.mark.parametrize(("locale", "pattern"), (
    ("pt-BR", "%d/%m/%Y %H:%M"),
    ("pt-PT", "%d/%m/%Y %H:%M"),
    ("en-US", "%m/%d/%Y %I:%M %p"),
    ("es-ES", "%d/%m/%Y %H:%M"),
    ("pl", "%d.%m.%Y %H:%M"),
))
def test_every_supported_locale_uses_its_own_datetime_pattern(locale, pattern):
    timestamp = datetime(2026, 8, 24, 19, 5).timestamp()

    line = format_copied_message(timestamp, "João", "Olá", pattern)

    assert line == f"{datetime.fromtimestamp(timestamp).strftime(pattern)} - João: Olá"


def test_missing_timestamp_omits_only_the_timestamp_prefix():
    assert format_copied_message(None, "João", "Olá", "%d/%m/%Y %H:%M") == "João: Olá"
