"""Tests for the "auto_focus_next_audio" setting gating whether
_auto_chain_next_audio() moves list focus onto the next voice note.

Feature request: some users want sequential voice-note playback (auto-chain)
to keep advancing audio automatically without also moving list focus away
from wherever they left it — a new Settings > Interface checkbox
("Mover o foco automaticamente para o próximo áudio ao reproduzir áudios em
sequência"), defaulting to the pre-existing behavior (checked/True).

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App, so _auto_chain_next_audio() is bound onto a plain stub — same
approach as tests/test_audio_finish_marks_played.py. wx.CallLater is
monkeypatched to run its callback immediately (as the real event loop
eventually would), so the whole two-step chain (play transition sound, then
start the next audio) resolves synchronously within one call.
"""

import pytest

from ui.conversations import ConversationsPanel


class _FakeMessagesList:
    def __init__(self, focused):
        self._focused = focused
        self.focus_calls = []
        self.select_calls = []
        self.ensure_visible_calls = []

    def GetFocusedItem(self):
        return self._focused

    def Focus(self, idx):
        self.focus_calls.append(idx)
        self._focused = idx

    def Select(self, idx, on=True):
        self.select_calls.append((idx, on))

    def EnsureVisible(self, idx):
        self.ensure_visible_calls.append(idx)


class _FakeMainWindow:
    def __init__(self, auto_focus_next_audio=True):
        self.settings = {"user_interface": {"auto_focus_next_audio": auto_focus_next_audio}}
        self.audio_transition_next_sound = None


def _voice_msg(msg_id):
    return {
        "key": {"id": msg_id},
        "messageType": "audioMessage",
        "message": {"audioMessage": {"ptt": True, "seconds": 5}},
    }


class _Stub:
    _auto_chain_next_audio = ConversationsPanel._auto_chain_next_audio
    _cancel_pending_chain_timers = ConversationsPanel._cancel_pending_chain_timers
    _is_separator = ConversationsPanel._is_separator
    _is_voice_message = ConversationsPanel._is_voice_message

    def __init__(self, sorted_messages, focused, auto_focus_next_audio=True):
        finished_jid = "grupo@g.us"
        self.main_window = _FakeMainWindow(auto_focus_next_audio)
        self._sorted_messages = sorted_messages
        self.conversation = {"remoteJid": finished_jid}
        self._audio_conv_jid = finished_jid
        self.messages_list = _FakeMessagesList(focused)
        self._is_in_audio_chain = False
        self._chain_play_timer = None
        self._chain_start_timer = None
        self._chain_end_timer = None
        self.toggle_calls = []

    def _toggle_playback(self, msg_id, duration, msg, file_path, audio_ext):
        self.toggle_calls.append(msg_id)


@pytest.fixture
def call_later_now(monkeypatch):
    """Run wx.CallLater's callback immediately instead of actually waiting —
    same approach as tests/test_refresh_messages_debounce.py."""
    class _Immediate:
        def Stop(self):
            pass

    def _call_later(delay, fn, *a, **kw):
        fn(*a, **kw)
        return _Immediate()

    monkeypatch.setattr("ui.conversations.wx.CallLater", _call_later)
    # _start_audio() (inside the chain) builds a voice_messages/ path via
    # data_path(), which needs an active multi-account context this test
    # never sets up — irrelevant to what's under test here (focus movement).
    monkeypatch.setattr("ui.conversations.data_path", lambda *a, **k: "unused.msv")


class TestAutoFocusNextAudioEnabled:
    def test_default_setting_moves_focus_onto_the_next_voice_note(self, call_later_now):
        msgs = [_voice_msg("m1"), _voice_msg("m2")]
        stub = _Stub(msgs, focused=0, auto_focus_next_audio=True)

        stub._auto_chain_next_audio("m1")

        assert stub.messages_list.focus_calls == [1]
        assert stub.messages_list.select_calls == [(1, True)]
        assert stub.toggle_calls == ["m2"]


class TestAutoFocusNextAudioDisabled:
    def test_disabled_setting_keeps_focus_in_place_but_still_chains_playback(self, call_later_now):
        """The checkbox only controls whether focus follows — audio must
        still auto-advance either way."""
        msgs = [_voice_msg("m1"), _voice_msg("m2")]
        stub = _Stub(msgs, focused=0, auto_focus_next_audio=False)

        stub._auto_chain_next_audio("m1")

        assert stub.messages_list.focus_calls == []
        assert stub.messages_list.select_calls == []
        assert stub.toggle_calls == ["m2"]
