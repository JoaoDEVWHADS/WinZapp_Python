"""Numbered chats and optional zero-key workaround without opening wx windows."""

from types import SimpleNamespace

import wx

from core.quick_chats import slots_from_settings
from core.keyboard_shortcuts import binding_for
from core.shortcut_catalog import SHORTCUTS
from main_window.quick_chats import QuickChatsMixin
from main_window.window_chrome import WindowChromeMixin
from main_window.win32_helpers import BOOKMARK_ZERO_HOTKEY_ID


class Event:
    def __init__(self, mod, key):
        self.mod, self.key, self.skipped = mod, key, False

    def GetModifiers(self):
        return self.mod

    def GetKeyCode(self):
        return self.key

    def Skip(self):
        self.skipped = True


class ChatPanel:
    def __init__(self, app):
        self.app = app
        self.layouts = []

    def show_chat_panel(self, origin, *, focus):
        self.layouts.append((origin, focus))

    def navigate_to_conversation(self, chat, *, origin):
        self.app.opened.append((chat["remoteJid"], origin))

    def Show(self):
        self.layouts.append("show detail host")


class App(QuickChatsMixin, WindowChromeMixin):
    def __init__(self):
        self.settings = {"quick_chats": {}}
        self.i18n = SimpleNamespace(t=lambda key: {
            "quick_chat_no_focus": "Focus a chat",
            "quick_chat_protected": "Protected chat",
            "quick_chat_assigned": "Slot {digit}: {name}",
            "quick_chat_empty": "Empty {digit}",
            "quick_chat_unavailable": "Unavailable {digit}",
        }.get(key, key))
        self.chats = {"person@s.whatsapp.net": {"remoteJid": "person@s.whatsapp.net", "name": "Pat"}}
        self.focused_chat = None
        self.spoken = []
        self.opened = []
        self.conversations_panel = ChatPanel(self)
        self.saves = 0
        self.locked = False
        self._bookmark_zero_hotkey_bound = True
        self._bookmark_zero_hotkey_on = False
        self.registered = []
        self.unregistered = []

    def _quick_chat_under_focus(self):
        return self.focused_chat

    def is_chat_locked(self, jid):
        return self.locked

    def output(self, text, interrupt=False):
        self.spoken.append(text)

    def chat_display_name(self, chat):
        return chat["name"]

    def save_settings(self):
        self.saves += 1

    def get_chat(self, jid):
        return self.chats.get(jid)

    def is_chat_archived(self, jid):
        return False

    def RegisterHotKey(self, ident, modifiers, key):
        self.registered.append((ident, modifiers, key))
        return True

    def UnregisterHotKey(self, ident):
        self.unregistered.append(ident)


def test_slots_are_account_local_and_invalid_values_are_ignored():
    assert slots_from_settings({"quick_chats": {"1": "a@s.whatsapp.net", "2": 5, "10": "bad"}}) == {
        "1": "a@s.whatsapp.net"
    }
    assert slots_from_settings({"quick_chats": []}) == {}


def test_assign_and_open_uses_saved_jid_and_existing_navigation():
    app = App()
    app.focused_chat = app.chats["person@s.whatsapp.net"]
    app._assign_quick_chat(3)
    assert app.settings["quick_chats"] == {"3": "person@s.whatsapp.net"}
    assert app.saves == 1
    assert app.spoken == ["Slot 3: Pat"]
    app._open_quick_chat(3)
    assert app.opened == [("person@s.whatsapp.net", "main")]
    assert app.conversations_panel.layouts == [("main", False)]


def test_empty_or_unavailable_slot_speaks_without_opening():
    app = App()
    app._open_quick_chat(2)
    app.settings["quick_chats"]["2"] = "missing@s.whatsapp.net"
    app._open_quick_chat(2)
    assert app.spoken == ["Empty 2", "Unavailable 2"]
    assert app.opened == []


def test_archived_slot_opens_even_when_its_row_is_filtered_out():
    app = App()
    app.settings["quick_chats"]["7"] = "person@s.whatsapp.net"
    app.is_chat_archived = lambda jid: True
    hidden = []
    app.archived_conversations_panel = SimpleNamespace(Hide=lambda: hidden.append("archive"))
    app.conversations_panel.conversations_label = SimpleNamespace(Hide=lambda: hidden.append("label"))
    app.conversations_panel.conversations_list = SimpleNamespace(Hide=lambda: hidden.append("list"))
    app.content_panel = SimpleNamespace(Layout=lambda: hidden.append("layout"))
    app._open_quick_chat(7)
    assert app.opened == [("person@s.whatsapp.net", "archived")]
    assert hidden == ["archive", "label", "list", "layout"]


