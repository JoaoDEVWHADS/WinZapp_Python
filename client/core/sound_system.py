#WinZapp's Sound System Module

import ctypes
import logging
import os
import sys
import sound_lib, sound_lib.output
from sound_lib import stream
from sound_lib.main import bass_call
import sound_lib.main as _bass_main


def _load_bass_plugin_from_path(dll_name: str) -> bool:
    """Try to load a BASS plugin DLL by absolute path, searching common locations."""
    # Candidate directories: exe dir, exe/lib, sys._MEIPASS, sys._MEIPASS/lib
    candidates_dirs = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates_dirs += [exe_dir, os.path.join(exe_dir, 'lib')]
    if hasattr(sys, '_MEIPASS'):
        candidates_dirs += [sys._MEIPASS, os.path.join(sys._MEIPASS, 'lib')]
    # Also check the source tree lib/ dir (dev mode)
    _src_lib = os.path.join(os.path.dirname(__file__), '..', 'lib')
    candidates_dirs.append(os.path.normpath(_src_lib))

    for d in candidates_dirs:
        path = os.path.join(d, dll_name)
        if os.path.isfile(path):
            try:
                # BASS_PluginLoad(file, flags) → returns handle (non-zero = ok)
                handle = _bass_main.bass_call(
                    _bass_main.BASS_PluginLoad, path.encode('utf-8'), 0
                )
                if handle:
                    logging.info("[sound_system] Loaded BASS plugin %s from %s (handle=%s)", dll_name, path, handle)
                    return True
                else:
                    logging.warning("[sound_system] BASS_PluginLoad returned 0 for %s at %s", dll_name, path)
            except Exception as _ex:
                logging.warning("[sound_system] BASS_PluginLoad error for %s at %s: %s", dll_name, path, _ex)
    return False


# ── Load bassopus (OGG Opus support) ────────────────────────────────────────
_bassopus_loaded = False
try:
    import sound_lib.external.pybassopus as _pybassopus
    # pybassopus calls BASS_PluginLoad internally; if it succeeded, the plugin handle is stored
    _bassopus_loaded = True
    logging.info("[sound_system] pybassopus imported successfully")
except Exception as _e:
    logging.warning("[sound_system] pybassopus import failed (%s) — trying explicit path load", _e)

if not _bassopus_loaded:
    _bassopus_loaded = _load_bass_plugin_from_path('bassopus.dll')
    if not _bassopus_loaded:
        logging.warning("[sound_system] bassopus.dll not loaded — OGG Opus playback will fail")

# ── Load bass_aac (AAC support) ──────────────────────────────────────────────
try:
    import sound_lib.external.pybass_aac
    logging.info("[sound_system] pybass_aac imported successfully")
except Exception as _e:
    logging.warning("[sound_system] bass_aac plugin not loaded: %s", _e)
    _load_bass_plugin_from_path('bass_aac.dll')

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
