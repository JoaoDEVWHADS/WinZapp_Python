"""show_chat_panel() against widgets that behave like wxWidgets parents/children.

test_panel_switch_wiring.py records Show/Hide calls; here IsShown() of a child
is its own flag AND every ancestor shown, so a parent's Show(True) brings back
the children that were not hidden explicitly (the message list and composer
inside the detail pane) and a hidden pane can only stay hidden if the code
hid the pane (or its parent) itself. This is the reconstruction of report B
(main chat still visible after Alt+4) with the real show_chat_panel() /
_apply_panel_layout(). Also pinned here: the vault timeout does not move the
user, and the switch log line carries no JID.

No window is created.
"""

import logging

import pytest

from core.conversation_view import ARCHIVED, LOCKED, MAIN
from main import MainWindow
from tests.test_panel_switch_wiring import (
    A, B, _MW, _focus_calls, _open, world,  # noqa: F401 (fixture)
)


def _tree(mw):
    """Give the harness widgets wx parent/child visibility semantics."""
    panel = mw.conversations_panel
    content = mw.content_panel
    parents = {
        panel: content,
        mw.archived_conversations_panel: content,
        mw.locked_conversations_panel: content,
        mw.status_panel: content,
        mw.calls_panel: content,
        panel.conversations_label: panel,
        panel.conversations_list: panel,
        panel.conversation_panel: panel,
        panel.messages_list: panel.conversation_panel,
        panel.message_field: panel.conversation_panel,
    }

    def effective(widget, own):
        parent = parents.get(widget)
        return own() and (parent is None or parent.IsShown())

    for widget, parent in parents.items():
        own = (lambda w=widget: w.panel_shown) if widget is panel else (lambda w=widget: w.shown)
        widget.IsShown = lambda w=widget, o=own: effective(w, o)
    # the real controls exist shown inside their (initially hidden) pane
    return mw


def _from_archived_list(mw, jid):
    """ArchivedConversationsPanel.on_conversation_selected()'s own steps."""
    panel = mw.conversations_panel
    mw.archived_conversations_panel.Hide()
    panel.Show()
    panel.conversations_label.Hide()
    panel.conversations_list.Hide()
    panel.navigate_to_conversation(mw.chats[jid], origin=ARCHIVED)
    mw.queued.clear()


def _on_screen(mw):
    panel = mw.conversations_panel
    return {
        "panel": panel.IsShown(),
        "detail": panel.conversation_panel.IsShown(),
        "messages_list": panel.messages_list.IsShown(),
        "message_field": panel.message_field.IsShown(),
    }


NOTHING_OF_THE_CONVERSATION = {
    "detail": False, "messages_list": False, "message_field": False}


def _only_conversation_parts(shown):
    return {k: v for k, v in shown.items() if k != "panel"}


class TestMainChatAndAlt4:
    def test_main_chat_open_then_alt_4_shows_nothing_of_it(self, world):
        _tree(world)
        _open(world, A, MAIN)
        assert _on_screen(world)["message_field"]  # it really was on screen
        world.on_alt_4(None)
        shown = _on_screen(world)
        assert _only_conversation_parts(shown) == NOTHING_OF_THE_CONVERSATION
        assert not shown["panel"]
        assert world.archived_conversations_panel.IsShown()
        assert _focus_calls(world)[-1] == "archived_list_panel"

    def test_open_main_alt_4_alt_1_lands_on_the_list_without_the_conversation(self, world):
        # Reversed deliberately: coming back used to show it again (the delay).
        _tree(world)
        _open(world, A, MAIN)
        world.on_alt_4(None)
        world.log.clear()
        world.on_alt_1(None)
        shown = _on_screen(world)
        assert shown["panel"]
        assert _only_conversation_parts(shown) == NOTHING_OF_THE_CONVERSATION
        assert world.conversations_panel.conversations_list.IsShown()
        assert not world.archived_conversations_panel.IsShown()
        assert _focus_calls(world) == ["own_list"]
        assert world.conversations_panel.conversation is not None

    def test_alt_m_brings_it_back_in_its_panel(self, world):
        _tree(world)
        _open(world, A, MAIN)
        world.on_alt_4(None)
        world.on_alt_1(None)
        world._on_global_focus_messages(None)
        shown = _on_screen(world)
        assert shown == {"panel": True, "detail": True,
                         "messages_list": True, "message_field": True}
        assert _focus_calls(world)[-1] == "messages_list"

    def test_archived_chat_is_hidden_on_every_switch_and_back_with_alt_m(self, world):
        _tree(world)
        world.on_alt_4(None)
        _from_archived_list(world, A)        # open archived X
        assert _on_screen(world)["detail"]
        world.on_alt_1(None)                 # main list; X hidden
        assert not world.conversations_panel.conversation_panel.IsShown()
        _open(world, B, MAIN)                # open main Y from the main list
        assert world.conversations_panel.conversation_panel.IsShown()

        world.on_alt_4(None)
        panel = world.conversations_panel
        assert _only_conversation_parts(_on_screen(world)) == NOTHING_OF_THE_CONVERSATION
        assert world.archived_conversations_panel.IsShown()
        assert _focus_calls(world)[-1] == "archived_list_panel"
        assert panel.conversation["remoteJid"] == B   # X is gone, Y waits hidden

        world._on_global_focus_messages(None)  # explicit: Y, in the main panel
        assert panel.conversation_panel.IsShown()
        assert panel.conversations_list.IsShown()
        assert not world.archived_conversations_panel.IsShown()

    def test_archived_conversation_comes_back_beneath_the_archived_list_on_alt_2(self, world):
        _tree(world)
        world.on_alt_4(None)
        _from_archived_list(world, A)
        world.on_alt_1(None)
        world._on_global_alt2(None)
        panel = world.conversations_panel
        assert panel.conversation_panel.IsShown()
        assert world.archived_conversations_panel.IsShown()
        assert not panel.conversations_list.IsShown()



