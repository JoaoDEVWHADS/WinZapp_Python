"""Regression coverage for the voice/video call button accessibility bug.

Neither `_voice_call_btn` nor `_video_call_btn` had a custom `wx.Accessible`,
so NVDA fell back to the native wx label mnemonic -- and in most locales both
labels started with the same letter after `&` (e.g. en-US "&Voice call" /
"&Video call"), so NVDA announced the same Alt+<letter> shortcut for both
buttons and a blind user could not tell them apart by ear.

Fixed by: giving each button its own dedicated global accelerator
(Ctrl+Shift+V for voice, Ctrl+Alt+Shift+V for video), reporting those through
dedicated `wx.Accessible` subclasses (matching the house pattern in
`client/ui/accessible.py`), stripping the now-redundant `&` mnemonic from the
button labels in every locale, and putting the video button first in both
creation/sizer order and tab order.

ConversationsPanel is a wx.Panel and can't be instantiated without a running
wx.App and a real MainWindow, so the accelerator-table wiring and sizer order
are verified against the source text, matching the existing pattern in
test_call_video.py's test_video_button_is_restricted_to_individual_chats.
"""

import json
from pathlib import Path

import wx

from ui.accessible import AccessibleVoiceCallButton, AccessibleVideoCallButton


_CONVERSATIONS_SRC = (
    Path(__file__).parents[1] / "client" / "ui" / "conversations.py"
).read_text(encoding="utf-8")


def test_accessible_call_button_classes_report_expected_shortcuts():
    assert AccessibleVoiceCallButton().GetKeyboardShortcut(0) == (wx.ACC_OK, "Ctrl+Shift+V")
    assert AccessibleVideoCallButton().GetKeyboardShortcut(0) == (wx.ACC_OK, "Ctrl+Alt+Shift+V")


def test_voice_and_video_call_accelerators_bind_to_the_right_handlers():
    # (CS, ord("V"), self.ID_CTRL_SHIFT_V) -> voice call
    assert '(CS,               ord("V"),          self.ID_CTRL_SHIFT_V),' in _CONVERSATIONS_SRC
    assert (
        "self.Bind(wx.EVT_MENU, self._on_voice_call,                id=self.ID_CTRL_SHIFT_V)"
        in _CONVERSATIONS_SRC
    )
    # (CAS, ord("V"), self.ID_CTRL_ALT_SHIFT_V) -> video call
    assert '(CAS,              ord("V"),          self.ID_CTRL_ALT_SHIFT_V),' in _CONVERSATIONS_SRC
    assert (
        "self.Bind(wx.EVT_MENU, self._on_video_call,                id=self.ID_CTRL_ALT_SHIFT_V)"
        in _CONVERSATIONS_SRC
    )
    # Alt+L, Alt+Shift+L, Ctrl+L and Ctrl+Shift+L are unrelated pre-existing
    # shortcuts in this same table and must be left untouched.
    assert '(wx.ACCEL_ALT,     ord("L"),          self.ID_ALT_L),' in _CONVERSATIONS_SRC
    assert '(AS,               ord("L"),          self.ID_ALT_SHIFT_L),' in _CONVERSATIONS_SRC
    assert '(wx.ACCEL_CTRL,    ord("L"),          self.ID_ALT_U),' in _CONVERSATIONS_SRC
    assert '(CS,               ord("L"),          self.ID_CTRL_SHIFT_L),' in _CONVERSATIONS_SRC


def test_video_call_button_is_wired_before_voice_call_button_in_the_sizer():
    video_btn_pos = _CONVERSATIONS_SRC.index("self._video_call_btn = wx.Button(")
    voice_btn_pos = _CONVERSATIONS_SRC.index("self._voice_call_btn = wx.Button(")
    assert video_btn_pos < voice_btn_pos

    video_sizer_pos = _CONVERSATIONS_SRC.index(
        "conv_sizer.Add(self._video_call_btn, 0, wx.LEFT | wx.TOP, 5)"
    )
    voice_sizer_pos = _CONVERSATIONS_SRC.index(
        "conv_sizer.Add(self._voice_call_btn, 0, wx.LEFT | wx.TOP, 5)"
    )
    assert video_sizer_pos < voice_sizer_pos


def test_call_buttons_have_dedicated_accessible_objects_set():
    assert "self._video_call_btn.SetAccessible(AccessibleVideoCallButton())" in _CONVERSATIONS_SRC
    assert "self._voice_call_btn.SetAccessible(AccessibleVoiceCallButton())" in _CONVERSATIONS_SRC


def test_call_button_labels_have_no_mnemonic_in_any_language():
    languages = Path(__file__).parents[1] / "client" / "languages"
    for path in languages.glob("*.json"):
        if path.name == "language_map.json":
            continue
        entries = json.loads(path.read_text(encoding="utf-8"))
        assert "&" not in entries["voice_call_button"], path.name
        assert "&" not in entries["video_call_button"], path.name
