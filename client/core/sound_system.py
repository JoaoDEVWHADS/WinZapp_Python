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


# ── Import plugin modules (early, so their symbols are available) ─────────────
try:
    import sound_lib.external.pybassopus as _pybassopus
except Exception as _e:
    _pybassopus = None

try:
    import sound_lib.external.pybass_aac as _pybass_aac
except Exception as _e:
    _pybass_aac = None


class SoundSystem:
    def __init__(self, main_window, sound_dir):
        self.enabled = False
        self.main_window = main_window
        self.sound_dir = sound_dir
        logging.info("[sound_system] sound_dir = %s (exists=%s)", sound_dir, os.path.isdir(sound_dir))

    def _load_bass_plugin(self, dll_name: str) -> bool:
        """Load a BASS plugin DLL via BASS_PluginLoad with an absolute path.

        Called after BASS Output() is initialised so both the logger and BASS
        device are ready. pybassopus/pybass_aac may import without error even
        when their internal libloader search fails silently — so we always call
        this explicitly with the real path.
        """
        candidates_dirs = []
        if getattr(sys, 'frozen', False):
            exe_dir = os.path.dirname(sys.executable)
            candidates_dirs += [exe_dir, os.path.join(exe_dir, 'lib')]
        if hasattr(sys, '_MEIPASS'):
            candidates_dirs += [sys._MEIPASS, os.path.join(sys._MEIPASS, 'lib')]
        _src_lib = os.path.join(os.path.dirname(__file__), '..', 'lib')
        candidates_dirs.append(os.path.normpath(_src_lib))

        logging.info("[sound_system] Looking for %s in: %s", dll_name, candidates_dirs)

        for d in candidates_dirs:
            path = os.path.join(d, dll_name)
            logging.info("[sound_system] Checking %s (exists=%s)", path, os.path.isfile(path))
            if not os.path.isfile(path):
                continue
            
            # Temporarily add the specific DLL directory to Windows DLL search path
            cookie = None
            if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
                try:
                    cookie = os.add_dll_directory(d)
                except Exception as e:
                    logging.debug("[sound_system] os.add_dll_directory failed for %s: %s", d, e)

            # Keep track of current working directory to restore it later
            old_cwd = os.getcwd()
            try:
                # Change directory to where the DLL resides so dependencies like libopus-0.dll are resolved locally
                os.chdir(d)
                # Load DLL dependency search paths locally using win32 API SetDllDirectoryW if available
                try:
                    ctypes.windll.kernel32.SetDllDirectoryW(d)
                except Exception:
                    pass

                bass_dll = ctypes.WinDLL("bass.dll")
                BASS_PluginLoad = bass_dll.BASS_PluginLoad
                BASS_PluginLoad.restype  = ctypes.c_ulong
                BASS_PluginLoad.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
                
                # Pass just the filename to BASS_PluginLoad since we already changed the CWD to the target directory
                handle = BASS_PluginLoad(dll_name.encode('utf-8'), 0)
                if handle:
                    logging.info("[sound_system] BASS_PluginLoad OK: %s (handle=%s)", path, handle)
                    return True
                else:
                    try:
                        err = bass_dll.BASS_ErrorGetCode()
                    except Exception:
                        err = "?"
                    logging.warning("[sound_system] BASS_PluginLoad=0 for %s (BASS error=%s)", path, err)
            except Exception as _ex:
                logging.warning("[sound_system] BASS_PluginLoad exception for %s: %s", path, _ex)
            finally:
                # Restore original CWD and clean SetDllDirectoryW
                try:
                    os.chdir(old_cwd)
                    if sys.platform == 'win32':
                        ctypes.windll.kernel32.SetDllDirectoryW(None)
                except Exception:
                    pass
                if cookie:
                    try:
                        cookie.close()
                    except Exception:
                        pass
        return False

    def start(self):
        self.enabled = True
        self.output = sound_lib.output.Output()
        # Load BASS plugins AFTER Output() so BASS device is initialised
        if not self._load_bass_plugin('bassopus.dll'):
            logging.warning("[sound_system] bassopus.dll not loaded — OGG Opus playback will fail")
        self._load_bass_plugin('bass_aac.dll')



