"""Tests for the voice-message/video seek shortcuts and helpers added for
issue #17: Shift+Left/Right (5s), Shift+PageUp/PageDown (1min), Shift+Home/
End (jump to start/end) while the message list has focus.

Also covers the fix for on_audio_slider() seeking the raw decode stream
instead of the Tempo FX control that's actually playing — when Tempo FX is
active (the normal case, needed for the playback-speed feature), a seek
that only moved the underlying decode stream's position "worked" in that
audio eventually reached the new spot, but only once Tempo's own already-
decoded-ahead buffer finished draining first, which is what made audio take
a long time to resume after a slider seek.

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App, so methods are bound onto a plain stub carrying only the attributes
they touch — same approach as the rest of this test suite.
"""

from ui.conversations import ConversationsPanel


class _FakeChannel:
    """Stand-in for a sound_lib FileStream/Tempo control. 100 bytes/second,
    matching real BASS's "position is in bytes" semantics closely enough to
    exercise the conversion math."""

    BYTES_PER_SECOND = 100

    def __init__(self, length_seconds=60, position_seconds=30):
        self._length = length_seconds * self.BYTES_PER_SECOND
        self._position = position_seconds * self.BYTES_PER_SECOND

    def get_length(self):
        return self._length

    def get_position(self):
        return self._position

    def set_position(self, pos):
        self._position = pos

    def seconds_to_bytes(self, seconds):
        return int(seconds * self.BYTES_PER_SECOND)


class _FakeVideoPlayer:
    is_playing = False

    def __init__(self, length_seconds=60, position_seconds=30):
        self._ctrl = _FakeChannel(length_seconds, position_seconds)

    def get_length(self):
        return self._ctrl.get_length()

    def get_position(self):
        return self._ctrl.get_position()

    def set_position(self, pos):
        self._ctrl.set_position(pos)

    def seconds_to_bytes(self, seconds):
        return self._ctrl.seconds_to_bytes(seconds)


class _Stub:
    on_audio_slider = ConversationsPanel.on_audio_slider
    seek_active_playback_by = ConversationsPanel.seek_active_playback_by
    seek_active_playback_to_edge = ConversationsPanel.seek_active_playback_to_edge
    _on_messages_list_key_down = ConversationsPanel._on_messages_list_key_down

    def __init__(self):
        self._current_video_msg_id = None
        self._video_player = _FakeVideoPlayer()
        self._audio_stream = None
        self._audio_tempo_ctrl = None
        self.audio_slider = type("Slider", (), {"GetValue": lambda self=None: 500})()
        # Attributes _on_messages_list_key_down reads before reaching the
        # Shift-seek branch — irrelevant to these tests but must exist.
        self.messages_list = type("List", (), {
            "GetFocusedItem": lambda self=None: -1,
            "GetItemCount": lambda self=None: 0,
        })()
        self._is_loading_more = False
        self._messages_offset = 0
        self.main_window = type("MW", (), {"settings": {}})()

    def _load_older_messages(self):
        pass

    def _load_more_messages(self):
        pass


class _FakeKeyEvent:
    def __init__(self, key_code, shift_down=True, ctrl_down=False):
        self._key_code = key_code
        self._shift_down = shift_down
        self._ctrl_down = ctrl_down
        self.skipped = False

    def GetKeyCode(self):
        return self._key_code

    def ShiftDown(self):
        return self._shift_down

    def ControlDown(self):
        return self._ctrl_down

    def Skip(self):
        self.skipped = True


class TestSeekActivePlaybackByUsesTheTempoControl:
    def test_seeks_the_tempo_control_when_active_not_the_raw_decode_stream(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        tempo = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = tempo

        assert stub.seek_active_playback_by(5) is True

        assert tempo.get_position() == 35 * _FakeChannel.BYTES_PER_SECOND
        # The raw decode stream underneath must be left alone by this call —
        # only the control that's actually playing gets seeked.
        assert stub._audio_stream.get_position() == 30 * _FakeChannel.BYTES_PER_SECOND

    def test_falls_back_to_the_raw_stream_when_tempo_fx_is_unavailable(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = None

        assert stub.seek_active_playback_by(-5) is True
        assert stub._audio_stream.get_position() == 25 * _FakeChannel.BYTES_PER_SECOND

    def test_clamps_to_zero_when_seeking_before_the_start(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=3)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=3)

        stub.seek_active_playback_by(-60)

        assert stub._audio_tempo_ctrl.get_position() == 0

    def test_clamps_to_the_end_when_seeking_past_it(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=58)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=58)

        stub.seek_active_playback_by(60)

        assert stub._audio_tempo_ctrl.get_position() == 60 * _FakeChannel.BYTES_PER_SECOND

    def test_returns_false_when_nothing_is_playing(self):
        stub = _Stub()
        assert stub.seek_active_playback_by(5) is False

    def test_seeks_the_video_player_when_a_video_is_playing(self):
        stub = _Stub()
        stub._current_video_msg_id = "abc"
        stub._video_player = _FakeVideoPlayer(length_seconds=60, position_seconds=10)
        stub._video_player.is_playing = True

        stub.seek_active_playback_by(5)

        assert stub._video_player.get_position() == 15 * _FakeChannel.BYTES_PER_SECOND


