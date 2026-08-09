"""Tests for StatusPanel (client/status_panel.py) — the Alt+5 tab.

Covers two of the reported bugs:

1. Pressing Space on the status list while viewing "status 3 de 5" reset
   the position back to "1 de 5". _on_status_contact_selected() (the
   handler that actually fires from Select()) used to reset
   _current_status_idx to 0 unconditionally on every selection event, even
   when re-selecting the SAME contact the user was already viewing deeper
   into.

2. The video "play/pause" button, and _show_current_status()'s handling of
   switching away from a playing video (must stop it) — verified here via
   button-visibility decisions (is_video -> _play_pause_btn shown) and the
   fake VideoPlayer's stop() call count.

Also covers the new copy-status-text computation (feature request #5): the
text handed to the clipboard must be the actual content — the full text for
a text status, or just the caption (not the "Foto:"/"Vídeo:" label prefix
used in the announced label) for a media status.

StatusPanel is a wx.Panel and cannot be instantiated without a running
wx.App — _show_current_status()/_on_status_contact_selected() are exercised
against a small stub with fake widgets recording Show/Hide/SetLabel calls,
same approach as tests/test_message_bookmarks.py.
"""

import pytest

from status_panel import StatusPanel


class _FakeI18n:
    _STRINGS = {
        "status_of": "Status {current} de {total}",
        "photo": "Foto",
        "video": "Vídeo",
        "status_like": "Curtir",
        "status_unlike": "Descurtir",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


class _FakeWidget:
    def __init__(self):
        self.shown = False
        self.label = ""

    def Show(self, show=True):
        self.shown = bool(show)

    def Hide(self):
        self.shown = False

    def IsShown(self):
        return self.shown

    def SetLabel(self, text):
        self.label = text


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.outputs = []

    def output(self, text, interrupt=False):
        self.outputs.append(text)


class _FakeVideoPlayer:
    def __init__(self):
        self.stop_calls = 0
        self.is_playing = False
        self.is_paused  = False

    def stop(self):
        self.stop_calls += 1
        self.is_playing = False
        self.is_paused  = False


class _Stub:
    _show_current_status         = StatusPanel._show_current_status
    _on_status_contact_selected  = StatusPanel._on_status_contact_selected

    def __init__(self):
        self.main_window = _FakeMainWindow()
        self._status_contacts      = []
        self._selected_contact_idx = -1
        self._current_status_idx   = 0
        self._current_status       = None
        self._current_status_entry = None
        self._current_status_text  = ""
        self._liked_statuses       = {}
        self._video_local_path          = None
        self._video_download_status_id  = None
        self._video_player = _FakeVideoPlayer()

        self._status_content_label = _FakeWidget()
        self._video_bitmap         = _FakeWidget()
        self._play_pause_btn       = _FakeWidget()
        self._save_media_btn       = _FakeWidget()
        self._copy_text_btn        = _FakeWidget()
        self._like_btn              = _FakeWidget()
        self._reply_label          = _FakeWidget()
        self._reply_field          = _FakeWidget()
        self._reply_send_btn       = _FakeWidget()
        self._viewer_panel         = _FakeWidget()

    def Layout(self):
        pass


def _text_status(text, from_me=False):
    return {
        "key": {"fromMe": from_me, "id": "s1"},
        "messageType": "conversation",
        "message": {"conversation": text},
        "messageTimestamp": 1700000000,
    }


def _image_status(caption="", from_me=False):
    return {
        "key": {"fromMe": from_me, "id": "s2"},
        "messageType": "imageMessage",
        "message": {"imageMessage": {"caption": caption, "mimetype": "image/jpeg"}},
        "messageTimestamp": 1700000000,
    }


def _video_status(caption="", from_me=False):
    return {
        "key": {"fromMe": from_me, "id": "s3"},
        "messageType": "videoMessage",
        "message": {"videoMessage": {"caption": caption, "mimetype": "video/mp4"}},
        "messageTimestamp": 1700000000,
    }


def _entry(jid, statuses):
    return {"name": "Ana", "jid": jid, "statuses": statuses}


class TestPositionPreservedOnReselect:
    """Issue: Space on "status 3 de 5" reset the counter to "1 de 5"."""

    def test_reselecting_the_same_contact_keeps_the_current_status(self):
        stub = _Stub()
        statuses = [_text_status("a"), _text_status("b"), _text_status("c"),
                    _text_status("d"), _text_status("e")]
        stub._status_contacts = [_entry("j@s.whatsapp.net", statuses)]
        stub._selected_contact_idx = 0
        stub._current_status_idx   = 2  # "status 3 de 5"

        class _Evt:
            def GetIndex(self):
                return 1  # row 1 = the same already-selected contact (row 0 is My Status)

        stub._on_status_contact_selected(_Evt())

        assert stub._current_status_idx == 2
        assert "3 de 5" in stub._status_content_label.label

    def test_selecting_a_different_contact_resets_to_the_first_status(self):
        stub = _Stub()
        statuses_a = [_text_status("a"), _text_status("b")]
        statuses_b = [_text_status("x")]
        stub._status_contacts = [
            _entry("a@s.whatsapp.net", statuses_a),
            _entry("b@s.whatsapp.net", statuses_b),
        ]
        stub._selected_contact_idx = 0
        stub._current_status_idx   = 1  # viewing "2 de 2" of contact A

        class _Evt:
            def GetIndex(self):
                return 2  # row 2 = contact B (a genuinely different contact)

        stub._on_status_contact_selected(_Evt())

        assert stub._selected_contact_idx == 1
        assert stub._current_status_idx == 0

    def test_selecting_my_status_row_hides_the_viewer(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("a")])]
        stub._selected_contact_idx = 0
        stub._current_status_idx   = 0

        class _Evt:
            def GetIndex(self):
                return 0

        stub._on_status_contact_selected(_Evt())

        assert stub._selected_contact_idx == -1
        assert stub._viewer_panel.shown is False


