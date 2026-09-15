"""Tests for ui.dialogs.clear_chat_confirm.confirm_clear_chat().

ClearChatConfirmDialog is replaced by a fake, so nothing is ever shown on the
desktop (see tests/test_no_desktop_visible_windows.py for why that matters).
"""

import pytest
import wx

from ui.dialogs import clear_chat_confirm


class _FakeDialog:
    # Per-test behaviour, overridden with monkeypatch.setattr on the class.
    result = wx.ID_YES
    checked_on_close = True
    raise_on_show = False
    instances = []

    def __init__(self, parent, message, title, keep_starred_label, yes_label, no_label):
        self.args = (parent, message, title, keep_starred_label, yes_label, no_label)
        self.destroyed = False
        _FakeDialog.instances.append(self)

    def ShowModal(self):
        if self.raise_on_show:
            raise RuntimeError("boom")
        return self.result

    def keep_starred(self):
        assert not self.destroyed, "checkbox read after Destroy()"
        return self.checked_on_close

    def Destroy(self):
        self.destroyed = True


@pytest.fixture
def fake_dialog(monkeypatch):
    monkeypatch.setattr(_FakeDialog, "instances", [])
    monkeypatch.setattr(clear_chat_confirm, "ClearChatConfirmDialog", _FakeDialog)
    return _FakeDialog


def test_every_label_reaches_the_dialog(fake_dialog):
    clear_chat_confirm.confirm_clear_chat(
        None, "msg", "title", "keep label", yes_label="&Sim", no_label="&Não",
    )

    dlg, = fake_dialog.instances
    assert dlg.args[1:] == ("msg", "title", "keep label", "&Sim", "&Não")
    assert dlg.destroyed


def test_yes_with_the_checkbox_ticked(fake_dialog):
    assert clear_chat_confirm.confirm_clear_chat(None, "m", "t", "l", yes_label="y", no_label="n") == (True, True)


def test_yes_with_the_checkbox_unticked(fake_dialog, monkeypatch):
    monkeypatch.setattr(fake_dialog, "checked_on_close", False)

    assert clear_chat_confirm.confirm_clear_chat(None, "m", "t", "l", yes_label="y", no_label="n") == (True, False)


def test_no_is_not_confirmed(fake_dialog, monkeypatch):
    monkeypatch.setattr(fake_dialog, "result", wx.ID_NO)

    confirmed, _ = clear_chat_confirm.confirm_clear_chat(None, "m", "t", "l", yes_label="y", no_label="n")

    assert confirmed is False


def test_the_dialog_is_destroyed_even_when_showing_it_raises(fake_dialog, monkeypatch):
    monkeypatch.setattr(fake_dialog, "raise_on_show", True)

    with pytest.raises(RuntimeError):
        clear_chat_confirm.confirm_clear_chat(None, "m", "t", "l", yes_label="y", no_label="n")

    dlg, = fake_dialog.instances
    assert dlg.destroyed


def test_it_is_not_the_task_dialog_checkbox_again():
    """RichMessageDialog's checkbox was read by NVDA as read-only and
    unchecked; the confirmation must stay on a plain wx.CheckBox."""
    import ast

    with open(clear_chat_confirm.__file__, encoding="utf-8") as f:
        tree = ast.parse(f.read())
    called = {
        getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "CheckBox" in called
    assert "RichMessageDialog" not in called
    assert "ShowCheckBox" not in called
