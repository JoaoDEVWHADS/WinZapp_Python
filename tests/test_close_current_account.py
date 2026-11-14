"""Accounts > Close current account (Ctrl+F4).

Ends only this account's process, so an account not in use stops costing the
machine a WhatsApp session, a Node and its memory, while the others keep
running. Reopening it is the existing switch (its item in another account's
Accounts menu, Ctrl+Alt+<n>, Switch account…), which starts a process for an
account that has none.

MainWindow cannot be built without a wx.App, so the real methods run against
a stub. Nothing here opens a window: MessageBox is replaced.
"""

import types

import pytest
import wx

import account_launcher
from main import MainWindow


class _Registry:
    def __init__(self, accounts):
        self._accounts = accounts

    def list(self):
        return list(self._accounts)


class _Stub:
    _close_current_account = MainWindow._close_current_account
    _on_account_hotkey_char = MainWindow._on_account_hotkey_char
    _on_accounts_menu = MainWindow._on_accounts_menu

    def __init__(self, others):
        self.global_dir = "G"
        self.account_id = "me"
        self.account_name = "Trabalho"
        self.registry = _Registry([
            {"id": "me", "state": "paired", "order": 1},
            {"id": "other", "state": "paired", "order": 2},
        ])
        self.i18n = types.SimpleNamespace(t=lambda k: k + ("{name}" if k.endswith("_done") else ""))
        self._others = others
        self._accounts_menu_id_map = {object(): {"close_current": True}}
        self.events = []

    def _other_running_account_ids(self):
        return list(self._others)

    def output(self, text, interrupt=False):
        self.events.append(("speak", text))

    def Hide(self):
        self.events.append(("hide",))

    def real_exit(self):
        self.events.append(("exit",))


@pytest.fixture
def inline(monkeypatch):
    """Run the hand-over worker and its CallAfter inline, in order."""
    class _Thread:
        def __init__(self, target=None, daemon=None, name=None, **kw):
            self.target = target

        def start(self):
            self.target()

    import main_window.window_chrome as chrome
    monkeypatch.setattr(chrome.threading, "Thread", _Thread)
    monkeypatch.setattr(wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))


@pytest.fixture
def switched(monkeypatch):
    calls = []

    def _switch(gd, account_id, frozen=None):
        calls.append((gd, account_id))
        return "activated"
    monkeypatch.setattr(account_launcher, "switch_to_account", _switch)
    return calls


@pytest.fixture
def answer(monkeypatch):
    state = {"reply": wx.NO, "asked": 0, "style": None}

    def _box(message, caption, style, parent=None):
        state["asked"] += 1
        state["style"] = style
        return state["reply"]
    monkeypatch.setattr(wx, "MessageBox", _box)
    return state


class TestWithAnotherAccountRunning:
    def test_hands_focus_over_then_exits_only_this_process(self, inline, switched, answer):
        s = _Stub(others=["other"])

        s._close_current_account()

        assert switched == [("G", "other")]
        assert s.events[-1] == ("exit",)
        assert ("hide",) in s.events
        assert answer["asked"] == 0, "nothing to confirm: WinZapp stays open"

    def test_says_which_account_was_closed(self, inline, switched, answer):
        s = _Stub(others=["other"])
        s._close_current_account()
        assert ("speak", "acc_close_current_doneTrabalho") in s.events

    def test_a_failed_hand_over_still_closes(self, inline, monkeypatch, answer):
        def _boom(*a, **kw):
            raise OSError("pipe")
        monkeypatch.setattr(account_launcher, "switch_to_account", _boom)
        s = _Stub(others=["other"])

        s._close_current_account()

        assert s.events[-1] == ("exit",)

    def test_the_hand_over_runs_off_the_wx_thread(self):
        """An IPC round trip to another process — see
        tests/test_shutdown_paths_off_main_thread.py for what that cost when it
        ran on the main thread."""
        import inspect
        src = inspect.getsource(MainWindow._close_current_account)
        assert src.index("def _hand_over_then_exit") < src.index("switch_to_account(gd, target)")
        assert "threading.Thread(target=_hand_over_then_exit" in src


class TestAsTheOnlyAccountRunning:
    def test_asks_first_with_no_as_the_default(self, inline, switched, answer):
        s = _Stub(others=[])

        s._close_current_account()

        assert answer["asked"] == 1
        assert answer["style"] & wx.NO_DEFAULT
        assert ("exit",) not in s.events
        assert switched == []

    def test_yes_quits(self, inline, switched, answer):
        answer["reply"] = wx.YES
        s = _Stub(others=[])

        s._close_current_account()

        assert s.events == [("exit",)]
        assert switched == []


class TestTheWayIn:
    def _event(self, modifiers, code):
        ev = types.SimpleNamespace(skipped=False)
        ev.GetModifiers = lambda: modifiers
        ev.GetKeyCode = lambda: code
        ev.Skip = lambda: setattr(ev, "skipped", True)
        return ev

    def test_ctrl_f4_closes_and_is_consumed(self):
        s = _Stub(others=["other"])
        closed = []
        s._close_current_account = lambda: closed.append(True)
        ev = self._event(wx.MOD_CONTROL, wx.WXK_F4)

        s._on_account_hotkey_char(ev)

        assert closed == [True]
        assert ev.skipped is False

    def test_ctrl_f4_outside_the_account_system_is_not_ours(self):
        s = _Stub(others=["other"])
        s._accounts_menu_id_map = {}
        closed = []
        s._close_current_account = lambda: closed.append(True)
        ev = self._event(wx.MOD_CONTROL, wx.WXK_F4)

        s._on_account_hotkey_char(ev)

        assert closed == []
        assert ev.skipped is True

    def test_other_f4_combos_pass_through(self):
        s = _Stub(others=["other"])
        closed = []
        s._close_current_account = lambda: closed.append(True)
        for mods in (wx.MOD_NONE, wx.MOD_ALT, wx.MOD_CONTROL | wx.MOD_SHIFT):
            ev = self._event(mods, wx.WXK_F4)
            s._on_account_hotkey_char(ev)
            assert ev.skipped is True
        assert closed == []

    def test_the_menu_item_closes(self):
        s = _Stub(others=["other"])
        closed = []
        s._close_current_account = lambda: closed.append(True)

        s._on_accounts_menu({"close_current": True})

        assert closed == [True]


def test_running_accounts_come_from_the_node_leases_minus_this_one(monkeypatch):
    import node_coord
    seen = {}

    def _leases(gd, is_alive=None):
        seen["gd"] = gd
        return [{"account_id": "me"}, {"account_id": "other"},
                {"account_id": "broken", "_corrupt": True}, {"account_id": ""}]
    monkeypatch.setattr(node_coord, "live_node_leases", _leases)

    class _S:
        _other_running_account_ids = MainWindow._other_running_account_ids
        global_dir = "G"
        account_id = "me"

    assert _S()._other_running_account_ids() == ["other"]
    assert seen["gd"] == "G"
