"""VoiceOver follows the focus move into the message field on a chat open
(vo_focus_mac), checked on stubs: no wx.App, no window, no AppKit call.
The focus move itself is WinZapp's; what is tested is when the layer
re-asserts it to VoiceOver, that it never touches focus the user moved, and
that announcements made meanwhile wait for it instead of being dropped."""

import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(ROOT, "macos"), os.path.join(ROOT, "client")]

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS layer")

from winzapp_mac import vo_focus_mac as V  # noqa: E402


# ------------------------------------------------------------- FocusSettle --

class TestFocusSettle:
    def test_an_open_settles_after_the_settle_time(self):
        s = V.FocusSettle(settle=0.2, max_settle=1.0, quiet=1.5)
        generation, delay = s.arm(10.0)
        assert delay == 0.2 and s.pending
        assert s.settle(generation, 10.2) is True
        assert not s.pending

    def test_a_list_write_pushes_the_reassert_back(self):
        s = V.FocusSettle(settle=0.2, max_settle=1.0)
        s.arm(10.0)
        assert s.delay_after_write(10.15) == pytest.approx(0.2)

    def test_list_writes_never_push_it_past_the_cap(self):
        s = V.FocusSettle(settle=0.2, max_settle=1.0)
        s.arm(10.0)
        assert s.delay_after_write(10.9) == pytest.approx(0.1)
        assert s.delay_after_write(11.5) == 0.0

    def test_a_write_with_no_open_settling_schedules_nothing(self):
        assert V.FocusSettle().delay_after_write(5.0) is None

    def test_a_newer_open_makes_the_older_timer_stale(self):
        s = V.FocusSettle()
        first, _ = s.arm(1.0)
        second, _ = s.arm(1.1)
        assert s.settle(first, 1.3) is False
        assert s.pending
        assert s.settle(second, 1.3) is True

    def test_announcements_are_held_then_queued_then_normal(self):
        s = V.FocusSettle(settle=0.2, quiet=1.5)
        assert s.route(0.0) == V.INTERRUPT
        generation, _ = s.arm(1.0)
        assert s.route(1.1) == V.HOLD
        s.settle(generation, 1.2)
        assert s.route(1.3) == V.QUEUE
        assert s.route(2.8) == V.INTERRUPT

    def test_cancel_speaks_normally_at_once(self):
        s = V.FocusSettle()
        s.arm(1.0)
        s.cancel()
        assert not s.pending
        assert s.route(1.1) == V.INTERRUPT


# ----------------------------------------------------- the wx/Cocoa side --

class _Field:
    def __init__(self, focused=False):
        self.focused = focused

    def HasFocus(self):
        return self.focused


class _Panel:
    def __init__(self, jid="1@s.whatsapp.net", target="message_field"):
        self.conversation = {"remoteJid": jid}
        self.message_field = _Field()
        self.target = target

    def _open_focus_target(self):
        return self.target


class _CallLater:
    def __init__(self, ms, fn, *args):
        self.ms, self.fn, self.args = ms, fn, args
        self.running = True

    def IsRunning(self):
        return self.running

    def Stop(self):
        self.running = False


@pytest.fixture
def env(monkeypatch):
    """Fresh layer state, a settable clock, wx focus and recorded effects."""
    state = types.SimpleNamespace(now=100.0, focus=None, timers=[], posted=[])
    monkeypatch.setattr(V, "_settle", V.FocusSettle(settle=0.2, max_settle=1.0, quiet=1.5))
    monkeypatch.setattr(V, "_timer", None)
    monkeypatch.setattr(V, "_target", None)
    monkeypatch.setattr(V, "_clock", lambda: state.now)

    def call_later(ms, fn, *args):
        timer = _CallLater(ms, fn, *args)
        state.timers.append(timer)
        return timer
    monkeypatch.setattr(V.wx, "CallLater", call_later)
    monkeypatch.setattr(V.wx.Window, "FindFocus", staticmethod(lambda: state.focus))
    monkeypatch.setattr(V, "_post_focus_changed", lambda field: state.posted.append(field))

    def fire_latest():
        live = [t for t in state.timers if t.running]
        timer = live[-1]
        timer.running = False
        timer.fn(*timer.args)
    state.fire_latest = fire_latest
    return state


def test_focus_still_on_the_field_reasserts_once(env):
    panel = _Panel()
    V.begin(panel)
    assert env.timers[-1].ms == 200
    env.focus = panel.message_field
    env.now += 0.2
    env.fire_latest()
    assert env.posted == [panel.message_field]


