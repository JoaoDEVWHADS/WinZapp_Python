import re


class TestBug11SaveAudioLogging:
    """Bug 11: save_audio_locally must print error instead of silent pass."""

    def test_has_print_not_pass(self):
        src = open("client/main.py", encoding="utf-8").read()
        # Find save_audio_locally function body
        m = re.search(r'def save_audio_locally.*?^(?=\s*def|\s*#)', src, re.DOTALL | re.MULTILINE)
        assert m, "save_audio_locally not found"
        body = m.group()
        assert "print(f\"[save_audio_locally]" in body, "Should print error detail"
        assert "pass" not in body.split("except")[-1].split("\n")[0], "Should not silently pass"
