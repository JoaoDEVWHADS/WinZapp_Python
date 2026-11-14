"""Speech suppression integration, extracted without loading Windows UI."""
import ast
import textwrap
from types import SimpleNamespace
import unittest

from tests.god_modules import main_window_method_source


def suppression(window):
    # _voice_recording_silence_active lives in client/main_window/shortcuts.py
    # (MainWindow is split into mixins — see main_window/__init__.py).
    source = textwrap.dedent(main_window_method_source("_voice_recording_silence_active"))
    method = ast.parse(source).body[0]
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), "shortcuts.py", "exec"), namespace)
    return namespace[method.name](window)


class SystemAudioSpeechTests(unittest.TestCase):
    def window(self, recording=True, mixed=True):
        return SimpleNamespace(
            settings={"speech_content": {"silence_while_recording": True}},
            conversations_panel=SimpleNamespace(_is_recording=recording,
                                               _recording_system_audio=mixed))

    def test_mixed_recording_does_not_suppress_speech_or_failure_announcement(self):
        self.assertFalse(suppression(self.window()))

    def test_ordinary_recording_keeps_existing_silence_preference(self):
        self.assertTrue(suppression(self.window(mixed=False)))

    def test_idle_speech_is_not_suppressed(self):
        self.assertFalse(suppression(self.window(recording=False, mixed=False)))


if __name__ == "__main__":
    unittest.main()