class TestSeekActivePlaybackToEdge:
    def test_jumps_to_the_start(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        assert stub.seek_active_playback_to_edge(to_end=False) is True
        assert stub._audio_tempo_ctrl.get_position() == 0

    def test_jumps_to_the_end(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        assert stub.seek_active_playback_to_edge(to_end=True) is True
        assert stub._audio_tempo_ctrl.get_position() == 60 * _FakeChannel.BYTES_PER_SECOND


class TestOnAudioSliderSeeksTheTempoControl:
    def test_slider_seek_moves_the_tempo_control_not_the_raw_stream(self):
        """Regression: on_audio_slider() used to call set_position() on the
        raw decode stream, which only became audible once Tempo's internal
        lookahead buffer drained on its own."""
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=100, position_seconds=0)
        tempo = _FakeChannel(length_seconds=100, position_seconds=0)
        stub._audio_tempo_ctrl = tempo
        stub.audio_slider = type("Slider", (), {"GetValue": lambda self=None: 500})()  # 50%

        stub.on_audio_slider(event=None)

        assert tempo.get_position() == 50 * _FakeChannel.BYTES_PER_SECOND
        assert stub._audio_stream.get_position() == 0


class TestMessageListShiftShortcutsDispatchToSeek:
    def test_shift_left_seeks_back_5_seconds_and_consumes_the_event(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        import wx
        event = _FakeKeyEvent(wx.WXK_LEFT, shift_down=True)

        stub._on_messages_list_key_down(event)

        assert stub._audio_tempo_ctrl.get_position() == 25 * _FakeChannel.BYTES_PER_SECOND
        assert not event.skipped

    def test_shift_right_seeks_forward_5_seconds(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        import wx
        stub._on_messages_list_key_down(_FakeKeyEvent(wx.WXK_RIGHT, shift_down=True))
        assert stub._audio_tempo_ctrl.get_position() == 35 * _FakeChannel.BYTES_PER_SECOND

    def test_shift_pageup_seeks_back_one_minute(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=300, position_seconds=120)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=300, position_seconds=120)
        import wx
        stub._on_messages_list_key_down(_FakeKeyEvent(wx.WXK_PAGEUP, shift_down=True))
        assert stub._audio_tempo_ctrl.get_position() == 60 * _FakeChannel.BYTES_PER_SECOND

    def test_shift_pagedown_seeks_forward_one_minute(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=300, position_seconds=120)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=300, position_seconds=120)
        import wx
        stub._on_messages_list_key_down(_FakeKeyEvent(wx.WXK_PAGEDOWN, shift_down=True))
        assert stub._audio_tempo_ctrl.get_position() == 180 * _FakeChannel.BYTES_PER_SECOND

    def test_shift_home_jumps_to_the_start(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        import wx
        stub._on_messages_list_key_down(_FakeKeyEvent(wx.WXK_HOME, shift_down=True))
        assert stub._audio_tempo_ctrl.get_position() == 0

    def test_shift_end_jumps_to_the_end(self):
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        import wx
        stub._on_messages_list_key_down(_FakeKeyEvent(wx.WXK_END, shift_down=True))
        assert stub._audio_tempo_ctrl.get_position() == 60 * _FakeChannel.BYTES_PER_SECOND

    def test_plain_home_without_shift_is_not_intercepted(self):
        """Home (no Shift) already has its own meaning here (load older
        history when at the top) — must fall through, not be consumed."""
        stub = _Stub()
        stub._audio_stream = _FakeChannel(length_seconds=60, position_seconds=30)
        stub._audio_tempo_ctrl = _FakeChannel(length_seconds=60, position_seconds=30)
        import wx
        event = _FakeKeyEvent(wx.WXK_HOME, shift_down=False)

        stub._on_messages_list_key_down(event)

        # Position untouched — the event went down the normal Home path.
        assert stub._audio_tempo_ctrl.get_position() == 30 * _FakeChannel.BYTES_PER_SECOND
