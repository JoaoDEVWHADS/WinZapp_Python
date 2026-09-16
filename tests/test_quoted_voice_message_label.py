"""A reply to a voice message must say "mensagem citada: mensagem de voz".

With Settings > voice messages distinguished from audio files, a normal row
already read "mensagem de voz", but a reply always read "mensagem citada:
áudio". Measured against the stored data: 477 of 493 quoted audio messages
normalised from sync are ``{"type": "ptt"}`` and rendered correctly. The broken
shape is the one WinZapp writes itself: every place that builds a reply (text,
voice, attachments) stores the quoted message's own body as
``contextInfo.quotedMessage`` — ``{"audioMessage": {..., "ptt": True}}``, with
no messageType. is_voice_message() refused to look inside a dict without a
type, and _slim_quoted_message() then saved the body as ``{"audioMessage": {}}``,
dropping the flag for good until a sync replaced the record.
"""

import json
from pathlib import Path

import pytest

from core.utils import _slim_quoted_message, is_voice_message
from ui.conversations import ConversationsPanel

_PT_BR = json.loads(
    (Path(__file__).parents[1] / "client" / "languages" / "pt-BR.json").read_text(encoding="utf-8")
)

VOICE_BODY = {"audioMessage": {"url": "x", "seconds": 7, "ptt": True}}
AUDIO_BODY = {"audioMessage": {"url": "x", "seconds": 7, "mimetype": "audio/mpeg"}}


class _I18n:
    def t(self, key):
        return _PT_BR.get(key, key)


def _panel(mode="voice_message"):
    class _MainWindow:
        i18n = _I18n()
        settings = {"user_interface": {"voice_message_mode": mode}}

    class _Panel:
        _get_quoted_preview = ConversationsPanel._get_quoted_preview
        main_window = _MainWindow()

    return _Panel()


VOICE = _PT_BR["message_type_voice_message"]
AUDIO = _PT_BR["message_type_audio"]


def _cap(label):
    return label[0].upper() + label[1:]


class TestQuotedPreview:
    @pytest.mark.parametrize("quoted, expected", [
        (VOICE_BODY, VOICE),                              # a reply WinZapp built
        (_slim_quoted_message(VOICE_BODY), VOICE),        # the same, once saved
        ({"type": "ptt"}, VOICE),                         # from sync (unchanged)
        (AUDIO_BODY, AUDIO),
        (_slim_quoted_message(AUDIO_BODY), AUDIO),
        ({"type": "audio"}, AUDIO),
    ])
    def test_voice_and_audio_are_told_apart(self, quoted, expected):
        assert _panel()._get_quoted_preview(quoted) == _cap(expected)

    @pytest.mark.parametrize("quoted", [VOICE_BODY, {"type": "ptt"}, AUDIO_BODY])
    def test_the_audio_mode_still_reads_everything_as_audio(self, quoted):
        assert _panel("audio")._get_quoted_preview(quoted) == _cap(AUDIO)


class TestSlimQuotedMessage:
    def test_a_voice_note_keeps_its_flag(self):
        assert _slim_quoted_message(VOICE_BODY) == {"audioMessage": {"ptt": True}}

    def test_an_audio_file_is_unchanged(self):
        assert _slim_quoted_message(AUDIO_BODY) == {"audioMessage": {}}

    def test_slimming_its_own_output_changes_nothing(self):
        once = _slim_quoted_message(VOICE_BODY)
        assert _slim_quoted_message(once) == once

    def test_type_audio_with_an_inner_voice_flag_stays_a_voice_note(self):
        quoted = {"type": "audio", "audioMessage": {"ptt": True}}
        assert _slim_quoted_message(quoted) == {"type": "ptt"}
        assert _panel()._get_quoted_preview(_slim_quoted_message(quoted)) == _cap(VOICE)

    def test_a_plain_type_audio_stays_audio(self):
        assert _slim_quoted_message({"type": "audio"}) == {"type": "audio"}


class TestTheSavedReply:
    def test_a_reply_built_by_winzapp_keeps_the_flag_through_pruning(self):
        """The path the bug actually went through: the reply record WinZapp
        builds (quotedMessage = the quoted message's own body) is pruned before
        it is stored, and the label must survive that."""
        from core.utils import prune_message_record

        record = {
            "key": {"id": "R1", "fromMe": True},
            "messageType": "conversation",
            "message": {"conversation": "respondendo"},
            "contextInfo": {
                "stanzaId": "V1",
                "participant": "5511888888888@s.whatsapp.net",
                "quotedMessage": {"audioMessage": {"url": "x", "seconds": 7, "ptt": True,
                                                   "mediaKey": "K", "waveform": "W"}},
            },
        }

        prune_message_record(record)

        quoted = record["contextInfo"]["quotedMessage"]
        assert is_voice_message(quoted) is True
        assert _panel()._get_quoted_preview(quoted) == _cap(VOICE)


class TestIsVoiceMessageOnABody:
    def test_a_bare_voice_body(self):
        assert is_voice_message(VOICE_BODY) is True

    def test_a_bare_audio_body(self):
        assert is_voice_message(AUDIO_BODY) is False

    def test_a_record_keeps_the_type_guard(self):
        """CLAUDE.md: a stray ptt flag on a photo must never make it a voice
        note. A record always has messageType, so the new body branch cannot
        reach it."""
        photo = {"messageType": "imageMessage", "ptt": False,
                 "message": {"imageMessage": {}, "audioMessage": {"ptt": True}}}
        assert is_voice_message(photo) is False
