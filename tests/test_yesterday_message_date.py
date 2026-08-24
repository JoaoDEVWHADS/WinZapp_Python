"""Tests for _format_date()'s "yesterday" label — Settings > Interface do
usuário > "Mostrar mensagens do dia anterior com data omitida (ontem)"
(user_interface.show_yesterday_label, default on).

A message timestamped anywhere on the calendar day before today announces as
"ontem às HH:MM" (still through get_time_format(), so it follows the user's
own time format) instead of the full date/time — unless the setting is off,
which keeps the pre-existing behavior (always the full date).

ConversationsPanel is a wx.Panel and cannot be instantiated without a running
wx.App, so _format_date is exercised against a small stub — same approach as
tests/test_message_status_history.py.
"""

from datetime import datetime, timedelta

import pytest

from ui.conversations import ConversationsPanel


@pytest.fixture(autouse=True)
def _fixed_locale_format(monkeypatch):
    """Pin get_time_format/get_datetime_format to their fallback argument —
    see test_message_status_history.py's identical fixture for why (avoids
    depending on the test runner's actual Windows regional format)."""
    monkeypatch.setattr("ui.conversations.get_time_format", lambda fallback: fallback)
    monkeypatch.setattr("ui.conversations.get_datetime_format", lambda fallback: fallback)


class _FakeI18n:
    _STRINGS = {
        "time_fmt": "%H:%M",
        "datetime_fmt": "%d/%m/%Y %H:%M",
        "yesterday_at": "Ontem às {time}",
    }

    def t(self, key):
        return self._STRINGS[key]


class _FakeMainWindow:
    def __init__(self, show_yesterday_label=True):
        self.i18n = _FakeI18n()
        self.settings = {"user_interface": {"show_yesterday_label": show_yesterday_label}}


def _panel(show_yesterday_label=True):
    p = ConversationsPanel.__new__(ConversationsPanel)
    p.main_window = _FakeMainWindow(show_yesterday_label=show_yesterday_label)
    return p


# A fixed point in "yesterday" (relative to whenever the suite runs) that is
# nowhere near midnight, so the test isn't flaky across a real day boundary.
_YESTERDAY_2228 = (datetime.now() - timedelta(days=1)).replace(
    hour=22, minute=28, second=0, microsecond=0
)


class TestYesterdayLabelEnabled:
    def test_yesterday_evening_announces_as_ontem(self):
        p = _panel(show_yesterday_label=True)
        assert p._format_date(_YESTERDAY_2228.timestamp()) == "Ontem às 22:28"

    def test_yesterday_morning_announces_as_ontem(self):
        p = _panel(show_yesterday_label=True)
        dt = _YESTERDAY_2228.replace(hour=11, minute=56)
        assert p._format_date(dt.timestamp()) == "Ontem às 11:56"

    def test_yesterday_just_before_midnight_still_counts(self):
        """"Any time up to 23:59" — the last minute of yesterday must still
        take the ontem branch, not fall through to the full-date one."""
        p = _panel(show_yesterday_label=True)
        dt = _YESTERDAY_2228.replace(hour=23, minute=59)
        assert p._format_date(dt.timestamp()) == "Ontem às 23:59"

    def test_today_is_unaffected(self):
        p = _panel(show_yesterday_label=True)
        now = datetime.now()
        assert p._format_date(now.timestamp()) == now.strftime("%H:%M")

    def test_two_days_ago_is_unaffected(self):
        p = _panel(show_yesterday_label=True)
        dt = datetime.now() - timedelta(days=2)
        assert p._format_date(dt.timestamp()) == dt.strftime("%d/%m/%Y %H:%M")


class TestYesterdayLabelDisabled:
    def test_yesterday_falls_back_to_the_full_date(self):
        p = _panel(show_yesterday_label=False)
        assert p._format_date(_YESTERDAY_2228.timestamp()) == _YESTERDAY_2228.strftime("%d/%m/%Y %H:%M")

    def test_today_is_still_unaffected(self):
        p = _panel(show_yesterday_label=False)
        now = datetime.now()
        assert p._format_date(now.timestamp()) == now.strftime("%H:%M")


class TestDefaultsToEnabledWhenSettingMissing:
    def test_missing_key_defaults_to_the_ontem_label(self):
        """An existing settings.json predating this feature has no
        show_yesterday_label key at all — must default to on (the newly
        introduced behavior), not silently keep the old full-date format."""
        p = ConversationsPanel.__new__(ConversationsPanel)
        p.main_window = _FakeMainWindow()
        p.main_window.settings = {"user_interface": {}}
        assert p._format_date(_YESTERDAY_2228.timestamp()) == "Ontem às 22:28"
