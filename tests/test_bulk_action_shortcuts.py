"""Tests for the dedicated per-action shortcuts of both "Ações em massa"
submenus (ConversationsPanel._on_accel_bulk_* — messages list and chat list).

Until these existed, the only keyboard route to a mass action was Settings >
Interface do usuário > "Substituir atalhos por ações em massa ao selecionar
conversas e mensagens" remapping the single-item shortcuts onto the
selection — so a user who turned that off (precisely to keep acting on the
one focused message/chat while a selection exists) could only reach the mass
actions through the context menu.

What is pinned here:
- each shortcut reaches its own mass handler, and only that one;
- they act on the selection regardless of the "Substituir atalhos..."
  setting, unlike the single-item shortcuts that setting remaps;
- with nothing selected they are inert (the submenu isn't even built then),
  but they say so out loud rather than doing nothing at all — silence reads
  as a broken shortcut to a screen-reader user;
- the message and chat selections gate each other's shortcuts not at all:
  selected messages never enable a chat mass action, and vice versa.

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App, so the methods under test are bound to a small stub carrying only
what they touch — same approach as tests/test_mass_selection.py.
"""

import pytest

from ui.conversations import ConversationsPanel


MESSAGE_ACCELS = {
    "_on_accel_bulk_copy": "_on_mass_copy_messages",
    "_on_accel_bulk_forward": "_on_mass_forward_messages",
    "_on_accel_bulk_star": "_on_mass_star_messages",
    "_on_accel_bulk_pin": "_on_mass_pin_messages",
    "_on_accel_bulk_save": "_on_mass_save_messages",
    "_on_accel_bulk_delete": "_on_mass_delete_messages",
}

CHAT_ACCELS = {
    "_on_accel_bulk_clear_chats": "_on_mass_clear_chats",
    "_on_accel_bulk_delete_chats": "_on_mass_delete_chats",
    "_on_accel_bulk_archive_chats": "_on_mass_archive_chats",
    "_on_accel_bulk_read_chats": "_on_mass_mark_read_chats",
    "_on_accel_bulk_unread_chats": "_on_mass_mark_unread_chats",
}

ALL_ACCELS = {**MESSAGE_ACCELS, **CHAT_ACCELS}

# (accel, handler, which selection enables it, what it announces without one)
MESSAGE_CASES = [
    (a, h, "messages", "bulk_no_message_selection") for a, h in sorted(MESSAGE_ACCELS.items())
]
CHAT_CASES = [
    (a, h, "chats", "bulk_no_chat_selection") for a, h in sorted(CHAT_ACCELS.items())
]
ALL_CASES = MESSAGE_CASES + CHAT_CASES


class _FakeI18n:
    def t(self, key):
        return key  # asserted by key name


class _FakeMainWindow:
    def __init__(self, bulk_shortcuts=True):
        self.i18n = _FakeI18n()
        self.settings = {"user_interface": {"bulk_action_shortcuts": bulk_shortcuts}}
        self.announced = []

    def output(self, text, interrupt=False):
        self.announced.append(text)


class _Panel:
    """Stub carrying exactly what the accelerator shims touch. The mass
    handlers themselves are replaced by recorders — they have their own
    coverage in tests/test_mass_selection.py; what matters here is which one
    each shortcut routes to."""

    _run_bulk_message_action = ConversationsPanel._run_bulk_message_action
    _run_bulk_chat_action = ConversationsPanel._run_bulk_chat_action
    _bulk_shortcuts_enabled = ConversationsPanel._bulk_shortcuts_enabled
    _on_accel_bulk_copy = ConversationsPanel._on_accel_bulk_copy
    _on_accel_bulk_forward = ConversationsPanel._on_accel_bulk_forward
    _on_accel_bulk_star = ConversationsPanel._on_accel_bulk_star
    _on_accel_bulk_pin = ConversationsPanel._on_accel_bulk_pin
    _on_accel_bulk_save = ConversationsPanel._on_accel_bulk_save
    _on_accel_bulk_delete = ConversationsPanel._on_accel_bulk_delete
    _on_accel_bulk_clear_chats = ConversationsPanel._on_accel_bulk_clear_chats
    _on_accel_bulk_delete_chats = ConversationsPanel._on_accel_bulk_delete_chats
    _on_accel_bulk_archive_chats = ConversationsPanel._on_accel_bulk_archive_chats
    _on_accel_bulk_read_chats = ConversationsPanel._on_accel_bulk_read_chats
    _on_accel_bulk_unread_chats = ConversationsPanel._on_accel_bulk_unread_chats

    def __init__(self, messages=(), chats=(), bulk_shortcuts=True):
        self.main_window = _FakeMainWindow(bulk_shortcuts)
        self.selected_messages = set(messages)
        self.selected_chats = set(chats)
        self.called = []
        for _name in ALL_ACCELS.values():
            setattr(self, _name, self._recorder(_name))

    def _recorder(self, name):
        def _record(event):
            self.called.append((name, event))
        return _record


