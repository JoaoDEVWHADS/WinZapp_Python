#WinZapp's Sound System Module

import logging
import os
import sound_lib, sound_lib.output
from sound_lib import stream

try:
    import sound_lib.external.pybassopus
except Exception as _e:
    logging.warning("[sound_system] bassopus plugin not loaded (%s) — OGG Opus playback will fail", _e)

try:
    import sound_lib.external.pybass_aac
except Exception as _e:
    logging.warning("[sound_system] bass_aac plugin not loaded: %s", _e)

class SoundSystem:
    def __init__(self, main_window, sound_dir):
        self.enabled = False
        self.main_window = main_window
        self.sound_dir = sound_dir
        logging.info("[sound_system] sound_dir = %s (exists=%s)", sound_dir, os.path.isdir(sound_dir))

    def start(self):
        self.enabled = True
        self.output = sound_lib.output.Output()


class NullSound:
    """Returned when a sound file can't be loaded — all methods are no-ops."""
    def play(self): pass
    def stop(self): pass


class Sound(stream.FileStream):
    def __init__(self, sound_system, file, *args, **kwargs):
        self.sound_system = sound_system
        if os.path.isfile(os.path.join(self.sound_system.sound_dir, file)): #sound is a file on disk
            self.file = os.path.join(self.sound_system.sound_dir, file)
        else: #sound is coming from memory
            self.file = file
        super().__init__(*args, file=self.file, **kwargs)

    def play(self):
        super().stop()
        #Check if sounds are enabled
        if self.sound_system.main_window.settings.get("general", {}).get("sounds_enabled", False):
            super().play()


def load_sound(sound_system, file):
    """Create a Sound, returning NullSound if the file can't be opened."""
    try:
        return Sound(sound_system, file)
    except Exception as e:
        logging.warning("[sound_system] Could not load sound '%s': %s", file, e)
        return NullSound()
