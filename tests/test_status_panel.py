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

from status_panel import StatusPanel, _status_content_label


class _FakeI18n:
    _STRINGS = {
        "status_of": "Status {current} de {total}",
        "photo": "Foto",
        "video": "Vídeo",
        "status_like": "Curtir",
        "status_unlike": "Descurtir",
        "message_type_audio": "Áudio",
        "document": "Documento",
        "sticker": "Figurinha",
        "contact_message": "Contato: {name}",
        "notif_unsupported": "Mensagem não suportada",
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


class _FakeTextCtrl(_FakeWidget):
    """Stands in for _reply_field: a wx.TextCtrl, which _show_current_status()
    and _on_reply_field_text_changed() read via GetValue()."""

    def __init__(self, value=""):
        super().__init__()
        self._value = value

    def GetValue(self):
        return self._value

    def SetValue(self, value):
        self._value = value


class _FakeMainWindow:
    def __init__(self, contact_names=None):
        self.i18n = _FakeI18n()
        self.outputs = []
        self._contact_names = contact_names or {}

    def _resolve_contact_name(self, chat):
        return self._contact_names.get(chat.get("remoteJid", ""))

    def output(self, text, interrupt=False):
        self.outputs.append(text)


class _FakeVideoPlayer:
    def __init__(self):
        self.stop_calls = 0
        self.toggle_pause_calls = 0
        self.is_playing = False
        self.is_paused  = False

    def stop(self):
        self.stop_calls += 1
        self.is_playing = False
        self.is_paused  = False

    def toggle_pause(self):
        self.toggle_pause_calls += 1
        self.is_paused = not self.is_paused


class _Stub:
    _show_current_status         = StatusPanel._show_current_status
    _on_status_contact_selected  = StatusPanel._on_status_contact_selected
    _on_reply_field_text_changed = StatusPanel._on_reply_field_text_changed
    _resolve_name                = StatusPanel._resolve_name
    _status_preview              = StatusPanel._status_preview
    _on_play_pause_video         = StatusPanel._on_play_pause_video
    _update_play_pause_label     = StatusPanel._update_play_pause_label

    def __init__(self, contact_names=None):
        self.main_window = _FakeMainWindow(contact_names=contact_names)
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
        self._reply_field          = _FakeTextCtrl()
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


def _audio_status(from_me=False):
    return {
        "key": {"fromMe": from_me, "id": "s4"},
        "messageType": "audioMessage",
        "message": {"audioMessage": {"mimetype": "audio/ogg; codecs=opus"}},
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

    def test_audio_status_shows_the_play_pause_button(self):
        # Regression: audio statuses had no way to trigger playback at
        # all — the button only ever checked for "videoMessage".
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_audio_status()])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._play_pause_btn.shown is True

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


