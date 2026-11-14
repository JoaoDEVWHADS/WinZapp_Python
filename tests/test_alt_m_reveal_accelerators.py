"""Alt+M is bound on every chat list, in each locale's own letter.

A plain panel switch leaves the open conversation hidden, and the native
mnemonic of the "&Messages" label lives inside that hidden pane, so it cannot
answer. The main, archived and locked lists each bind the label's letter
explicitly, to a handler that reveals the conversation first. The tables are
built here with the real methods against a recording stub: no window.
"""

from unittest.mock import MagicMock

import pytest
import wx

from tests.locales import load_strings, registered_locale_codes
from ui.chat_lock import LockedConversationsPanel
from ui.conversation_panel.accelerators import AcceleratorsMixin
from ui.conversation_panel.archived_panel import ArchivedConversationsPanel


class _I18n:
    def __init__(self, strings):
        self.strings = strings

    def t(self, key):
        return self.strings[key]


class _Stub:
    """Records the accelerator entries and the handler bound to each id."""

    def __init__(self, strings):
        self.main_window = MagicMock()
        self.main_window.i18n = _I18n(strings)
        self.entries = []
        self.bound = {}

    def SetAcceleratorTable(self, table):
        self.entries = table.entries

    def Bind(self, event, handler, id=None):
        self.bound[id] = handler

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = MagicMock()
        setattr(self, name, value)
        return value

    def handler_for_alt(self, letter):
        ids = [i for flags, key, i in self.entries
               if flags == wx.ACCEL_ALT and key == ord(letter)]
        assert len(ids) == 1, f"Alt+{letter} is bound {len(ids)} times"
        return self.bound[ids[0]]


@pytest.fixture(autouse=True)
def _recording_table(monkeypatch):
    class _Table:
        def __init__(self, entries):
            self.entries = list(entries)

    monkeypatch.setattr(wx, "AcceleratorTable", _Table)


def _strings(code):
    return load_strings(code)


def _letter(strings):
    label = strings["messages"]
    return label[label.index("&") + 1].upper()


LOCALES = registered_locale_codes()


@pytest.mark.parametrize("code", LOCALES)
class TestAltMIsBoundOnEveryList:
    def test_main_list_binds_it_to_the_reveal_handler(self, code):
        strings = _strings(code)
        stub = _Stub(strings)
        AcceleratorsMixin.create_accelerator_table(stub)
        assert stub.handler_for_alt(_letter(strings)) is stub._on_list_focus_messages

    def test_archived_list_binds_it_to_the_global_reveal_handler(self, code):
        strings = _strings(code)
        stub = _Stub(strings)
        ArchivedConversationsPanel.create_accelerator_table(stub)
        handler = stub.handler_for_alt(_letter(strings))
        assert handler is stub.main_window._on_global_focus_messages

    def test_locked_list_binds_it_to_the_global_reveal_handler(self, code):
        strings = _strings(code)
        stub = _Stub(strings)
        LockedConversationsPanel._create_accelerator_table(stub)
        handler = stub.handler_for_alt(_letter(strings))
        assert handler is stub.main_window._on_global_focus_messages


def test_the_letter_follows_the_locale():
    assert _letter(_strings("pl")) == "W"
    assert _letter(_strings("pt-BR")) == "M"
