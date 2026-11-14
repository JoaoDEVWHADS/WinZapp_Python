"""The data dialog's "Profile picture" button, driven against plain stubs.

No window opens: the background thread runs inline, wx.CallAfter calls
straight through and wx.MessageBox / ProfilePictureDialog are replaced.
"""

import pytest
import wx

from ui.dialogs import profile_picture_dialog as ppd
from ui.dialogs.conversation_data_dialog import ConversationDataDialog


class _I18n:
    def t(self, key):
        return key


class _Speech:
    def __init__(self):
        self.spoken = []

    def output(self, text):
        self.spoken.append(text)


class _MainWindow:
    def __init__(self):
        self.i18n = _I18n()
        self.speak_output = _Speech()
        self.wpp_server = "http://127.0.0.1"
        self.wpp_port = 6300
        self.token = "tok"
        self.contacts = {}
        self._lid_to_phone = {"9@lid": "5511999990000@s.whatsapp.net"}


class _Parent:
    def __init__(self, shown=True):
        self._shown = shown

    def IsShown(self):
        return self._shown


class _Button:
    def __init__(self):
        self.focused = 0

    def SetFocus(self):
        self.focused += 1


class _Thread:
    """Queues the target; `_drain()` runs it, as the worker thread would."""
    pending = []

    def __init__(self, target, daemon=None):
        self._target = target

    def start(self):
        _Thread.pending.append(self._target)


def _drain():
    while _Thread.pending:
        _Thread.pending.pop(0)()


def _patch(monkeypatch, data, tmp_path):
    calls = {"fetch": [], "boxes": [], "dialogs": []}
    _Thread.pending = []
    monkeypatch.setattr(ppd.threading, "Thread", _Thread)
    monkeypatch.setattr(ppd.wx, "CallAfter", lambda fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(ppd.wx, "MessageBox", lambda *a, **k: calls["boxes"].append(a))
    monkeypatch.setattr(ppd, "data_path", lambda *parts: str(tmp_path.joinpath(*parts)))

    def fake_fetch(base_url, token, jid, api_get, http_get, fallback=""):
        calls["fetch"].append((base_url, token, jid))
        return data
    monkeypatch.setattr(ppd.profile_picture, "fetch_profile_picture", fake_fetch)

    class _Dialog:
        def __init__(self, parent, i18n, name, path):
            calls["dialogs"].append((name, path))

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass
    monkeypatch.setattr(ppd, "ProfilePictureDialog", _Dialog)
    return calls


def test_no_picture_shows_the_unavailable_message(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, tmp_path)
    mw, parent = _MainWindow(), _Parent()
    ppd.show_profile_picture(parent, mw, "a@s.whatsapp.net", "Ana")
    _drain()
    assert calls["boxes"][0][:2] == ("profile_picture_unavailable", "profile_picture_title")
    assert calls["dialogs"] == []
    assert mw.speak_output.spoken == ["loading"]


def test_a_picture_opens_the_dialog_and_gives_focus_back(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, b"\xff\xd8\xff\xe0" + b"\x00" * 16, tmp_path)
    button = _Button()
    ppd.show_profile_picture(_Parent(), _MainWindow(), "1@g.us", "Família", button)
    _drain()
    (name, path), = calls["dialogs"]
    assert name == "Família" and path.endswith(".jpg")
    assert calls["boxes"] == []
    assert button.focused == 1


def test_a_known_lid_is_asked_by_its_phone(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, tmp_path)
    ppd.show_profile_picture(_Parent(), _MainWindow(), "9@lid", "Ana")
    _drain()
    assert calls["fetch"] == [("http://127.0.0.1:6300", "tok", "5511999990000@s.whatsapp.net")]


def test_a_lid_chat_falls_back_to_the_url_stored_under_its_phone(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, tmp_path)
    fallbacks = []
    monkeypatch.setattr(
        ppd.profile_picture, "fetch_profile_picture",
        lambda base, token, jid, api_get, http_get, fallback="": fallbacks.append(fallback))
    mw = _MainWindow()
    mw.contacts = {"5511999990000@s.whatsapp.net": {"profilePicUrl": "https://cdn/p"}}
    ppd.show_profile_picture(_Parent(), mw, "9@lid", "Ana")
    _drain()
    assert fallbacks == ["https://cdn/p"]


def test_a_second_press_while_loading_is_ignored(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, tmp_path)
    parent, mw = _Parent(), _MainWindow()
    ppd.show_profile_picture(parent, mw, "a@s.whatsapp.net", "Ana")
    ppd.show_profile_picture(parent, mw, "a@s.whatsapp.net", "Ana")
    _drain()
    assert len(calls["fetch"]) == 1
    # Once it is done, the button works again.
    ppd.show_profile_picture(parent, mw, "a@s.whatsapp.net", "Ana")
    _drain()
    assert len(calls["fetch"]) == 2


def test_nothing_is_shown_once_the_data_dialog_is_hidden(monkeypatch, tmp_path):
    calls = _patch(monkeypatch, None, tmp_path)
    ppd.show_profile_picture(_Parent(shown=False), _MainWindow(), "a@s.whatsapp.net", "Ana")
    _drain()
    assert calls["boxes"] == [] and calls["dialogs"] == []


def test_the_data_dialog_button_hands_over_its_chat(monkeypatch):
    seen = []
    monkeypatch.setattr(ppd, "show_profile_picture", lambda *a: seen.append(a))

    class _Stub:
        _on_profile_picture = ConversationDataDialog._on_profile_picture
    stub = _Stub()
    stub._mw, stub._jid, stub._name = object(), "a@s.whatsapp.net", "Ana"
    stub._profile_picture_btn = _Button()
    stub._on_profile_picture(None)
    assert seen == [(stub, stub._mw, "a@s.whatsapp.net", "Ana", stub._profile_picture_btn)]


class TestOpenInDefaultApp:
    def _startfile(self, monkeypatch, fail_times):
        calls = []

        def fake(*args):
            calls.append(args)
            if len(calls) <= fail_times:
                raise OSError("no association")
        monkeypatch.setattr(ppd.sys, "platform", "win32")
        monkeypatch.setattr(ppd.os, "startfile", fake, raising=False)
        return calls

    def test_no_program_for_the_type_asks_windows_which_one(self, monkeypatch):
        calls = self._startfile(monkeypatch, fail_times=1)
        ppd.open_in_default_app("C:/p.jpg")
        assert calls == [("C:/p.jpg",), ("C:/p.jpg", "openas")]

    def test_when_open_with_fails_too_the_caller_hears_of_it(self, monkeypatch):
        self._startfile(monkeypatch, fail_times=2)
        with pytest.raises(OSError):
            ppd.open_in_default_app("C:/p.jpg")
