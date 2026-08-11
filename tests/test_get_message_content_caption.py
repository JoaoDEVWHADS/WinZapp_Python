"""Tests for ConversationsPanel._get_message_content()'s caption handling
across attachment types.

Reported live: sending an attachment with a caption showed the caption
correctly for images, but not for video or document messages — the virtual
(pending) message built in _on_send_attachment() always included
message[type]["caption"] for every attachment type, but only the
imageMessage branch here ever read it back out.
"""

from ui.conversations import ConversationsPanel


class _FakeI18n:
    _STRINGS = {
        "document": "Documento",
        "photo": "Foto",
        "photo_no_caption": "Foto sem legenda",
        "video": "Vídeo",
        "duration": "duração",
        "second": "segundo", "seconds": "segundos",
        "minute": "minuto", "minutes": "minutos",
        "hour": "hora", "hours": "horas",
        "and": "e",
        "decimal_separator": ".",
    }

    def t(self, key):
        return self._STRINGS.get(key, f"[{key}]")


class _Stub:
    _get_message_content = ConversationsPanel._get_message_content
    _format_duration      = ConversationsPanel._format_duration
    _format_filesize      = ConversationsPanel._format_filesize

    def __init__(self):
        self.main_window = type("MW", (), {"i18n": _FakeI18n()})()
        self._download_progress = {}


def _msg(message_type, inner):
    return {
        "messageType": message_type,
        "message": {message_type: inner},
        "key": {"id": "ABC"},
    }


class TestDocumentCaption:
    def test_caption_is_shown_when_present(self):
        stub = _Stub()
        msg = _msg("documentMessage", {
            "fileName": "contrato.pdf", "fileLength": 1024,
            "caption": "Segue o contrato assinado",
        })

        text = stub._get_message_content(msg)

        assert "contrato.pdf" in text
        assert "Segue o contrato assinado" in text

    def test_no_caption_omits_the_clause(self):
        stub = _Stub()
        msg = _msg("documentMessage", {"fileName": "contrato.pdf", "fileLength": 1024})

        text = stub._get_message_content(msg)

        assert text == "Documento, contrato.pdf, 1.0 kb"


class TestVideoCaption:
    def test_caption_is_shown_when_present(self):
        stub = _Stub()
        msg = _msg("videoMessage", {"seconds": 12, "caption": "Olha isso!"})

        text = stub._get_message_content(msg)

        assert "Olha isso!" in text
        assert "Vídeo" in text

    def test_no_caption_omits_the_clause(self):
        stub = _Stub()
        msg = _msg("videoMessage", {"seconds": 12})

        text = stub._get_message_content(msg)

        assert text == "Vídeo, duração: 12 segundos"

    def test_gif_playback_is_unaffected_by_caption_handling(self):
        stub = _Stub()
        msg = _msg("videoMessage", {"seconds": 3, "gifPlayback": True, "caption": "engraçado"})

        text = stub._get_message_content(msg)

        assert text == "[sticker]"


class TestImageCaptionStillWorks:
    """Sanity check the already-working case wasn't disturbed."""

    def test_caption_is_shown_when_present(self):
        stub = _Stub()
        msg = _msg("imageMessage", {"caption": "Legenda da foto"})

        text = stub._get_message_content(msg)

        assert text == "Foto, Legenda da foto"

    def test_no_caption_uses_the_placeholder(self):
        stub = _Stub()
        msg = _msg("imageMessage", {})

        text = stub._get_message_content(msg)

        assert text == "Foto sem legenda"
