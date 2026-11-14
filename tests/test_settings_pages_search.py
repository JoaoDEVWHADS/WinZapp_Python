"""Window-free checks for the settings search: folding and entry collection."""

import wx
from ui.dialogs.settings_pages import SearchEntry, _fold, collect_entries


class _Node:
    """Mixin giving a wx control the few calls collect_entries makes."""

    def __init__(self, text="", name="", shown=True, children=()):
        self._text, self._name, self._shown = text, name, shown
        self._children = list(children)

    def IsShown(self):
        return self._shown

    def GetChildren(self):
        return self._children

    def GetLabelText(self):
        return self._text

    def GetName(self):
        return self._name


class _Panel(_Node, wx.Panel):
    pass


class _Static(_Node, wx.StaticText):
    pass


class _Check(_Node, wx.CheckBox):
    pass


class _Choice(_Node, wx.Choice):
    pass


def _collect(*children):
    return collect_entries(_Panel(children=children), 3, "Audio")


def test_fold_ignores_accents_and_case():
    assert _fold("Áudio") == _fold("audio") == "audio"
    assert _fold(None) == ""


def test_search_entry_folds_category_and_label():
    entry = SearchEntry(1, "Áudio", "Volume", None)
    assert entry.folded == "audio volume"


def test_checkbox_uses_its_own_label():
    entries = _collect(_Check("Play in sequence"))
    assert [e.label for e in entries] == ["Play in sequence"]
    assert entries[0].page_index == 3 and entries[0].category == "Audio"


def test_caption_is_attached_to_the_next_captioned_control():
    choice = _Choice()
    entries = _collect(_Static("Output device"), choice)
    assert [(e.label, e.control) for e in entries] == [("Output device", choice)]


def test_caption_is_used_once():
    entries = _collect(_Static("Output device"), _Choice(), _Choice(name="Input device"))
    assert [e.label for e in entries] == ["Output device", "Input device"]


def test_default_wx_names_are_dropped():
    assert _collect(_Choice(name="choice")) == []


def test_hidden_controls_are_skipped():
    entries = _collect(_Check("Hidden", shown=False), _Check("Shown"))
    assert [e.label for e in entries] == ["Shown"]


def test_nested_panels_are_walked():
    inner = _Panel(children=[_Check("Deep option")])
    assert [e.label for e in _collect(inner)] == ["Deep option"]
