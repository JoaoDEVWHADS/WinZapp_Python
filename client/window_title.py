"""Pure, wx-free window-title helper (client/window_title.py).

Extracted from main.py so the account-aware title logic is unit-testable
without importing the whole wxPython/socketio stack (plan Zad 2.2/4.2).
"""

from __future__ import annotations


def format_window_title(app_name: str, account_name: str, unread: int = 0,
                        is_multi: bool = False) -> str:
    """Build the main-window title, account-aware.

    In multi-account mode the account name is appended so each window is
    distinguishable to the screen reader; a positive unread count is shown in
    parentheses.
    """
    title = app_name
    if is_multi and account_name and account_name != app_name:
        title = f"{app_name} — {account_name}"
    if unread and unread > 0:
        title = f"{title} ({unread})"
    return title