def test_no_focused_chat_or_protected_chat_cannot_be_saved():
    app = App()
    app._assign_quick_chat(4)
    app.focused_chat = app.chats["person@s.whatsapp.net"]
    app.locked = True
    app._assign_quick_chat(4)
    assert app.spoken == ["Focus a chat", "Protected chat"]
    assert app.saves == 0


def test_assignment_reads_only_the_focused_chat_or_open_detail(monkeypatch):
    app = App()
    chat = app.chats["person@s.whatsapp.net"]
    listing = SimpleNamespace(GetFocusedItem=lambda: 0)
    detail = SimpleNamespace(IsShown=lambda: True)
    app.conversations_panel.conversations_list = listing
    app.conversations_panel.chats_list = [chat]
    app.conversations_panel.conversation_panel = detail
    app.conversations_panel.conversation = chat

    monkeypatch.setattr(wx.Window, "FindFocus", lambda: listing)
    assert QuickChatsMixin._quick_chat_under_focus(app) is chat

    child = SimpleNamespace(GetParent=lambda: detail)
    monkeypatch.setattr(wx.Window, "FindFocus", lambda: child)
    assert QuickChatsMixin._quick_chat_under_focus(app) is chat

    unrelated = SimpleNamespace(GetParent=lambda: None)
    monkeypatch.setattr(wx.Window, "FindFocus", lambda: unrelated)
    assert QuickChatsMixin._quick_chat_under_focus(app) is None


def test_protected_slot_is_not_opened_or_named():
    app = App()
    app.settings["quick_chats"]["1"] = "person@s.whatsapp.net"
    app.locked = True
    app._open_quick_chat(1)
    assert app.opened == []
    assert app.spoken == ["Unavailable 1"]


def test_both_key_families_dispatch_and_other_keys_fall_through():
    app = App()
    app.focused_chat = app.chats["person@s.whatsapp.net"]
    app._on_quick_chat_char(Event(wx.MOD_CONTROL | wx.MOD_ALT | wx.MOD_SHIFT, wx.WXK_F5))
    app._on_quick_chat_char(Event(wx.MOD_CONTROL | wx.MOD_SHIFT, wx.WXK_F5))
    unrelated = Event(wx.MOD_ALT, ord("5"))
    app._on_quick_chat_char(unrelated)
    assert app.opened == [("person@s.whatsapp.net", "main")]
    assert unrelated.skipped


def test_quick_keys_leave_bookmark_removal_defaults_intact():
    by_id = {s.id: s for s in SHORTCUTS}
    for digit in range(10):
        fkey = wx.WXK_F10 if digit == 0 else wx.WXK_F1 + digit - 1
        assert binding_for(by_id[f"main.quick_chat_open[{digit}]"], {}, lambda key: key) == (6, fkey)
        assert binding_for(by_id[f"main.quick_chat_assign[{digit}]"], {}, lambda key: key) == (7, fkey)
        assert binding_for(by_id[f"messages.ID_BOOKMARK_REMOVE[{digit}]"], {}, lambda key: key) == (6, ord(str(digit)))
        assert binding_for(by_id[f"messages.ID_TEMP_BOOKMARK_REMOVE[{digit}]"], {}, lambda key: key) == (7, ord(str(digit)))


def test_zero_key_is_held_only_while_active_and_opens_slot():
    app = App()
    app.settings["quick_chats"]["0"] = "person@s.whatsapp.net"
    # Unassign the bookmark default before choosing the IME-swallowed chord.
    app.settings["keyboard_shortcuts"] = {
        "messages.ID_BOOKMARK_REMOVE[0]": None,
        "main.quick_chat_open[0]": [6, ord("0")],
    }
    app._set_bookmark_zero_hotkey(True)
    assert app.registered == [(BOOKMARK_ZERO_HOTKEY_ID,
                               wx.MOD_CONTROL | wx.MOD_SHIFT, ord("0"))]
    app._on_bookmark_zero_hotkey(None)
    assert app.opened == [("person@s.whatsapp.net", "main")]
    app._set_bookmark_zero_hotkey(False)
    assert app.unregistered == [BOOKMARK_ZERO_HOTKEY_ID]
