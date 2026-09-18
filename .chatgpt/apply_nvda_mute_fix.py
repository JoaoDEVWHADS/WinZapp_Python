from pathlib import Path

ROOT = Path.cwd()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding='utf-8')


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding='utf-8')


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        if new in text:
            return text
        raise SystemExit(f'missing expected block: {label}')
    return text.replace(old, new, 1)


path = 'client/main.py'
text = read(path)
text = replace_once(
    text,
    '        self.voice_call_window_mute_button = wx.Button(call_panel, label=self.i18n.t("voice_call_mute_button"))\n        self.voice_call_window_end_button.Bind(wx.EVT_BUTTON, self.end_active_call)\n',
    '        self.voice_call_window_mute_button = wx.Button(call_panel, label=self.i18n.t("voice_call_mute_button"))\n        self.voice_call_window_mute_button.SetName(self.i18n.t("voice_call_mute_button").replace("&", ""))\n        self.voice_call_window_end_button.Bind(wx.EVT_BUTTON, self.end_active_call)\n',
    'window mute button accessible name',
)
text = replace_once(
    text,
    '        muted = bool(getattr(getattr(self, "_call_audio_session", None), "microphone_muted", False))\n        mute_label = self.i18n.t("voice_call_unmute_button" if muted else "voice_call_mute_button")\n        for button_name in ("voice_call_mute_button", "voice_call_window_mute_button"):\n            button = getattr(self, button_name, None)\n            if button is not None:\n                button.SetLabel(mute_label)\n',
    '        self._refresh_voice_call_mute_button_labels()\n',
    'sync mute label block',
)
text = replace_once(
    text,
    '            if not window.IsShown():\n                window.Show()\n                window.Raise()\n            self.voice_call_window_mute_button.SetFocus()\n',
    '            if not window.IsShown():\n                window.Show()\n                window.Raise()\n                wx.CallAfter(self._focus_voice_call_window_mute_button)\n',
    'window initial focus',
)
helper = '''\n    def _refresh_voice_call_mute_button_labels(self):\n        muted = bool(getattr(getattr(self, "_call_audio_session", None), "microphone_muted", False))\n        label = self.i18n.t("voice_call_unmute_button" if muted else "voice_call_mute_button")\n        clean_label = label.replace("&", "")\n        for button_name in ("voice_call_mute_button", "voice_call_window_mute_button"):\n            button = getattr(self, button_name, None)\n            if button is not None:\n                button.SetLabel(label)\n                # NVDA can announce the parent wx.Panel when a button loses its\n                # accessible name during a relabel/focus cycle. Keep the button's\n                # accessible name in sync with the visible label so focus remains\n                # on "Mudo"/"Ativar microfone", not on a generic "painel".\n                try:\n                    button.SetName(clean_label)\n                except Exception:\n                    pass\n        return label\n\n    def _focus_voice_call_window_mute_button(self):\n        button = getattr(self, "voice_call_window_mute_button", None)\n        if button is None:\n            return\n        try:\n            if button.IsShown() and button.IsEnabled():\n                button.SetFocus()\n        except Exception:\n            logging.exception("[call] failed to focus mute button")\n\n'''
if 'def _refresh_voice_call_mute_button_labels' not in text:
    text = replace_once(
        text,
        '    def toggle_call_microphone(self, _event=None):\n',
        helper + '    def toggle_call_microphone(self, event=None):\n',
        'insert mute helpers',
    )
else:
    text = text.replace('    def toggle_call_microphone(self, _event=None):\n', '    def toggle_call_microphone(self, event=None):\n', 1)
old_body = '''    def toggle_call_microphone(self, event=None):\n        session = getattr(self, "_call_audio_session", None)\n        if session is None:\n            return\n        session.set_microphone_muted(not session.microphone_muted)\n        self._sync_voice_call_bar()\n        wx.CallAfter(self.voice_call_window_mute_button.SetFocus)\n'''
new_body = '''    def toggle_call_microphone(self, event=None):\n        session = getattr(self, "_call_audio_session", None)\n        if session is None:\n            return\n        session.set_microphone_muted(not session.microphone_muted)\n        self._refresh_voice_call_mute_button_labels()\n        button = None\n        try:\n            button = event.GetEventObject() if event is not None else None\n        except Exception:\n            button = None\n        if button is None:\n            button = getattr(self, "voice_call_window_mute_button", None)\n        if button is not None:\n            wx.CallAfter(button.SetFocus)\n'''
text = replace_once(text, old_body, new_body, 'toggle_call_microphone body')
write(path, text)

path = 'tests/test_group_voice_call_ui.py'
text = read(path)
if 'test_voice_call_mute_toggle_keeps_button_accessible_name_and_focus' not in text:
    text += '''\n\ndef test_voice_call_mute_toggle_keeps_button_accessible_name_and_focus():\n    source = _source("client/main.py")\n\n    assert "def _refresh_voice_call_mute_button_labels" in source\n    assert "button.SetName(clean_label)" in source\n    assert "event.GetEventObject()" in source\n    assert "def _focus_voice_call_window_mute_button" in source\n    toggle_body = source.split("def toggle_call_microphone", 1)[1].split("def on_voice_call_state_event", 1)[0]\n    assert "self._sync_voice_call_bar()" not in toggle_body\n    assert "voice_call_window_mute_button.SetFocus" not in toggle_body\n'''
write(path, text)
