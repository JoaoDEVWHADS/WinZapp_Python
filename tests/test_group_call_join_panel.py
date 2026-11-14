"""Call discovery updates only the current visible group and never steals focus."""
from types import SimpleNamespace

import pytest

from ui.conversation_panel.group_calls import GroupCallJoinPanelMixin
from ui.conversation_panel.composer import ComposerMixin

GROUP = "120363000001@g.us"
CALL = {"id": "call-1", "groupJid": GROUP, "isVideo": False}
PERSON = "5511999999999@s.whatsapp.net"


class Widget:
    def __init__(self):
        self.shown = False
        self.focused = False
        self.focus_count = 0
        self.label = ""
        self.label_changes = 0
        self.layouts = 0

    def HasFocus(self):
        return self.focused

    def IsShown(self):
        return self.shown

    def Show(self, value):
        self.shown = value

    def SetFocus(self):
        self.focus_count += 1

    def SetLabel(self, label):
        self.label = label
        self.label_changes += 1

    def GetLabel(self):
        return self.label

    def Layout(self):
        self.layouts += 1


class Panel(GroupCallJoinPanelMixin):
    _sync_voice_call_button = ComposerMixin._sync_voice_call_button
    _update_call_start_buttons = ComposerMixin._update_call_start_buttons

    def __init__(self):
        self.conversation = {"remoteJid": GROUP}
        self.conversation_name = "Group"
        self._group_call_join_btn = Widget()
        self._voice_call_btn = Widget()
        self._video_call_btn = Widget()
        self._group_call_unavailable_btn = Widget()
        self.message_field = Widget()
        self.conversation_panel = Widget()
        self.conversation_panel.shown = True
        self.visible = True
        self.requests = []
        self.started = []
        self.result = CALL
        self.main_window = SimpleNamespace(
            i18n=SimpleNamespace(t=lambda key: key),
            _post_call_control=self.post,
            _raise_for_call_response=lambda response, action: response,
            _start_call=lambda *args, **kwargs: self.started.append((args, kwargs)),
            _is_self_jid=lambda jid: False,
            _allow_ui_focus_changes=lambda: True,
        )

    # Match wx.Panel's real visibility API. Do not invent a panel method
    # named conversation_in_view: production uses the shared free function.
    def IsShown(self):
        return self.visible

    def post(self, endpoint, payload, **kwargs):
        self.requests.append((endpoint, payload))
        return SimpleNamespace(json=lambda: {"response": self.result})

    def Layout(self):
        pass


@pytest.fixture
def runtime(monkeypatch):
    queued = []
    timers = []

    class Timer:
        def __init__(self, delay, fn):
            self.fn = fn
            self.stopped = False
            timers.append(self)

        def Stop(self):
            self.stopped = True

    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            queued.append(self.target)

    monkeypatch.setattr("ui.conversation_panel.group_calls.wx.CallAfter", lambda fn, *a: fn(*a))
    monkeypatch.setattr("ui.conversation_panel.group_calls.wx.CallLater", Timer)
    monkeypatch.setattr("ui.conversation_panel.group_calls.threading.Thread", Thread)
    return queued, timers


def test_button_tracks_discovery_and_keeps_other_focus(runtime):
    queued, timers = runtime
    panel = Panel()
    panel._watch_group_calls(GROUP)
    assert not panel._group_call_join_btn.shown
    queued.pop(0)()
    assert panel._group_call_join_btn.shown
    assert panel.message_field.focus_count == 0
    panel._show_ongoing_group_call(CALL)
    assert panel._group_call_join_btn.label_changes == 1
    panel.result = None
    timers[-1].fn()
    queued.pop(0)()
    assert not panel._group_call_join_btn.shown
    assert panel.message_field.focus_count == 0


def test_disappearing_focused_button_moves_focus_to_composer(runtime):
    panel = Panel()
    panel._show_ongoing_group_call(CALL)
    panel._group_call_join_btn.focused = True
    panel._show_ongoing_group_call(None)
    assert panel.message_field.focus_count == 1


def test_late_reply_for_previous_chat_is_discarded(runtime):
    queued, timers = runtime
    panel = Panel()
    panel._watch_group_calls(GROUP)
    panel.conversation = {"remoteJid": "1@s.whatsapp.net"}
    panel._watch_group_calls("1@s.whatsapp.net")
    queued.pop(0)()
    assert not panel._group_call_join_btn.shown
    assert not timers


def test_hidden_chat_does_not_poll_and_close_stops_timer(runtime):
    queued, timers = runtime
    panel = Panel()
    panel.visible = False
    panel._watch_group_calls(GROUP)
    assert not queued
    panel._stop_group_call_watch()
    assert timers[-1].stopped
    timers[-1].fn()
    assert not queued


@pytest.mark.parametrize("result", [{}, {**CALL, "groupJid": "other@g.us"}, {**CALL, "isVideo": "false"}])
def test_invalid_replies_hide_the_button(runtime, result):
    queued, _ = runtime
    panel = Panel()
    panel.result = result
    panel._watch_group_calls(GROUP)
    queued.pop(0)()
    assert not panel._group_call_join_btn.shown


