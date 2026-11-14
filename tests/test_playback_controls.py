"""Settings > Audio > Audio playback: leaving the speed button and the duration
bar out of the controls after the message list while media plays.

`_show_audio_controls()` runs unbound on a stub; no window opens.
"""

from types import SimpleNamespace

from core import playback_controls
from core.utils import DEFAULT_SETTINGS
from ui.conversation_panel.audio_playback import AudioPlaybackMixin


def test_both_shown_by_default():
    assert DEFAULT_SETTINGS["audio_playback"]["hide_speed_button"] is False
    assert DEFAULT_SETTINGS["audio_playback"]["hide_progress_bar"] is False
    assert playback_controls.shown(DEFAULT_SETTINGS) == (True, True)
    assert playback_controls.shown({}) == (True, True)
    assert playback_controls.shown(None) == (True, True)


def test_only_an_explicit_true_hides():
    assert playback_controls.shown({"audio_playback": {"hide_speed_button": True}}) == (False, True)
    assert playback_controls.shown({"audio_playback": {"hide_progress_bar": True}}) == (True, False)
    assert playback_controls.shown({"audio_playback": {"hide_progress_bar": "yes"}}) == (True, True)


class _Control:
    def __init__(self):
        self.shown = None

    def Show(self, show=True):
        self.shown = show


def _panel(settings):
    return SimpleNamespace(
        main_window=SimpleNamespace(settings=settings),
        audio_speed_btn=_Control(), audio_progress_label=_Control(), audio_slider=_Control(),
        conversation_panel=SimpleNamespace(Layout=lambda: None),
    )


def test_playback_shows_what_settings_allow():
    panel = _panel({"audio_playback": {"hide_speed_button": True, "hide_progress_bar": True}})
    AudioPlaybackMixin._show_audio_controls(panel)
    assert (panel.audio_speed_btn.shown, panel.audio_progress_label.shown,
            panel.audio_slider.shown) == (False, False, False)
    panel = _panel({})
    AudioPlaybackMixin._show_audio_controls(panel)
    assert (panel.audio_speed_btn.shown, panel.audio_progress_label.shown,
            panel.audio_slider.shown) == (True, True, True)
