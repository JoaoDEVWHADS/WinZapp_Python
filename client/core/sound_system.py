#WinZapp's Sound System Module

import os
import sound_lib, sound_lib.output
from sound_lib import stream

try:
    import sound_lib.external.pybassopus
    import sound_lib.external.pybass_aac
except Exception:
    pass

class SoundSystem:
    def __init__(self, main_window, sound_dir):
        self.enabled = False
        self.main_window = main_window
        self.sound_dir = sound_dir

    def start(self):
        self.enabled = True
        self.output = sound_lib.output.Output()


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
