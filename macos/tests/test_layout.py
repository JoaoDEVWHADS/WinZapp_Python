"""The messages list keeps its height (layout_mac), checked on stubs: no wx
window is created. A zero-height list is dropped by VoiceOver, which is how
the whole messages table vanished after playing or recording a voice
message."""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

from winzapp_mac import layout_mac  # noqa: E402


class _Control:
    def __init__(self, char_height=16):
        self.char_height = char_height
        self.min_size = None

    def GetCharHeight(self):
        return self.char_height

    def SetMinSize(self, size):
        self.min_size = size


class _Window:
    """Records Layout() calls in a log shared by the inner and outer panel."""

    def __init__(self, name, log):
        self.name = name
        self.log = log
        self.on_layout = None

    def Layout(self):
        self.log.append(self.name)
        if self.on_layout:
            self.on_layout()
        return True


def _panel():
    log = []
    panel = _Window("outer", log)
    panel.conversation_panel = _Window("inner", log)
    panel.conversations_list = _Control(18)
    panel._message_list_controls = {"classic": _Control(), "listbox": _Control(20)}
    return panel, log


@pytest.fixture
def call_after(monkeypatch):
    """wx.CallAfter queued here; run() drains it like one event-loop turn."""
    queue = []
    monkeypatch.setattr(layout_mac.wx, "CallAfter", lambda fn, *a: queue.append((fn, a)))

    def run():
        while queue:
            fn, a = queue.pop(0)
            fn(*a)

    run.queue = queue
    return run


def test_minimum_height_uses_the_native_row_height():
    # MacListCtrl's row: text height + 4 px; plus the scroll view's border.
    assert layout_mac.min_list_height(_Control(16)) == 4 * (16 + 4) + 4
    assert layout_mac.min_list_height(_Control(20), rows=2) == 2 * (20 + 4) + 4


def test_messages_lists_and_chats_list_get_the_minimum():
    panel, _log = _panel()
    layout_mac.keep_lists_tall(panel)
    assert panel._message_list_controls["classic"].min_size == (-1, 84)
    assert panel._message_list_controls["listbox"].min_size == (-1, 100)
    assert panel.conversations_list.min_size == (-1, 92)


def test_panel_without_lists_is_left_alone(caplog):
    with caplog.at_level("DEBUG"):
        layout_mac.keep_lists_tall(types.SimpleNamespace())
    assert "no _message_list_controls" in caplog.text
    assert "no conversations_list" in caplog.text


def test_inner_layout_is_synchronous_and_the_outer_one_follows(call_after):
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)
    assert panel.conversation_panel.Layout() is True     # wx's return value kept
    assert log == ["inner"]
    call_after()
    assert log == ["inner", "outer"]


def test_several_inner_layouts_in_one_turn_lay_out_the_outer_panel_once(call_after):
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)
    for _ in range(5):          # what one arrow key in the messages list does
        panel.conversation_panel.Layout()
    assert len(call_after.queue) == 1
    call_after()
    assert log == ["inner"] * 5 + ["outer"]
    panel.conversation_panel.Layout()                     # the next turn schedules again
    call_after()
    assert log == ["inner"] * 5 + ["outer", "inner", "outer"]


def test_outer_layout_reaching_the_inner_one_does_not_loop(call_after):
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)
    panel.on_layout = panel.conversation_panel.Layout
    panel.conversation_panel.Layout()
    call_after()
    assert log == ["inner", "outer", "inner"]
    assert call_after.queue == []


def test_a_failing_outer_layout_does_not_stop_later_ones(call_after):
    panel, log = _panel()
    layout_mac.chain_layout_to_outer(panel)

    def boom():
        raise RuntimeError("wrapped C/C++ object has been deleted")

    panel.on_layout = boom
    assert panel.conversation_panel.Layout() is True
    call_after()
    panel.on_layout = None
    panel.conversation_panel.Layout()
    call_after()
    assert log == ["inner", "outer", "inner", "outer"]


def test_a_panel_without_conversation_panel_is_not_chained(call_after):
    panel = types.SimpleNamespace()
    layout_mac.chain_layout_to_outer(panel)               # logs, does not raise
    assert call_after.queue == []


def test_install_applies_both_after_winzapps_init_ui(monkeypatch, call_after):
    panel, log = _panel()

    class ConversationsPanel:
        def init_UI(self):
            log.append("init_UI")
            return "built"

    conversations = types.SimpleNamespace(ConversationsPanel=ConversationsPanel)
    monkeypatch.setitem(sys.modules, "ui", types.SimpleNamespace(conversations=conversations))
    monkeypatch.setitem(sys.modules, "ui.conversations", conversations)
    layout_mac.install()

    assert ConversationsPanel.init_UI(panel) == "built"
    assert panel._message_list_controls["classic"].min_size == (-1, 84)
    assert panel.conversations_list.min_size == (-1, 92)
    panel.conversation_panel.Layout()
    call_after()
    assert log == ["init_UI", "inner", "outer"]