# ── Sound event registry ────────────────────────────────────────────────────
# Every one-shot UI sound the app plays, as (settings key, default filename in
# sounds/) pairs — except message_background.ogg, which is configured
# separately (Alert Tones settings tab / per-conversation override) since it
# plays through the WinRT toast notification path, not through this list.
SOUND_EVENTS: list[tuple[str, str]] = [
    ("startup", "startup.ogg"),
    ("error", "error.ogg"),
    ("qrcode_loaded", "qrcode_loaded.ogg"),
    ("waiting_pairing", "waiting_pairing.ogg"),
    ("pairing_code_updated", "pairing_code_updated.ogg"),
    ("connected", "connected.ogg"),
    ("synchronizing", "synchronizing.ogg"),
    ("sync_complete", "sync_complete.ogg"),
    ("offline_mode", "offline_mode.ogg"),
    ("voicemsg_startrecording", "voicemsg_startrecording.ogg"),
    ("voicemsg_pauserecording", "voicemsg_pauserecording.ogg"),
    ("voicemsg_discard", "voicemsg_discard.ogg"),
    ("voicemsg_send", "voicemsg_send.ogg"),
    ("message_current", "message_current.ogg"),
    ("message_foreground", "message_foreground.ogg"),
    ("message_sent", "message_sent.ogg"),
]

# ── Alert tone registry (background notification sound choices) ────────────
# Shared by the Settings > Alert Tones tab (private/group defaults) and the
# per-conversation notification-sound picker in the conversation data dialog.
ALERT_TONE_COUNT = 10   # client/sounds/alerts/Alert-01.ogg .. Alert-10.ogg


def alert_tone_choice_keys() -> list[str]:
    """Ordered internal choice keys: 'default', 'alert_1'..'alert_N', 'custom'."""
    return ["default"] + [f"alert_{i}" for i in range(1, ALERT_TONE_COUNT + 1)] + ["custom"]


def resolve_alert_tone_path(sound_dir: str, choice: str, custom_path: str = "") -> str:
    """Resolve an alert-tone choice key to an absolute .ogg path.

    'default' -> message_background.ogg, 'alert_N' -> sounds/alerts/Alert-0N.ogg,
    'custom' -> custom_path as given (validation is the caller's job — this
    just resolves the choice, it doesn't check the file exists).
    """
    if choice == "custom":
        return custom_path or ""
    if choice and choice.startswith("alert_"):
        try:
            n = int(choice.split("_", 1)[1])
        except (ValueError, IndexError):
            n = 0
        if 1 <= n <= ALERT_TONE_COUNT:
            return os.path.join(sound_dir, "alerts", f"Alert-{n:02d}.ogg")
    return os.path.join(sound_dir, "message_background.ogg")


class NullSound:
    """Returned when a sound file can't be loaded — all methods are no-ops."""
    def play(self): pass
    def stop(self): pass


class Sound(stream.FileStream):
    def __init__(self, sound_system, file, event_key=None, *args, **kwargs):
        self.sound_system = sound_system
        self.event_key = event_key
        if os.path.isfile(os.path.join(self.sound_system.sound_dir, file)): #sound is a file on disk
            self.file = os.path.join(self.sound_system.sound_dir, file)
        else: #sound is coming from memory
            self.file = file
        super().__init__(*args, file=self.file, **kwargs)

    def play(self):
        super().stop()
        # Each sound event can be individually enabled/disabled from the
        # Settings > Sound Events tab. Sounds not tied to an event (e.g. the
        # background notification tone, resolved dynamically elsewhere) always
        # play — there's nothing here to gate them on.
        if self.event_key is not None:
            events = self.sound_system.main_window.settings.get("sound_events", {})
            if not events.get(self.event_key, {}).get("enabled", True):
                return
        super().play()


def load_sound(sound_system, file, event_key=None):
    """Create a Sound, returning NullSound if the file can't be opened."""
    try:
        return Sound(sound_system, file, event_key=event_key)
    except Exception as e:
        logging.warning("[sound_system] Could not load sound '%s': %s", file, e)
        return NullSound()