def test_click_joins_the_cached_call_instead_of_dialling(runtime):
    panel = Panel()
    panel._show_ongoing_group_call(CALL)
    panel._on_join_ongoing_group_call()
    assert panel.started == [((GROUP, "Group"), {
        "is_group": True, "is_video": False, "join_call_id": "call-1",
    })]
    panel.visible = False
    panel._on_join_ongoing_group_call()
    assert len(panel.started) == 1


def test_reopened_chat_probes_at_once_and_the_old_reply_is_discarded(runtime):
    """Closing the watch frees the probe slot; the old watch's late reply
    neither shows a button nor frees the new watch's slot."""
    queued, timers = runtime
    panel = Panel()
    panel._watch_group_calls(GROUP)
    old_reply = queued.pop(0)
    panel.conversation = dict(panel.conversation)
    panel._watch_group_calls(GROUP)
    assert len(queued) == 1
    new_watch = panel._group_call_watch
    old_reply()
    assert not panel._group_call_join_btn.shown
    assert panel._group_call_probe_inflight is new_watch and not timers
    queued.pop(0)()
    assert panel._group_call_join_btn.shown and len(timers) == 1
    assert panel._group_call_probe_inflight is None


def test_hidden_detail_pane_does_not_poll_even_when_panel_is_shown(runtime):
    queued, _ = runtime
    panel = Panel()
    panel.conversation_panel.shown = False
    panel._watch_group_calls(GROUP)
    assert not queued
    assert not panel.requests


def test_hiding_detail_before_reply_suppresses_button_and_join(runtime):
    queued, _ = runtime
    panel = Panel()
    panel._watch_group_calls(GROUP)
    panel.conversation_panel.shown = False
    queued.pop(0)()
    assert not panel._group_call_join_btn.shown
    panel._show_ongoing_group_call(CALL)
    panel._on_join_ongoing_group_call()
    assert not panel.started


def test_ongoing_call_replaces_start_buttons_and_restores_them_when_it_ends(runtime):
    queued, timers = runtime
    panel = Panel()
    panel._sync_voice_call_button(GROUP)
    assert panel._voice_call_btn.shown and panel._video_call_btn.shown
    queued.pop(0)()
    assert panel._group_call_join_btn.shown
    assert not panel._voice_call_btn.shown
    assert not panel._video_call_btn.shown
    # A late member-count callback must not bring the start buttons back.
    panel._sync_voice_call_button(GROUP)
    assert not panel._voice_call_btn.shown
    panel.result = None
    timers[-1].fn()
    queued.pop(0)()
    assert not panel._group_call_join_btn.shown
    assert panel._voice_call_btn.shown and panel._video_call_btn.shown


def test_join_replaces_large_group_note_until_the_call_ends(runtime):
    panel = Panel()
    panel._group_call_blocked_jid = GROUP
    panel._sync_voice_call_button(GROUP)
    panel._show_ongoing_group_call(CALL)
    assert not panel._group_call_unavailable_btn.shown
    panel._show_ongoing_group_call(None)
    assert panel._group_call_unavailable_btn.shown
    assert not panel._voice_call_btn.shown and not panel._video_call_btn.shown


def test_discovery_moves_only_a_hidden_start_buttons_focus_to_join(runtime):
    panel = Panel()
    panel._voice_call_btn.shown = panel._voice_call_btn.focused = True
    panel._show_ongoing_group_call(CALL)
    assert panel._group_call_join_btn.focus_count == 1


def test_start_buttons_stay_hidden_while_already_connected(runtime):
    panel = Panel()
    panel.main_window._active_voice_call = {"peer_jid": GROUP}
    panel._show_ongoing_group_call(None)
    assert not panel._voice_call_btn.shown and not panel._video_call_btn.shown


def test_an_unchanged_poll_answer_does_not_relayout(runtime):
    panel = Panel()
    panel._show_ongoing_group_call(CALL)
    before = panel.conversation_panel.layouts
    panel._show_ongoing_group_call(dict(CALL))
    assert panel.conversation_panel.layouts == before
    panel._show_ongoing_group_call(None)
    assert panel.conversation_panel.layouts == before + 1


def test_one_to_one_start_buttons_stay_while_a_call_with_that_contact_is_active(runtime):
    """Only the group watch re-syncs the start buttons after a call ends, so a
    one-to-one chat reopened during a call must never lose them."""
    panel = Panel()
    panel.conversation = {"remoteJid": PERSON}
    panel.main_window._active_voice_call = {"call_id": "C1", "peer_jid": PERSON}
    panel._sync_voice_call_button(PERSON)
    assert panel._voice_call_btn.shown and panel._video_call_btn.shown
    panel.main_window._active_voice_call = None  # hang-up: nothing re-syncs
    assert panel._voice_call_btn.shown and panel._video_call_btn.shown


@pytest.mark.parametrize("handler", [ComposerMixin._on_voice_call, ComposerMixin._on_video_call])
def test_call_shortcuts_join_instead_of_placing_another_offer(runtime, handler):
    panel = Panel()
    panel._show_ongoing_group_call(CALL)
    handler(panel)
    assert panel.started == [((GROUP, "Group"), {
        "is_group": True, "is_video": False, "join_call_id": "call-1"})]
