import re


class TestBug12AudioProgress:
    """Bug 12: Audio messages must pass progress_callback to handle_audio_message."""

    def test_sync_if_media_passes_callback_for_audio(self):
        src = open("client/main.py", encoding="utf-8").read()
        # Find sync_if_media and check audio passes progress_callback
        m = re.search(r'def sync_if_media.*?audioMessage.*?progress_callback', src, re.DOTALL)
        assert m, "progress_callback not found in sync_if_media audio path"

    def test_handle_audio_message_accepts_progress_callback(self):
        src = open("client/main.py", encoding="utf-8").read()
        m = re.search(r'def handle_audio_message\(self,\s*msg,\s*progress_callback=None', src)
        assert m, "handle_audio_message does not accept progress_callback"