class TestVideoPlayback:
    def test_video_status_shows_the_play_pause_button(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_video_status()])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._play_pause_btn.shown is True

    def test_text_status_hides_the_play_pause_button(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi")])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._play_pause_btn.shown is False

    def test_switching_status_stops_any_playing_video(self):
        """Reported live: leaving the video's status without stopping it
        first would keep its audio playing / ffmpeg decoding in the
        background — _show_current_status() must always stop() the player
        first, whatever was showing before."""
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_video_status(), _text_status("oi")])]
        stub._selected_contact_idx = 0
        stub._current_status_idx = 0
        stub._show_current_status()
        assert stub._video_player.stop_calls == 1  # stopped once on first show too

        stub._current_status_idx = 1
        stub._show_current_status()

        assert stub._video_player.stop_calls == 2
        assert stub._video_bitmap.shown is False


class TestCopyStatusText:
    def test_text_status_copy_text_is_the_full_text(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("Bom dia!")])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._current_status_text == "Bom dia!"
        assert stub._copy_text_btn.shown is True

    def test_image_status_copy_text_is_just_the_caption(self):
        """Not "Foto: <caption>" — that prefix is only for the announced
        label, the clipboard should get the caption text alone."""
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_image_status(caption="praia")])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._current_status_text == "praia"

    def test_image_status_with_no_caption_hides_the_copy_button(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_image_status(caption="")])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._current_status_text == ""
        assert stub._copy_text_btn.shown is False


class TestReplyAndLikeOnlyForOthersStatuses:
    def test_others_status_shows_reply_and_like(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi", from_me=False)])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._reply_field.shown is True
        assert stub._reply_send_btn.shown is True
        assert stub._like_btn.shown is True

    def test_own_status_hides_reply_and_like(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi", from_me=True)])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._reply_field.shown is False
        assert stub._reply_send_btn.shown is False
        assert stub._like_btn.shown is False
