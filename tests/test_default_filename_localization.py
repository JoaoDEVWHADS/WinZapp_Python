"""Tests for _resolve_media_filename()'s default (no-original-filename)
names honoring the selected language instead of always being pt-BR.

Reported live: saving media whose messageType carries no original filename
(recorded voice messages especially) always suggested a pt-BR name like
"mensagem_de_voz_20260101_120000.ogg" regardless of the language selected in
Settings — the prefixes were hardcoded Portuguese literals instead of going
through i18n.t().
"""

from ui.conversations import ConversationsPanel


class _I18n:
    TRANSLATIONS = {
        "default_filename_voice_message": "voice_message",
        "default_filename_document": "document",
        "default_filename_image": "image",
        "default_filename_video": "video",
        "default_filename_audio": "audio",
        "default_filename_generic": "file",
    }

    def t(self, key):
        return self.TRANSLATIONS[key]


class _Stub:
    _resolve_media_filename = ConversationsPanel._resolve_media_filename

    def __init__(self):
        self.main_window = type("MainWindowStub", (), {"i18n": _I18n()})()


def _msg(msg_type, inner=None, ptt=False, ts=1_700_000_000):
    payload = dict(inner or {})
    if msg_type == "audioMessage":
        payload["ptt"] = ptt
    return {
        "key": {"id": "ABC123", "fromMe": True},
        "message": {msg_type: payload},
        "messageType": msg_type,
        "messageTimestamp": ts,
    }


class TestDefaultFilenameUsesSelectedLanguage:
    def test_voice_message_prefix_is_translated(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("audioMessage", ptt=True))
        assert name.startswith("voice_message_")
        assert name.endswith(".ogg")
        assert "mensagem_de_voz" not in name

    def test_document_prefix_is_translated(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("documentMessage"))
        assert name.startswith("document_")

    def test_image_prefix_is_translated(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("imageMessage"))
        assert name.startswith("image_")

    def test_video_prefix_is_translated(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("videoMessage"))
        assert name.startswith("video_")

    def test_non_ptt_audio_prefix_is_translated(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("audioMessage", ptt=False))
        assert name.startswith("audio_")

    def test_unknown_type_falls_back_to_generic_translated_prefix(self):
        stub = _Stub()
        name = stub._resolve_media_filename(_msg("stickerMessage"))
        assert name.startswith("file_")

    def test_original_filename_still_wins_over_the_translated_default(self):
        stub = _Stub()
        name = stub._resolve_media_filename(
            _msg("documentMessage", inner={"fileName": "relatorio.pdf"})
        )
        assert name == "relatorio.pdf"