def test_focus_the_user_moved_is_never_touched(env):
    panel = _Panel()
    V.begin(panel)
    env.focus = object()  # the user tabbed or went back to the chats list
    env.fire_latest()
    assert env.posted == []
    assert V._settle.route(env.now) == V.INTERRUPT


def test_another_chat_opened_in_between_is_not_reasserted_for_the_first(env):
    panel = _Panel(jid="1@s.whatsapp.net")
    V.begin(panel)
    panel.conversation = {"remoteJid": "2@s.whatsapp.net"}
    env.focus = panel.message_field
    env.fire_latest()
    assert env.posted == []


def test_an_unfocused_list_write_restarts_the_timer(env):
    panel = _Panel()
    V.begin(panel)
    first = env.timers[-1]
    env.now += 0.1
    V.note_list_write(_Field(focused=False))
    assert not first.running and env.timers[-1].ms == 200


def test_a_write_to_the_focused_list_is_ignored(env):
    V.begin(_Panel())
    V.note_list_write(_Field(focused=True))
    assert len(env.timers) == 1


def test_list_writes_without_an_open_do_nothing(env):
    V.note_list_write(_Field(focused=False))
    assert env.timers == []


def test_announcements_wait_for_the_reassert_then_queue(env):
    panel = _Panel()
    V.begin(panel)
    spoken = []
    V.route_announcement(lambda queued: spoken.append(("pinned", queued)))
    assert spoken == []
    env.focus = panel.message_field
    env.now += 0.2
    env.fire_latest()
    assert env.posted == [panel.message_field]
    assert spoken == [("pinned", True)]
    V.route_announcement(lambda queued: spoken.append(("next", queued)))
    env.now += 2.0
    V.route_announcement(lambda queued: spoken.append(("later", queued)))
    assert spoken[1:] == [("next", True), ("later", False)]


def test_held_announcements_are_spoken_even_when_the_user_moved(env):
    V.begin(_Panel())
    spoken = []
    V.route_announcement(lambda queued: spoken.append(queued))
    env.focus = None
    env.fire_latest()
    assert spoken == [False]


def test_a_failing_reassert_still_speaks_what_was_held(env, monkeypatch):
    panel = _Panel()
    V.begin(panel)
    spoken = []
    V.route_announcement(lambda queued: spoken.append(queued))

    def boom(field):
        raise RuntimeError("no view")
    monkeypatch.setattr(V, "_post_focus_changed", boom)
    env.focus = panel.message_field
    env.fire_latest()
    assert spoken == [False]


# ---------------------------------------------------------------- install --

def _install_on(monkeypatch, cls):
    module = types.ModuleType("ui.conversations")
    module.ConversationsPanel = cls
    package = types.ModuleType("ui")
    package.conversations = module
    monkeypatch.setitem(sys.modules, "ui", package)
    monkeypatch.setitem(sys.modules, "ui.conversations", module)
    V.install()


def _recording_panel_class(calls):
    class Panel(_Panel):
        def navigate_to_conversation(self, conversation, *, origin=None, take_focus=True):
            calls.append((conversation, origin, take_focus))
            return "opened"
    return Panel


def test_install_arms_after_an_open_that_focuses_the_field(env, monkeypatch):
    calls = []
    cls = _recording_panel_class(calls)
    _install_on(monkeypatch, cls)
    panel = cls()
    assert panel.navigate_to_conversation({"remoteJid": "x"}, origin="main") == "opened"
    assert calls == [({"remoteJid": "x"}, "main", True)]
    assert V._settle.pending


def test_install_leaves_a_background_open_alone(env, monkeypatch):
    cls = _recording_panel_class([])
    _install_on(monkeypatch, cls)
    cls().navigate_to_conversation({}, take_focus=False)
    assert not V._settle.pending


def test_install_leaves_an_open_that_focuses_the_messages_list_alone(env, monkeypatch):
    cls = _recording_panel_class([])
    _install_on(monkeypatch, cls)

    class ListFirst(cls):
        def __init__(self):
            super().__init__(target="messages_list")
    ListFirst().navigate_to_conversation({})
    assert not V._settle.pending


# ----------------------------------------------------------------- speech --

def test_voiceover_announcements_go_through_the_router(monkeypatch):
    from winzapp_mac import speech
    routed = []
    monkeypatch.setattr(speech, "_on_main", lambda fn: fn())
    monkeypatch.setattr(V, "route_announcement", routed.append)
    speech.VoiceOverAnnounce().speak("3 pinned messages")
    assert len(routed) == 1 and callable(routed[0])
    speech.VoiceOverAnnounce().speak("   ")
    assert len(routed) == 1
