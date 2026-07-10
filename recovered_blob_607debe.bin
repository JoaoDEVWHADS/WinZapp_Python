#WinZapp's Sound System Module

import ctypes
import logging
import os
import sys
import sound_lib, sound_lib.output
from sound_lib import stream
from sound_lib.main import bass_call
import sound_lib.main as _bass_main


def _load_bass_plugin_explicit(dll_name: str) -> bool:
    """Load a BASS plugin DLL using ctypes BASS_PluginLoad with an absolute path.

    pybassopus/pybass_aac may import without error even when their internal
    libloader search fails silently — so we always try the explicit load too.
    """
    candidates_dirs = []
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        candidates_dirs += [exe_dir, os.path.join(exe_dir, 'lib')]
    if hasattr(sys, '_MEIPASS'):
        candidates_dirs += [sys._MEIPASS, os.path.join(sys._MEIPASS, 'lib')]
    # dev mode: source tree lib/ next to this file's parent package
    _src_lib = os.path.join(os.path.dirname(__file__), '..', 'lib')
    candidates_dirs.append(os.path.normpath(_src_lib))

    for d in candidates_dirs:
        path = os.path.join(d, dll_name)
        if not os.path.isfile(path):
            continue
        try:
            # Load via ctypes directly — works even if BASS_PluginLoad wrapper
            # in sound_lib has a different calling convention expectation.
            bass_dll = ctypes.WinDLL("bass.dll")
            BASS_PluginLoad = bass_dll.BASS_PluginLoad
            BASS_PluginLoad.restype  = ctypes.c_ulong
            BASS_PluginLoad.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
            handle = BASS_PluginLoad(path.encode('utf-8'), 0)
            if handle:
                logging.info(
                    "[sound_system] BASS_PluginLoad OK: %s from %s (handle=%s)",
                    dll_name, path, handle
                )
                return True
            else:
                # GetLastError via BASS_ErrorGetCode
                try:
                    err = bass_dll.BASS_ErrorGetCode()
                except Exception:
                    err = "?"
                logging.warning(
                    "[sound_system] BASS_PluginLoad returned 0 for %s at %s (BASS error=%s)",
                    dll_name, path, err
                )
        except Exception as _ex:
            logging.warning(
                "[sound_system] explicit BASS_PluginLoad failed for %s at %s: %s",
                dll_name, path, _ex
            )
    return False


# ── Load bassopus (OGG Opus support) ────────────────────────────────────────
try:
    import sound_lib.external.pybassopus as _pybassopus
    logging.info("[sound_system] pybassopus module imported")
except Exception as _e:
    logging.warning("[sound_system] pybassopus import failed: %s", _e)

# Always force explicit load — pybassopus may import without actually loading the DLL
_bassopus_ok = _load_bass_plugin_explicit('bassopus.dll')
if not _bassopus_ok:
    logging.warning("[sound_system] bassopus.dll not loaded via explicit path — OGG Opus playback will fail")

# ── Load bass_aac (AAC support) ──────────────────────────────────────────────
try:
    import sound_lib.external.pybass_aac
    logging.info("[sound_system] pybass_aac module imported")
except Exception as _e:
    logging.warning("[sound_system] bass_aac plugin not loaded: %s", _e)
_load_bass_plugin_explicit('bass_aac.dll')


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
