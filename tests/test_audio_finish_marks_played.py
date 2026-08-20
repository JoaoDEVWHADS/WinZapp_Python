"""Tests for ConversationsPanel.on_audio_timer()'s "audio reached the end"
branch calling MainWindow.mark_audio_message_played().

Feature: reaching the end of in-app audio playback — the same moment the
playback controls get hidden — must mark a received voice message as
played (locally + a real receipt to WhatsApp, see
tests/test_mark_audio_played.py for that half). Must never fire for a
message that isn't found in the currently-open conversation's message list
(e.g. it scrolled out / the conversation changed underneath playback).

ConversationsPanel is a wx.Panel and can't be instantiated without a
running wx.App, so on_audio_timer() is bound onto a plain stub — same
approach as tests/test_conversation_video_playback.py's _ControlsStub.
"""

from ui.conversations import ConversationsPanel


class _FakeAudioStream:
    def __init__(self, position, length):
        self._position = position
        self._length = length

    def get_position(self):
        return self._position

    def get_length(self):
        return self._length


class _FakeSlider:
    def SetValue(self, value):
        pass

    def Refresh(self):
        pass


class _FakeMainWindow:
    def __init__(self):
        self.mark_played_calls = []
        self.skip_panel_refresh_calls = []

    def mark_audio_message_played(self, msg, skip_panel_refresh=False):
        self.mark_played_calls.append(msg)
        self.skip_panel_refresh_calls.append(skip_panel_refresh)


def _audio_msg(msg_id, from_me=False, ptt=False):
    return {
        "key": {"id": msg_id, "fromMe": from_me},
        "messageType": "audioMessage",
        "message": {"audioMessage": {"ptt": ptt}},
    }


class _Stub:
    on_audio_timer = ConversationsPanel.on_audio_timer
    _next_message_is_chainable_audio = ConversationsPanel._next_message_is_chainable_audio
    _is_separator = ConversationsPanel._is_separator
    _is_voice_message = ConversationsPanel._is_voice_message

    def __init__(self, sorted_messages, current_audio_id, position, length):
        self.main_window = _FakeMainWindow()
        self._sorted_messages = sorted_messages
        self._current_video_msg_id = None
        self._current_audio_id = current_audio_id
        self._audio_stream = _FakeAudioStream(position, length)
        self._audio_tempo_ctrl = None
        self.audio_slider = _FakeSlider()
        self._in_auto_timer_stop = False
        self.conversation = None
        self._audio_conv_jid = ""
        self.stop_audio_calls = 0
        self.hide_audio_controls_calls = 0
        self.auto_chain_calls = []

    def _stop_audio(self):
        self.stop_audio_calls += 1
        self._current_audio_id = None

    def _hide_audio_controls(self):
        self.hide_audio_controls_calls += 1

    def _auto_chain_next_audio(self, finished_id, pending_played_msg_id=None):
        self.auto_chain_calls.append((finished_id, pending_played_msg_id))


class TestAudioFinishMarksPlayed:
    def test_reaching_the_end_marks_the_finished_message_played(self):
        msg = _audio_msg("m1")
        stub = _Stub([msg], current_audio_id="m1", position=1000, length=1000)

        stub.on_audio_timer(None)

        assert stub.main_window.mark_played_calls == [msg]
        assert stub.main_window.skip_panel_refresh_calls == [False]
        assert stub.stop_audio_calls == 1
        assert stub.hide_audio_controls_calls == 1
        assert stub.auto_chain_calls == [("m1", None)]

    def test_still_playing_does_not_mark_anything(self):
        msg = _audio_msg("m1")
        stub = _Stub([msg], current_audio_id="m1", position=500, length=1000)

        stub.on_audio_timer(None)

        assert stub.main_window.mark_played_calls == []
        assert stub.stop_audio_calls == 0

    def test_finished_message_not_in_the_open_conversation_is_skipped_safely(self):
        """The finished id doesn't match anything in _sorted_messages (e.g.
        conversation changed underneath playback) — must not crash, and
        must not call mark_audio_message_played with nothing to mark."""
        stub = _Stub([], current_audio_id="m1", position=1000, length=1000)

        stub.on_audio_timer(None)  # must not raise

        assert stub.main_window.mark_played_calls == []
        assert stub.stop_audio_calls == 1

    def test_own_sent_audio_message_is_still_passed_through(self):
        """The from_me exclusion lives in mark_audio_message_played() itself
        (tests/test_mark_audio_played.py) — on_audio_timer() just calls
        through unconditionally whenever a message is found."""
        msg = _audio_msg("m1", from_me=True)
        stub = _Stub([msg], current_audio_id="m1", position=1000, length=1000)

        stub.on_audio_timer(None)

        assert stub.main_window.mark_played_calls == [msg]
        assert stub.main_window.skip_panel_refresh_calls == [False]


class TestPendingPlayedRefreshHandoffWhenChainingIntoTheNextVoiceNote:
    """Reported live, twice: playing several voice notes back to back, NVDA
    kept announcing the just-finished note's "played" status-icon change
    before it got to announce focus landing on the next one. A first fix
    delayed the refresh by a fixed 300ms timeout — still lost the race in
    practice, because the real gap before the chain moves focus isn't a
    fixed number. on_audio_timer() now hands the refresh off to
    _auto_chain_next_audio() itself instead of guessing a delay: that method
    fires it deterministically right after its own focus move happens (see
    tests/test_audio_chain_auto_focus_setting.py for that half), never on a
    timer that can race it."""

    def test_skips_the_refresh_and_hands_it_to_the_chain_when_chainable(self):
        finished = _audio_msg("m1", ptt=True)
        next_note = _audio_msg("m2", ptt=True)
        stub = _Stub([finished, next_note], current_audio_id="m1", position=1000, length=1000)
        stub.conversation = {"remoteJid": "grupo@g.us"}
        stub._audio_conv_jid = "grupo@g.us"

        stub.on_audio_timer(None)

        assert stub.main_window.skip_panel_refresh_calls == [True]
        assert stub.auto_chain_calls == [("m1", "m1")]

    def test_refreshes_immediately_when_nothing_chainable_follows(self):
        finished = _audio_msg("m1", ptt=True)
        stub = _Stub([finished], current_audio_id="m1", position=1000, length=1000)
        stub.conversation = {"remoteJid": "grupo@g.us"}
        stub._audio_conv_jid = "grupo@g.us"

        stub.on_audio_timer(None)

        assert stub.main_window.skip_panel_refresh_calls == [False]
        assert stub.auto_chain_calls == [("m1", None)]

    def test_refreshes_immediately_for_a_generic_audio_file_not_a_voice_note(self):
        """Sequential chaining/transition sounds only apply to PTT voice
        notes, never to generic attached audio — same restriction
        _auto_chain_next_audio() itself already applies."""
        finished = _audio_msg("m1", ptt=False)
        next_note = _audio_msg("m2", ptt=True)
        stub = _Stub([finished, next_note], current_audio_id="m1", position=1000, length=1000)
        stub.conversation = {"remoteJid": "grupo@g.us"}
        stub._audio_conv_jid = "grupo@g.us"

        stub.on_audio_timer(None)

        assert stub.main_window.skip_panel_refresh_calls == [False]
        assert stub.auto_chain_calls == [("m1", None)]
