"""File > WhatsApp settings has its own shortcut, Ctrl+Shift+comma.

Ctrl+. was the first idea and is the emoji picker's key (messages and status
scopes), so it would have opened the picker inside a conversation. No window is
opened and wx is not imported: the catalog is plain data and the wiring is read
from source, like tests/test_shortcut_table_catalog_coverage.py does for tables.
"""

import re
from pathlib import Path

from core.shortcut_catalog import SHORTCUTS

ROOT = Path(__file__).resolve().parents[1] / "client"
CTRL, SHIFT = 2, 4
COMMA = ord(",")


def _source(path):
    return (ROOT / path).read_text(encoding="utf-8-sig")


def _row(shortcut_id):
    rows = [s for s in SHORTCUTS if s.id == shortcut_id]
    assert len(rows) == 1
    return rows[0]


def test_the_catalog_row_is_ctrl_shift_comma():
    row = _row("main.ID_CTRL_SHIFT_COMMA")
    assert (row.scope, row.command) == ("main", "ID_CTRL_SHIFT_COMMA")
    assert (row.mod, row.key) == (CTRL | SHIFT, COMMA)


def test_settings_keeps_plain_ctrl_comma():
    row = _row("main.ID_CTRL_COMMA")
    assert (row.mod, row.key) == (CTRL, COMMA)


def test_no_other_command_defaults_to_that_chord():
    clashes = [s.id for s in SHORTCUTS
               if (s.mod, s.key) == (CTRL | SHIFT, COMMA) and s.id != "main.ID_CTRL_SHIFT_COMMA"]
    assert clashes == []


def test_ctrl_period_is_still_the_emoji_picker_not_whatsapp_settings():
    period = [s for s in SHORTCUTS if (s.mod, s.key) == (CTRL, ord("."))]
    assert period and all(s.id.endswith("ID_CTRL_PERIOD") for s in period)


def test_the_main_window_table_opens_the_whatsapp_settings():
    source = _source("main_window/shortcuts.py")
    assert "self.ID_CTRL_SHIFT_COMMA = wx.NewIdRef()" in source
    assert re.search(
        r"wx\.ACCEL_CTRL \| wx\.ACCEL_SHIFT, ord\(','\), self\.ID_CTRL_SHIFT_COMMA\)", source)
    assert "self.open_whatsapp_settings, id=self.ID_CTRL_SHIFT_COMMA" in source


def test_the_menu_item_advertises_and_follows_the_binding():
    chrome = _source("main_window/window_chrome.py")
    # Built once and relabelled after a language change: both must carry it.
    assert chrome.count("menu_settings_whatsapp')}\\tCtrl+Shift+,") == 2
    bindings = _source("ui/shortcut_bindings.py")
    assert "'_ID_WA_SETTINGS': 'main.ID_CTRL_SHIFT_COMMA'" in bindings


def test_the_shortcuts_help_lists_it():
    assert 'i18n.t("shortcut_ctrl_shift_comma_label")' in _source("ui/dialogs/shortcuts_dialog.py")
