"""Tests for preserving original filename when forwarding documents with caption."""

import os
from unittest.mock import MagicMock
from main import MainWindow


def test_resend_media_message_preserves_document_filename(tmp_path, monkeypatch):
    stub = MainWindow.__new__(MainWindow)
    stub.key = b"dummy_key_32_bytes_long_12345678"
    stub.token = "test_token"
    stub.wpp_server = "http://127.0.0.1"
    stub.wpp_port = 6300
    stub.output = MagicMock()
    stub.handle_media_message = MagicMock(return_value=True)

    # Mock data_path and decrypt_bytes
    temp_media = tmp_path / "3EB0F5F2800B0C540313D1.wzmedia"
    temp_media.write_bytes(b"encrypted_content")

    monkeypatch.setattr("main.data_path", lambda folder, fname: str(tmp_path / fname))
    monkeypatch.setattr("core.utils.decrypt_bytes", lambda data, key: b"decrypted_file_bytes")

    sent_calls = []
    def _mock_send_media(target_jid, file_path, media_type, caption="", custom_filename=""):
        sent_calls.append({
            "target_jid": target_jid,
            "file_path": file_path,
            "media_type": media_type,
            "caption": caption,
            "custom_filename": custom_filename,
        })
        return True

    stub.send_media_attachment = _mock_send_media

    msg = {
        "key": {
            "id": "false_120363409652783723@g.us_3EB0F5F2800B0C540313D1",
            "remoteJid": "120363409652783723@g.us",
        },
        "message": {
            "documentMessage": {
                "fileName": "relatorio_final.zip",
                "caption": "Segue o arquivo",
                "mimetype": "application/zip",
            }
        }
    }

    success = stub.resend_media_message_with_caption(msg, "5511999999999@s.whatsapp.net")
    assert success is True
    assert len(sent_calls) == 1
    assert sent_calls[0]["custom_filename"] == "relatorio_final.zip"
    assert sent_calls[0]["caption"] == "Segue o arquivo"
    assert sent_calls[0]["media_type"] == "document"
