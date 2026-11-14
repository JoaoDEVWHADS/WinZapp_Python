from pathlib import Path
from tests.god_modules import status_panel_source


ROOT = Path(__file__).resolve().parents[1]
SOURCE = status_panel_source()


def test_my_status_audio_starts_automatically():
    assert "if is_audio:" in SOURCE
    assert "wx.CallAfter(self._on_play_pause_video, None)" in SOURCE


def test_status_media_download_retries_before_failing():
    assert "def _download_status_media(main_window, status: dict, attempts: int = 4)" in SOURCE
    assert "for attempt in range(attempts):" in SOURCE
    assert "if attempt + 1 < attempts:" in SOURCE
    assert "time.sleep(1.0)" in SOURCE


def test_all_status_media_consumers_use_retry_helper():
    assert SOURCE.count("_download_status_media(") == 6  # the sixth is the AI Describe loader (status_ai.py)
    assert "return _download_status_media(self.main_window, st)" in SOURCE
    assert "content = _download_status_media(self._mw, status)" in SOURCE
    assert SOURCE.count("content = _download_status_media(mw, status)") == 2
    assert "data = _download_status_media(mw, snapshot)" in SOURCE
