"""'Check for Updates…' in the application menu (menubar_mac). Fakes only:
no wx.App, no window."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

from winzapp_mac import menubar_mac  # noqa: E402


class _I18n:
    def __init__(self, text):
        self.text = text

    def t(self, key):
        return self.text if key == "menu_force_update" else key


class _Item:
    def __init__(self, label):
        self.label = label

    def SetItemLabel(self, label):
        self.label = label


class _Menu:
    def __init__(self):
        self.items = [(1, _Item("About WinZapp"))]

    def Insert(self, pos, item_id, label):
        self.items.insert(pos, (item_id, _Item(label)))

    def FindItemById(self, item_id):
        return next((i for k, i in self.items if k == item_id), None)


class _MenuBar:
    def __init__(self):
        self.apple = _Menu()

    def OSXGetAppleMenu(self):
        return self.apple


class _Frame:
    def __init__(self, text="&Check for updates"):
        self.i18n = _I18n(text)
        self.bound, self.forced = [], []
        self.mb = _MenuBar()

    def Bind(self, event, handler, id):
        self.bound.append((id, handler))

    def GetMenuBar(self):
        return self.mb

    def _on_force_update(self, evt):
        self.forced.append(evt)


def test_label_is_the_help_items_words_without_mnemonic_with_ellipsis():
    assert menubar_mac.app_menu_update_label(_I18n("&Check for updates")) == "Check for updates…"
    assert menubar_mac.app_menu_update_label(_I18n("Buscar &atualizações...")) == "Buscar atualizações…"


def test_the_item_goes_right_under_about_and_runs_the_help_items_handler():
    frame = _Frame()
    menubar_mac._add_app_menu_update_item(frame, frame.mb)
    ids = [k for k, _ in frame.mb.apple.items]
    assert ids[0] == 1 and ids[1] == int(frame._mac_app_update_id)
    assert frame.mb.apple.items[1][1].label == "Check for updates…"
    (bound_id, handler), = frame.bound
    assert bound_id == int(frame._mac_app_update_id)
    handler("evt")
    assert frame.forced == ["evt"]


def test_building_the_menu_bar_again_adds_it_once():
    frame = _Frame()
    menubar_mac._add_app_menu_update_item(frame, frame.mb)
    menubar_mac._add_app_menu_update_item(frame, frame.mb)
    assert len(frame.mb.apple.items) == 2 and len(frame.bound) == 1


def test_a_language_change_relabels_it():
    frame = _Frame()
    menubar_mac._add_app_menu_update_item(frame, frame.mb)
    frame.i18n = _I18n("&Buscar atualizações")
    menubar_mac._relabel_app_menu_update_item(frame)
    assert frame.mb.apple.items[1][1].label == "Buscar atualizações…"
