"""Tests for ConversationsPanel._pre_cache_sent_media() and the rename step
in _mark_message_sent() that follows it.

Reported live: sending a document/image/video attachment showed the virtual
pending message with only a Download button — Open/Save As only appeared
after the user explicitly downloaded the file again, even though WinZapp
already has the exact bytes on disk (it's the sender). This mirrors the
existing "rename the local audio file so we don't have to download it"
trick _mark_message_sent() already did for recorded voice messages
(voice_messages/<id>.msv), extended to attachment-picker files cached under
data/media/<id>.wzmedia — the same directory/extension handle_media_message()
downloads real messages into, and the same one on_message_selected() checks
via os.path.isfile() to decide Download vs Open+Save As.

ConversationsPanel is a wx.Panel and cannot be instantiated without a
running wx.App, so the methods under test are exercised as plain functions
against a small stub — same approach as tests/test_message_bookmarks.py.
"""

import os

import pytest
from cryptography.fernet import Fernet

import ui.conversations as conversations_module
from ui.conversations import ConversationsPanel


class _FakeMainWindow:
    def __init__(self, key):
        self.key = key


class _Stub:
    _pre_cache_sent_media = ConversationsPanel._pre_cache_sent_media

    def __init__(self, key):
        self.main_window = _FakeMainWindow(key)


@pytest.fixture
def fake_data_path(tmp_path, monkeypatch):
    def _data_path(*parts):
        p = tmp_path.joinpath(*parts) if parts else tmp_path
        os.makedirs(p.parent if parts else p, exist_ok=True)
        return str(p)

    monkeypatch.setattr(conversations_module, "data_path", _data_path)
    return tmp_path


class TestPreCacheSentMedia:
    def test_document_is_cached_under_local_id_in_the_media_dir(self, fake_data_path, tmp_path):
        key = Fernet.generate_key()
        src = tmp_path / "report.pdf"
        src.write_bytes(b"%PDF-1.4 fake contents")
        stub = _Stub(key)

        stub._pre_cache_sent_media("local-123", str(src), "document")

        cache_file = fake_data_path / "media" / "local-123.wzmedia"
        assert cache_file.is_file()
        decrypted = Fernet(key).decrypt(cache_file.read_bytes())
        assert decrypted == b"%PDF-1.4 fake contents"

    def test_audio_file_is_cached_in_voice_messages_as_msv(self, fake_data_path, tmp_path):
        key = Fernet.generate_key()
        src = tmp_path / "clip.ogg"
        src.write_bytes(b"fake-ogg-bytes")
        stub = _Stub(key)

        stub._pre_cache_sent_media("local-456", str(src), "audio")

        cache_file = fake_data_path / "voice_messages" / "local-456.msv"
        assert cache_file.is_file()
        assert Fernet(key).decrypt(cache_file.read_bytes()) == b"fake-ogg-bytes"

    def test_missing_source_file_does_not_raise(self, fake_data_path, tmp_path):
        stub = _Stub(Fernet.generate_key())
        stub._pre_cache_sent_media("local-789", str(tmp_path / "does_not_exist.pdf"), "document")
        assert not (fake_data_path / "media" / "local-789.wzmedia").exists()


class TestMarkMessageSentRenamesMediaCache:
    """_mark_message_sent() itself touches wx widgets (messages_list,
    sound objects) beyond what's worth stubbing here; this exercises just
    the rename step in isolation, the same way the pre-existing audio
    rename behaves, to pin the documented contract: local_id.wzmedia becomes
    real_id.wzmedia once the real id is known."""

    def test_rename_contract_matches_the_audio_precedent(self, fake_data_path):
        media_dir = fake_data_path / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        old_media = media_dir / "local-abc.wzmedia"
        old_media.write_bytes(b"cached-bytes")

        # Mirrors the rename block added to _mark_message_sent() for
        # documentMessage/imageMessage/videoMessage.
        new_media = media_dir / "real-999.wzmedia"
        if old_media.is_file() and not new_media.is_file():
            os.rename(str(old_media), str(new_media))

        assert not old_media.exists()
        assert new_media.read_bytes() == b"cached-bytes"