class _Vault(_MW):
    lock_chat_vault = MainWindow.lock_chat_vault

    def __init__(self, log):
        super().__init__(log)
        self.locked.add(B)
        self.chat_lock_navigation = True

    def _refresh_chat_lock_navigation(self):
        pass

    def _cancel_chat_lock_timeout(self):
        pass

    def output(self, *a, **k):
        pass


@pytest.fixture
def vault(world, monkeypatch):
    mw = _Vault(world.log)
    mw.started, mw.queued = world.started, world.queued
    panel = mw.conversations_panel

    def _close():  # what _close_conversation_core() leaves behind
        panel.conversation = None
        panel._conversation_origin = None
        panel.conversation_panel.Hide()

    panel.close_conversation_for_panel_switch = _close
    return mw


class TestVaultTimeoutDoesNotMoveTheUser:
    def test_locked_list_on_screen_goes_to_the_main_list(self, vault):
        vault.locked_conversations_panel.Show()
        vault.conversations_panel.Hide()
        vault.lock_chat_vault(silent=True)
        assert vault.conversations_panel.IsShown()
        assert not vault.locked_conversations_panel.IsShown()
        assert _focus_calls(vault)[-1] == "own_list"

    def test_locked_chat_open_in_view_goes_to_the_main_list(self, vault):
        _open(vault, B, LOCKED)
        vault.lock_chat_vault(silent=True)
        panel = vault.conversations_panel
        assert panel.conversation is None
        assert panel.IsShown() and panel.conversations_list.IsShown()
        assert _focus_calls(vault)[-1] == "own_list"

    @pytest.mark.parametrize("where", ["status", "calls", "main", "archived"])
    def test_a_timeout_elsewhere_changes_nothing(self, vault, where):
        panel = vault.conversations_panel
        panel.Hide()
        {"status": vault.status_panel, "calls": vault.calls_panel,
         "archived": vault.archived_conversations_panel}.get(where, panel).Show()
        before = (panel.IsShown(), vault.status_panel.shown,
                  vault.calls_panel.shown, vault.archived_conversations_panel.shown)
        vault.log.clear()
        vault.lock_chat_vault(silent=True)
        assert (panel.IsShown(), vault.status_panel.shown, vault.calls_panel.shown,
                vault.archived_conversations_panel.shown) == before
        assert _focus_calls(vault) == []

    def test_a_locked_chat_open_behind_status_is_closed_without_moving(self, vault):
        _open(vault, B, LOCKED)
        vault.conversations_panel.Hide()
        vault.status_panel.Show()
        vault.lock_chat_vault(silent=True)
        assert vault.conversations_panel.conversation is None
        assert vault.status_panel.shown and not vault.conversations_panel.IsShown()
        assert _focus_calls(vault) == []


class TestSwitchLogLine:
    def test_one_line_per_switch_without_jids(self, world, caplog):
        _open(world, A, MAIN)
        with caplog.at_level(logging.INFO):
            world.on_alt_4(None)
        lines = [r.getMessage() for r in caplog.records if "[panel-switch]" in r.getMessage()]
        assert len(lines) == 1
        line = lines[0]
        assert "shown=archived" in line and "origin=main" in line
        assert "'detail': False" in line and "'list_panel': True" in line
        assert "parked" not in line
        assert "detail=False" in line and "messages_list=" in line
        assert "@" not in line and "s.whatsapp.net" not in line

    def test_a_destroyed_widget_cannot_break_the_switch(self, world):
        def _dead():
            raise RuntimeError("wrapped C/C++ object has been deleted")
        world.conversations_panel.messages_list.IsShown = _dead
        world.on_alt_4(None)
        assert world.archived_conversations_panel.shown
