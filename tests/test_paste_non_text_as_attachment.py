"""Tests for Ctrl+V of non-text clipboard content (files, images) inside a
conversation: skip the file picker and go straight to the attachment panel,
same shortcut the official WhatsApp client offers.
"""

import os
import tempfile

import pytest
import wx

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


def _open_clipboard(retries=10):
    import time
    for _ in range(retries):
        if wx.TheClipboard.Open():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture(autouse=True)
def _clear_clipboard_after_test():
    yield
    if _open_clipboard():
        try:
            wx.TheClipboard.Clear()
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()


def _set_clipboard_files(paths):
    if not _open_clipboard():
        return False
    try:
        wx.TheClipboard.Clear()
        data = wx.FileDataObject()
        for p in paths:
            data.AddFile(p)
        wx.TheClipboard.SetData(data)
        wx.TheClipboard.Flush()
    finally:
        wx.TheClipboard.Close()
    return True


def _set_clipboard_bitmap():
    try:
        wx.InitAllImageHandlers()
    except Exception:
        pass
    bmp = wx.Bitmap(16, 16)
    dc = wx.MemoryDC(bmp)
    dc.SetBackground(wx.Brush(wx.Colour(255, 0, 0)))
    dc.Clear()
    dc.SelectObject(wx.NullBitmap)
    del dc
    if not _open_clipboard():
        return False
    try:
        wx.TheClipboard.Clear()
        wx.TheClipboard.SetData(wx.BitmapDataObject(bmp))
        wx.TheClipboard.Flush()
    finally:
        wx.TheClipboard.Close()
    return True


def _set_clipboard_text(text):
    if not _open_clipboard():
        return False
    try:
        wx.TheClipboard.Clear()
        wx.TheClipboard.SetData(wx.TextDataObject(text))
        wx.TheClipboard.Flush()
    finally:
        wx.TheClipboard.Close()
    return True


class TestPasteFiles:
    def test_pasted_files_are_staged_by_extension(self, wx_app, tmp_path):
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n")
        doc = tmp_path / "report.pdf"
        doc.write_bytes(b"%PDF")

        if not _set_clipboard_files([str(img), str(doc)]):
            pytest.skip("clipboard unavailable")

        stub = _Stub()
        if not _open_clipboard():
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
        if not _open_clipboard():
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
        if not _open_clipboard():
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
        if not _open_clipboard():
            pytest.skip("clipboard unavailable")
        try:
            handled = stub._paste_clipboard_as_attachment()
        finally:
            wx.TheClipboard.Close()

        assert handled is False
        assert stub._staged_attachments == []
        assert stub.panel_shown_calls == 0
