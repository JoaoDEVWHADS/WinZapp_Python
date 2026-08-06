"""Tests for the user-configurable media auto-download limits
(Settings > Armazenamento: "baixar mídias automaticamente ao sincronizar",
day limit, size limit).

Before this, sync_if_media() enforced a single hardcoded 100 MB cap and the
initial/full sync unconditionally skipped downloading any media at all
("Phase 2 media auto-download on startup bypassed") — the user had to open
the Sincronização menu and trigger "Baixar mídias" by hand every time.
MainWindow._media_max_download_days()/_media_max_download_bytes() now read
these limits from settings["storage"], with 0 meaning "unlimited" for both.

MainWindow is a wx.Frame and cannot be instantiated without a running wx.App,
so the methods under test are exercised as plain functions against a small
stub — same approach as tests/test_message_bookmarks.py.
"""

from main import MainWindow


class _Stub:
    _media_max_download_days = MainWindow._media_max_download_days
    _media_max_download_bytes = MainWindow._media_max_download_bytes

    def __init__(self, storage=None):
        self.settings = {"storage": storage} if storage is not None else {}


class TestMediaMaxDownloadDays:
    def test_defaults_to_30_when_storage_settings_absent(self):
        s = _Stub()
        assert s._media_max_download_days() == 30

    def test_reads_configured_value(self):
        s = _Stub({"media_max_days": 7})
        assert s._media_max_download_days() == 7

    def test_zero_means_unlimited_and_is_returned_as_is(self):
        s = _Stub({"media_max_days": 0})
        assert s._media_max_download_days() == 0

    def test_falls_back_to_default_on_garbage_value(self):
        s = _Stub({"media_max_days": "not-a-number"})
        assert s._media_max_download_days() == 30


class TestMediaMaxDownloadBytes:
    def test_defaults_to_100mb_when_storage_settings_absent(self):
        s = _Stub()
        assert s._media_max_download_bytes() == 100 * 1024 * 1024

    def test_reads_configured_value_in_mb(self):
        s = _Stub({"media_max_mb": 250})
        assert s._media_max_download_bytes() == 250 * 1024 * 1024

    def test_zero_means_unlimited_returned_as_zero_bytes(self):
        s = _Stub({"media_max_mb": 0})
        assert s._media_max_download_bytes() == 0

    def test_falls_back_to_default_on_garbage_value(self):
        s = _Stub({"media_max_mb": None})
        assert s._media_max_download_bytes() == 100 * 1024 * 1024