def _selected(kind):
    """A panel whose *kind* selection is non-empty and the other one empty."""
    if kind == "messages":
        return _Panel(messages={"m1", "m2"})
    return _Panel(chats={"a@s.whatsapp.net", "b@s.whatsapp.net"})


class TestEachShortcutReachesItsOwnMassAction:
    @pytest.mark.parametrize("accel,handler,kind,_announce", ALL_CASES)
    def test_routes_to_the_matching_handler(self, accel, handler, kind, _announce):
        panel = _selected(kind)
        event = object()
        getattr(panel, accel)(event)
        assert panel.called == [(handler, event)]
        assert panel.main_window.announced == []

    def test_no_shortcut_reaches_more_than_one_handler(self):
        """Guards against a copy-paste slip in the eleven near-identical
        shims — one wrong handler name here is a chat silently cleared
        instead of archived."""
        routed = []
        for accel, _handler, kind, _announce in ALL_CASES:
            panel = _selected(kind)
            getattr(panel, accel)(None)
            assert len(panel.called) == 1
            routed.append(panel.called[0][0])
        assert sorted(routed) == sorted(ALL_ACCELS.values())

    def test_read_and_unread_are_separate_shortcuts_not_a_toggle(self):
        """Unlike the single-chat Ctrl+Shift+M (which flips depending on the
        focused chat's unread count), the submenu offers "mark selected as
        read" and "as unread" as two entries — so each gets its own key."""
        panel = _Panel(chats={"a@s.whatsapp.net"})
        panel._on_accel_bulk_read_chats(None)
        panel._on_accel_bulk_unread_chats(None)
        assert [name for name, _e in panel.called] == [
            "_on_mass_mark_read_chats", "_on_mass_mark_unread_chats"
        ]


class TestGatingOnTheSelection:
    @pytest.mark.parametrize("accel,_handler,kind,announce", ALL_CASES)
    def test_an_empty_selection_runs_nothing_and_announces_it(
        self, accel, _handler, kind, announce
    ):
        """Mirrors the submenu, which isn't built at all without a selection
        — but announces instead of failing silently."""
        panel = _Panel()
        getattr(panel, accel)(None)
        assert panel.called == []
        assert panel.main_window.announced == [announce]

    @pytest.mark.parametrize("accel,_handler,kind,announce", ALL_CASES)
    def test_the_other_list_selection_does_not_enable_it(
        self, accel, _handler, kind, announce
    ):
        """A chat mass action must stay inert while only messages are
        selected, and the other way round — the two selections are
        independent sets and both survive switching between the lists."""
        other = _Panel(chats={"a@s.whatsapp.net"}) if kind == "messages" else _Panel(messages={"m1"})
        getattr(other, accel)(None)
        assert other.called == []
        assert other.main_window.announced == [announce]

    @pytest.mark.parametrize("accel,handler,kind,_announce", ALL_CASES)
    def test_they_work_with_the_override_setting_off(self, accel, handler, kind, _announce):
        """The whole point: "Substituir atalhos por ações em massa..." off is
        what makes the single-item shortcuts keep acting on one message/chat,
        and these must still reach the selection then."""
        panel = _selected(kind)
        panel.main_window.settings["user_interface"]["bulk_action_shortcuts"] = False
        assert panel._bulk_shortcuts_enabled() is False
        getattr(panel, accel)(None)
        assert [name for name, _e in panel.called] == [handler]

    @pytest.mark.parametrize("accel,handler,kind,_announce", ALL_CASES)
    def test_they_work_with_the_override_setting_on_too(self, accel, handler, kind, _announce):
        panel = _selected(kind)
        getattr(panel, accel)(None)
        assert [name for name, _e in panel.called] == [handler]
