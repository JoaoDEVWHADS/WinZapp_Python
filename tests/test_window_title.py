"""Tests for the pure format_window_title() helper (client/window_title.py)."""

from window_title import format_window_title


def test_single_account_plain():
    assert format_window_title("WinZapp", "WinZapp", 0, is_multi=False) == "WinZapp"


def test_multi_account_appends_name():
    assert format_window_title("WinZapp", "Praca", 0, is_multi=True) == "WinZapp — Praca"


def test_unread_count_shown():
    assert format_window_title("WinZapp", "Praca", 5, is_multi=True) == "WinZapp — Praca (5)"


def test_multi_but_name_equals_app():
    # A name equal to the app name shouldn't double up.
    assert format_window_title("WinZapp", "WinZapp", 0, is_multi=True) == "WinZapp"


def test_single_account_ignores_name():
    assert format_window_title("WinZapp", "Praca", 0, is_multi=False) == "WinZapp"


def test_multi_account_keeps_name_with_unread():
    # Regression guard: _update_title() builds its base title via this helper,
    # so a positive unread count must NOT drop the account name (the earlier
    # bug: the window title lost the profile name on every unread refresh).
    assert format_window_title("WinZapp", "Midzi", 3, is_multi=True) == "WinZapp — Midzi (3)"