class TestPlayPauseAcceptsAudioStatuses:
    """_on_play_pause_video() used to bail out for anything but
    "videoMessage" — the download/threading path itself isn't exercised
    here (see TestVideoPlayback / _download_and_play_video), just the
    guard that used to block audio entirely."""

    def test_ignores_a_status_type_with_no_playable_media(self):
        stub = _Stub()
        stub._current_status = _text_status("oi")

        stub._on_play_pause_video(None)

        assert stub._video_player.toggle_pause_calls == 0

    def test_toggles_pause_for_an_already_playing_audio_status(self):
        stub = _Stub()
        stub._current_status = _audio_status()
        stub._video_player.is_playing = True

        stub._on_play_pause_video(None)

        assert stub._video_player.toggle_pause_calls == 1


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
    def test_others_status_shows_reply_field_but_not_the_empty_send_button(self):
        # The reply field itself always shows for someone else's status —
        # only the send button waits for actual text (see
        # TestReplySendButtonFollowsFieldContent below).
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi", from_me=False)])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._reply_field.shown is True
        assert stub._reply_send_btn.shown is False
        assert stub._like_btn.shown is True

    def test_others_status_with_pending_reply_text_shows_the_send_button(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi", from_me=False)])]
        stub._selected_contact_idx = 0
        stub._reply_field.SetValue("valeu!")

        stub._show_current_status()

        assert stub._reply_send_btn.shown is True

    def test_own_status_hides_reply_and_like(self):
        stub = _Stub()
        stub._status_contacts = [_entry("a@s.whatsapp.net", [_text_status("oi", from_me=True)])]
        stub._selected_contact_idx = 0

        stub._show_current_status()

        assert stub._reply_field.shown is False
        assert stub._reply_send_btn.shown is False
        assert stub._like_btn.shown is False


class TestReplySendButtonFollowsFieldContent:
    """The send button only makes sense once there's something to send —
    _on_reply_field_text_changed() (bound to EVT_TEXT) keeps it in sync as
    the user types/clears the reply field."""

    def test_typing_text_shows_the_button(self):
        stub = _Stub()
        stub._reply_field.SetValue("oi")

        stub._on_reply_field_text_changed(None)

        assert stub._reply_send_btn.shown is True

    def test_clearing_the_field_hides_the_button(self):
        stub = _Stub()
        stub._reply_field.SetValue("oi")
        stub._on_reply_field_text_changed(None)
        assert stub._reply_send_btn.shown is True

        stub._reply_field.SetValue("")
        stub._on_reply_field_text_changed(None)

        assert stub._reply_send_btn.shown is False

    def test_whitespace_only_text_does_not_show_the_button(self):
        stub = _Stub()
        stub._reply_field.SetValue("   ")

        stub._on_reply_field_text_changed(None)

        assert stub._reply_send_btn.shown is False


class TestStatusContentLabelHandlesEveryMessageType:
    """Regression: audio/document/sticker/contact statuses used to fall
    through to the raw messageType string itself (literally "audioMessage")
    instead of a translated label — reported live as "Fulano: audioMessage"
    in the Alt+5 status list."""

    i18n = _FakeI18n()

    def test_audio_status_is_translated(self):
        label = _status_content_label("audioMessage", {"audioMessage": {}}, self.i18n)
        assert label == "Áudio"

    def test_document_status_includes_filename(self):
        msg_obj = {"documentMessage": {"fileName": "relatorio.pdf"}}
        label = _status_content_label("documentMessage", msg_obj, self.i18n)
        assert label == "Documento: relatorio.pdf"

    def test_document_status_without_filename(self):
        label = _status_content_label("documentMessage", {"documentMessage": {}}, self.i18n)
        assert label == "Documento"

    def test_sticker_status_is_translated(self):
        label = _status_content_label("stickerMessage", {}, self.i18n)
        assert label == "Figurinha"

    def test_contact_status_is_translated(self):
        msg_obj = {"contactMessage": {"displayName": "Ana"}}
        label = _status_content_label("contactMessage", msg_obj, self.i18n)
        assert label == "Contato: Ana"

    def test_unknown_type_falls_back_to_translated_generic_label(self):
        # Never the raw type string itself.
        label = _status_content_label("someBrandNewWhatsAppType", {}, self.i18n)
        assert label == "Mensagem não suportada"


class TestResolveNamePrefersSavedContactNameOverPushName:
    """Regression: the status list always showed the sender's WhatsApp
    profile name (pushName) even when a different name was saved for them
    in the address book — unlike every chat list/conversation in the app,
    which prefers the saved contact name."""

    def test_prefers_saved_contact_name(self):
        stub = _Stub(contact_names={"5511999999999@s.whatsapp.net": "Apelido Salvo"})

        name = stub._resolve_name("5511999999999@s.whatsapp.net")

        assert name == "Apelido Salvo"

    def test_returns_empty_string_when_unresolved(self):
        # _parse_statuses() does `self._resolve_name(jid) or format_number(jid)`
        # — an empty string (not None) is what lets that fallback kick in.
        stub = _Stub(contact_names={})

        name = stub._resolve_name("5511999999999@s.whatsapp.net")

        assert name == ""

    def test_status_preview_uses_resolved_name_for_a_captioned_photo(self):
        stub = _Stub()
        status = {
            "messageType": "imageMessage",
            "message": {"imageMessage": {"caption": "praia"}},
        }
        preview = stub._status_preview(status, stub.main_window.i18n)
        assert preview == "Foto: praia"
