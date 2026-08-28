"""Tests for Ctrl+V of non-text clipboard content (files, images) inside a
conversation: skip the file picker and go straight to the attachment panel,
same shortcut the official WhatsApp client offers.
"""

import os
import tempfile
import time

import pytest
import wx

from tests.conftest import set_clipboard_data, set_clipboard_text
from ui.conversations import ConversationsPanel


_SENTINEL = object()


class _Stub:
    _paste_clipboard_as_attachment = ConversationsPanel._paste_clipboard_as_attachment
    _EXT_TYPE_MAP = ConversationsPanel._EXT_TYPE_MAP

    def __init__(self, conversation=_SENTINEL):
        self.conversation = (
            {"remoteJid": "jid1"} if conversation is _SENTINEL else conversation
        )
        self._staged_attachments = []
        self.panel_shown_calls = 0

    def _show_attachment_panel(self):
        self.panel_shown_calls += 1


# The retrying writer lives in conftest so both clipboard-using test modules
# share one implementation — see conftest.set_clipboard_data's docstring.
_set_clipboard_data = set_clipboard_data


def _set_clipboard_files(paths):
    def make():
        data = wx.FileDataObject()
        for p in paths:
            data.AddFile(p)
        return data

    return _set_clipboard_data(make)


def _set_clipboard_bitmap():
    bmp = wx.Bitmap(4, 4)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(wx.Colour(255, 0, 0)))
    dc.Clear()
    dc.SelectObject(wx.NullBitmap)

    return _set_clipboard_data(lambda: wx.BitmapDataObject(bmp))


# Was the one helper here that still ignored SetData()'s return value, three
# lines below the one that fixed it. It backs the tests asserting that plain
# text is NOT staged as an attachment — so a stale FileDataObject left by an
# earlier test made exactly those assertions fail.
_set_clipboard_text = set_clipboard_text


class TestPasteFiles:
    def test_pasted_files_are_staged_by_extension(self, wx_app, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n")
        doc = tmp_path / "report.pdf"
        doc.write_bytes(b"%PDF")

        if not _set_clipboard_files([str(img), str(doc)]):
            pytest.skip("clipboard unavailable")

        stub = _Stub()
        if not wx.TheClipboard.Open():
            pytest.skip("clipboard unavailable")
        try:
            handled = stub._paste_clipboard_as_attachment()
        finally:
            wx.TheClipboard.Close()

        assert handled is True
        types = {a["media_type"] for a in stub._staged_attachments}
        assert {"image", "document"} <= types
        assert stub.panel_shown_calls == 1

    def test_no_open_conversation_does_nothing(self, wx_app, tmp_path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG\r\n")
        if not _set_clipboard_files([str(f)]):
            pytest.skip("clipboard unavailable")

        stub = _Stub(conversation=None)
        if not wx.TheClipboard.Open():
            pytest.skip("clipboard unavailable")
        try:
            handled = stub._paste_clipboard_as_attachment()
        finally:
            wx.TheClipboard.Close()

        assert handled is False
        assert stub._staged_attachments == []
        assert stub.panel_shown_calls == 0


class TestPasteImage:
    def test_pasted_bitmap_is_staged_as_image(self, wx_app):
        if not _set_clipboard_bitmap():
            pytest.skip("clipboard unavailable")

        stub = _Stub()
        if not wx.TheClipboard.Open():
            pytest.skip("clipboard unavailable")
        try:
            handled = stub._paste_clipboard_as_attachment()
        finally:
            wx.TheClipboard.Close()

        assert handled is True
        assert len(stub._staged_attachments) == 1
        entry = stub._staged_attachments[0]
        assert entry["media_type"] == "image"
        assert os.path.isfile(entry["path"])
        assert stub.panel_shown_calls == 1
        os.unlink(entry["path"])


class TestPasteTextIsUnaffected:
    def test_plain_text_is_not_treated_as_attachment(self, wx_app):
        if not _set_clipboard_text("hello world"):
            pytest.skip("clipboard unavailable")

        stub = _Stub()
        if not wx.TheClipboard.Open():
            pytest.skip("clipboard unavailable")
        try:
            handled = stub._paste_clipboard_as_attachment()
        finally:
            wx.TheClipboard.Close()

        assert handled is False
        assert stub._staged_attachments == []
        assert stub.panel_shown_calls == 0
