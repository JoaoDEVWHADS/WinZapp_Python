#WinZapp's Sound System Module

import logging
import os
import sound_lib, sound_lib.output
from sound_lib import stream

import sys

def _load_bassopus():
    """Load the BASS Opus plugin (bassopus.dll) so BASS can play OGG Opus files.

    Tries three approaches in order:
    1. pybassopus import from sound_lib (finds the DLL on sys.path / beside bass.dll).
    2. Explicit BASS_PluginLoad with the DLL beside the running executable / lib/.
    3. Explicit BASS_PluginLoad from client/lib/ in development mode.
    """
    # Candidate directories where bassopus.dll may live
    candidates = []

    # Frozen (PyInstaller onedir): DLL is in lib/ next to WinZapp.exe
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        candidates.append(os.path.join(exe_dir, "lib", "bassopus.dll"))
        candidates.append(os.path.join(exe_dir, "bassopus.dll"))

    # Development: client/lib/bassopus.dll relative to this file
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "lib", "bassopus.dll"))

    # First: try the standard pybassopus import (works if DLL is beside bass.dll)
    try:
        import sound_lib.external.pybassopus
        logging.info("[sound_system] bassopus plugin loaded via pybassopus import")
        return
    except Exception as _e:
        logging.debug("[sound_system] pybassopus import failed (%s), trying explicit path", _e)

    # Second: try BASS_PluginLoad with an explicit path
    try:
        from sound_lib.external import pybass
        for path in candidates:
            path = os.path.normpath(path)
            if os.path.isfile(path):
                handle = pybass.BASS_PluginLoad(path.encode(), 0)
                if handle:
                    logging.info("[sound_system] bassopus loaded via BASS_PluginLoad: %s", path)
                    return
                else:
                    logging.debug("[sound_system] BASS_PluginLoad returned 0 for %s", path)
    except Exception as _e:
        logging.debug("[sound_system] BASS_PluginLoad attempt failed: %s", _e)

    logging.warning(
        "[sound_system] bassopus.dll could not be loaded — OGG Opus voice message "
        "playback will fail. Checked paths: %s", candidates
    )

_load_bassopus()

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
