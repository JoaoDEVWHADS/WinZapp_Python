"""Regression tests for attachment caption staging."""

from ui.conversations import ConversationsPanel


class _CaptionField:
    def __init__(self, value):
        self.value = value

    def GetValue(self):
        return self.value

    def Clear(self):
        self.value = ""


class _Stub:
    _consume_attachment_caption = ConversationsPanel._consume_attachment_caption

    def __init__(self, caption):
        self._caption_field = _CaptionField(caption)


def test_consuming_attachment_caption_clears_the_staging_field():
    panel = _Stub("  legenda do arquivo  ")

    assert panel._consume_attachment_caption() == "legenda do arquivo"
    assert panel._caption_field.GetValue() == ""


def test_next_attachment_caption_is_blank_when_no_new_caption_is_written():
    panel = _Stub("legenda do primeiro arquivo")

    panel._consume_attachment_caption()

    assert panel._consume_attachment_caption() == ""
