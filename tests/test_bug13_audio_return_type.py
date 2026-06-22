import re


class TestBug13AudioReturnType:
    """Bug 13: send_audio_message should not be annotated -> bool."""

    def test_return_type_annotation_not_just_bool(self):
        src = open("client/main.py", encoding="utf-8").read()
        # Match function def with annotation (-> ...) before the docstring colon
        m = re.search(r'def send_audio_message\(self,.*?\)\s*->\s*([^:]+)', src)
        assert m, "Could not find send_audio_message annotation"
        ann = m.group(1).strip()
        assert ann != "bool", f"Annotation should not be just bool: {ann}"
        assert "str" in ann, "Should accept str return"
