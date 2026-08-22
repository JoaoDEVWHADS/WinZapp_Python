"""Media that WhatsApp Web can no longer produce is a tally, not 106 warnings.

Measured on one live sync: 106 of 1,110 media requests came back
`400 {"status":"error","message":"Message ... not found"}` — the message had
been unloaded from WhatsApp Web's Store, so no amount of retrying can produce
it. The Node side already exhausts a recovery chain (original id, id without
the device-port suffix, cleaned id, loadEarlierMessages, getMessages(100), and
a LID/phone JID resolution) before answering that.

Each one wrote two log lines, so a healthy session buried log.log under 212
warnings nobody can act on — in a file that is truncated at every launch and is
the first thing asked for when something really is wrong.

These tests pin the reporting rule: real failures still shout, this one counts.
"""

import logging

import pytest

from main import (
    _MEDIA_MISSING_LOG_EVERY,
    _report_media_fetch_failure,
    media_not_in_store_count,
    reset_media_not_in_store_count,
)

NOT_FOUND = '{"status":"error","message":"Message false_55@c.us_AC1 not found"}'


@pytest.fixture(autouse=True)
def _fresh_tally():
    reset_media_not_in_store_count()
    yield
    reset_media_not_in_store_count()


class TestOnlyThisFailureIsTallied:
    def test_a_missing_message_is_handled_here(self):
        assert _report_media_fetch_failure("false_55@c.us_AC1", 400, NOT_FOUND)
        assert media_not_in_store_count() == 1

    def test_any_other_400_is_left_to_the_caller_to_warn_about(self):
        """A malformed request or a rejected token must keep shouting."""
        assert not _report_media_fetch_failure(
            "false_55@c.us_AC1", 400, '{"message":"invalid mediaKey"}')
        assert media_not_in_store_count() == 0

    def test_a_server_error_is_left_to_the_caller(self):
        assert not _report_media_fetch_failure("false_55@c.us_AC1", 500, NOT_FOUND)

    def test_an_empty_body_does_not_crash_the_check(self):
        assert not _report_media_fetch_failure("false_55@c.us_AC1", 400, "")
        assert not _report_media_fetch_failure("false_55@c.us_AC1", 400, None)


class TestTheLogStaysReadableWithoutGoingSilent:
    def test_the_first_one_explains_itself(self, caplog):
        with caplog.at_level(logging.WARNING):
            _report_media_fetch_failure("false_55@c.us_AC1", 400, NOT_FOUND)

        assert "no longer holds this message" in caplog.text

    def test_the_next_ones_do_not_each_warn(self, caplog):
        with caplog.at_level(logging.WARNING):
            for index in range(_MEDIA_MISSING_LOG_EVERY - 1):
                _report_media_fetch_failure(f"id-{index}", 400, NOT_FOUND)

        assert caplog.text.count("WARNING") <= 1

    def test_the_running_total_still_surfaces_periodically(self, caplog):
        """A session where everything fails must not look like a quiet one."""
        with caplog.at_level(logging.WARNING):
            for index in range(_MEDIA_MISSING_LOG_EVERY * 2):
                _report_media_fetch_failure(f"id-{index}", 400, NOT_FOUND)

        assert f"{_MEDIA_MISSING_LOG_EVERY} media unavailable" in caplog.text
        assert f"{_MEDIA_MISSING_LOG_EVERY * 2} media unavailable" in caplog.text

    def test_the_live_volume_costs_a_handful_of_warnings_not_a_hundred(self, caplog):
        with caplog.at_level(logging.WARNING):
            for index in range(106):
                _report_media_fetch_failure(f"id-{index}", 400, NOT_FOUND)

        assert media_not_in_store_count() == 106
        assert caplog.text.count("WARNING") <= 6
