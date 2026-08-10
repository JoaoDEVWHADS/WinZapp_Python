"""Tests for in-app video-message playback wiring in
ConversationsPanel (client/ui/conversations.py) — audio via BASS, frames
via ffmpeg, see client/core/video_player.py.

Enter on a video message row is the only trigger now (the separate
Play/Pause button that used to sit next to Open/Save As was removed — it
made no sense as a standing UI element and duplicated what Enter should
just do directly). Only the parts that don't require a real ffmpeg
process / running wx.App are exercised here: _play_toggle_video_message()'s
"already playing the SAME video -> just toggle pause" vs. "different video
-> switch to it" branches, and _hide_all_media_controls() always stopping
the player (selection/conversation changes must never leave an orphaned
ffmpeg subprocess or audio channel running in the background).
"""

from ui.conversations import ConversationsPanel


class _FakeVideoPlayer:
    def __init__(self, is_playing=False):
        self.is_playing = is_playing
        self.toggle_pause_calls = 0
        self.stop_calls = 0
        self.load_and_play_calls = []

    def toggle_pause(self):
        self.toggle_pause_calls += 1

    def stop(self):
        self.stop_calls += 1
        self.is_playing = False

    def load_and_play(self, path, speed=1.0):
        self.load_and_play_calls.append((path, speed))
        self.is_playing = True


class _FakeWidget:
    def __init__(self):
        self.shown = False

    def Show(self, show=True):
        self.shown = bool(show)

    def Hide(self):
        self.shown = False


class _FakeMainWindow:
    def output(self, text, interrupt=False):
        pass


class _FakeMessagesList:
    def __init__(self, focused=0):
        self._focused = focused

    def GetFirstSelected(self):
        return self._focused


def _video_msg(mid="v1"):
    return {"key": {"id": mid}, "messageType": "videoMessage", "message": {"videoMessage": {}}}


class _Stub:
    _play_toggle_video_message   = ConversationsPanel._play_toggle_video_message
    _hide_all_media_controls     = ConversationsPanel._hide_all_media_controls
    _update_links_panel          = lambda self, links: None
    _update_mentions_panel       = lambda self, mentions: None

    def __init__(self, sorted_messages, is_playing=False, current_video_msg_id=None):
        self.main_window   = _FakeMainWindow()
        self._sorted_messages = sorted_messages
        self.messages_list = _FakeMessagesList()
        self._video_player = _FakeVideoPlayer(is_playing=is_playing)
        self._current_video_msg_id = current_video_msg_id
        self._media_bitmap         = _FakeWidget()
        self._action_open_btn      = _FakeWidget()
        self._action_save_as_btn   = _FakeWidget()
        self._action_download_btn  = _FakeWidget()
        self._buttons_container    = _FakeWidget()
        self._contact_converse_btn = _FakeWidget()
        self._contact_msg_jid      = None
        self.conversation_panel    = _FakeWidget()
        self.conversation_panel.IsShown = lambda: False
        self.conversation_panel.Layout = lambda: None


class TestPlayToggleTogglesPauseForTheSameVideo:
    def test_toggles_pause_instead_of_restarting(self):
        stub = _Stub([_video_msg("v1")], is_playing=True, current_video_msg_id="v1")

        stub._play_toggle_video_message(_video_msg("v1"))

        assert stub._video_player.toggle_pause_calls == 1
        assert stub._video_player.load_and_play_calls == []

    def test_non_video_message_is_ignored(self):
        stub = _Stub([], is_playing=True, current_video_msg_id="v1")

        stub._play_toggle_video_message({"key": {"id": "x"}, "messageType": "conversation"})

        assert stub._video_player.toggle_pause_calls == 0


class TestHideAllMediaControlsAlwaysStopsTheVideoPlayer:
    def test_stops_the_player(self):
        stub = _Stub([], is_playing=True, current_video_msg_id="v1")

        stub._hide_all_media_controls()

        assert stub._video_player.stop_calls == 1
        assert stub._current_video_msg_id is None

    def test_stops_the_player_even_when_nothing_was_playing(self):
        stub = _Stub([], is_playing=False)

        stub._hide_all_media_controls()

        assert stub._video_player.stop_calls == 1
