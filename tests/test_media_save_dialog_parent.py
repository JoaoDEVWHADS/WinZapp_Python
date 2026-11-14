"""The Media tab's Save dialog belongs to the conversation data dialog.

Reported: saving a file with the Save button of the group data dialog's Media
tab sometimes left WinZapp "indisponível". The Save dialog was parented to the
conversation panel, whose top-level window (the main window) is disabled while
the modal data dialog is open. Windows reactivates a closed dialog's owner, so
focus went back to that disabled window instead of the data dialog.
"""

import inspect

import wx

from ui.conversations import ConversationsPanel
from ui.dialogs.conversation_data_dialog import ConversationDataDialog


class _CapturingFileDialog:
    parent = None

    def __init__(self, parent, *args, **kwargs):
        type(self).parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def ShowModal(self):
        return wx.ID_CANCEL


class _FakeI18n:
    def t(self, key):
        return key


class _FakeMainWindow:
    def __init__(self):
        self.i18n = _FakeI18n()
        self.settings = {}
        self.app_name = "WinZapp"


_PanelStub = type("_PanelStub", (), {
    "_is_separator": ConversationsPanel._is_separator,
    "_resolve_media_filename": ConversationsPanel._resolve_media_filename,
    "save_media_message": ConversationsPanel.save_media_message,
})


def _image_msg():
    return {
        "key": {"id": "ABC123", "fromMe": False},
        "message": {"imageMessage": {"mimetype": "image/jpeg"}},
        "messageType": "imageMessage",
        "messageTimestamp": 1700000000,
    }


def _panel():
    panel = _PanelStub()
    panel.main_window = _FakeMainWindow()
    return panel


def test_save_dialog_uses_the_given_parent(monkeypatch):
    monkeypatch.setattr(wx, "FileDialog", _CapturingFileDialog)
    owner = object()

    _panel().save_media_message(_image_msg(), parent=owner)

    assert _CapturingFileDialog.parent is owner


def test_save_dialog_defaults_to_the_panel(monkeypatch):
    monkeypatch.setattr(wx, "FileDialog", _CapturingFileDialog)
    panel = _panel()

    panel.save_media_message(_image_msg())

    assert _CapturingFileDialog.parent is panel


def test_media_tab_save_button_passes_the_dialog_as_parent():
    calls = []

    class _Panel:
        def save_media_message(self, msg, parent=None):
            calls.append((msg, parent))

    msg = _image_msg()
    panel = _Panel()
    dialog = type("_DialogStub", (), {
        "_on_media_save_btn": ConversationDataDialog._on_media_save_btn,
        "_invoke": ConversationDataDialog._invoke,
    })()
    dialog._selected_media_message = lambda: msg
    dialog._conversation_panel = lambda: panel
    dialog._panel_is_on_this_chat = lambda: True

    dialog._on_media_save_btn(None)

    assert calls == [(msg, dialog)]


def test_every_media_tab_save_path_passes_the_dialog_as_parent():
    """Button, Ctrl+Shift+S and the context menu all open the same dialog."""
    src = inspect.getsource(ConversationDataDialog)
    calls = src.count("panel.save_media_message(")
    assert calls == 3
    assert src.count("panel.save_media_message(msg, parent=self)") == calls
