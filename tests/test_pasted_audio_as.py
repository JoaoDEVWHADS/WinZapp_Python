"""Audio files pasted into the message field (Ctrl+V): sent as audio or as a
document, by the user's choice (Settings > Files and saving), audio by default.

Reported: pasted audio showed in the list as a document and only turned into
audio at the 60 s refresh. Staging the file with the type the user chose means
the row shown while sending is already what WhatsApp will show. Nothing here
opens a window.
"""

import inspect
import wave

import pytest

from core.attachment_types import (
    DEFAULT_PASTED_AUDIO_AS,
    PASTED_AUDIO_MODES,
    pasted_attachment_media_type,
)
from core.utils import DEFAULT_SETTINGS


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "gravacao.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b"\x00\x00" * 80)
    return str(path)


def test_audio_is_the_default():
    assert DEFAULT_PASTED_AUDIO_AS == "audio"
    assert DEFAULT_SETTINGS["general"]["pasted_audio_as"] == "audio"
    assert PASTED_AUDIO_MODES == ("audio", "document")


def test_audio_stays_audio_by_default(wav):
    assert pasted_attachment_media_type(wav, "audio") == "audio"


def test_audio_goes_as_a_document_when_chosen(wav):
    assert pasted_attachment_media_type(wav, "document") == "document"


def test_an_unknown_choice_keeps_audio(wav):
    assert pasted_attachment_media_type(wav, "podcast") == "audio"


def test_other_files_are_not_touched(tmp_path):
    png = tmp_path / "foto.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    txt = tmp_path / "notas.txt"
    txt.write_text("oi", encoding="utf-8")
    for mode in PASTED_AUDIO_MODES:
        assert pasted_attachment_media_type(str(png), mode) == "image"
        assert pasted_attachment_media_type(str(txt), mode) == "document"


def test_the_paste_uses_the_setting():
    from ui.conversation_panel.composer import ComposerMixin
    src = inspect.getsource(ComposerMixin._paste_clipboard_as_attachment)
    assert '.get("pasted_audio_as", DEFAULT_PASTED_AUDIO_AS)' in src
    assert "pasted_attachment_media_type(" in src


def test_settings_load_save_and_relabel_it():
    from ui.dialogs import settings_dialog
    src = inspect.getsource(settings_dialog.SettingsDialog).replace("\r\n", "\n")
    assert '.get("general", {}).get("pasted_audio_as", "audio")' in src
    assert 'PASTED_AUDIO_MODES[self._pasted_audio_radio.GetSelection()]' in src
    assert 'self._pasted_audio_radio.SetLabel(i18n.t("pasted_audio_label"))' in src
