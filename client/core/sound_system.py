#WinZapp's Sound System Module

import ctypes
import json
import logging
import os
import shutil
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


# ── Soundpacks ───────────────────────────────────────────────────────────────
# A soundpack is a subfolder of client/sounds/ containing a *.pack.json
# manifest ({"name": ..., "events": {event_key: relative_path}, "alerts":
# {alert_key: relative_path}}) plus the .ogg files it references. Paths in
# the manifest are always relative to the pack's own folder — never absolute,
# since an absolute path baked in at manifest-authoring time would point at
# the wrong install location on a different machine.
PACK_MANIFEST_SUFFIX = ".pack.json"
DEFAULT_PACK_ID = "default"


def _find_pack_manifest(folder: str) -> "str | None":
    """Return the path to the *.pack.json manifest directly inside `folder`."""
    try:
        for name in os.listdir(folder):
            if name.lower().endswith(PACK_MANIFEST_SUFFIX):
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    return candidate
    except OSError:
        pass
    return None


def _load_pack(pack_id: str, folder: str) -> "dict | None":
    manifest = _find_pack_manifest(folder)
    if not manifest:
        return None
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return {
        "id": pack_id,
        "name": str(data.get("name") or pack_id),
        "dir": folder,
        "events": data.get("events") if isinstance(data.get("events"), dict) else {},
        "alerts": data.get("alerts") if isinstance(data.get("alerts"), dict) else {},
    }


def discover_sound_packs(sounds_root: str) -> dict:
    """Scan sounds_root for immediate subfolders containing a *.pack.json
    manifest. Returns {pack_id: pack_dict}, pack_id being the folder name."""
    packs: dict = {}
    try:
        entries = os.listdir(sounds_root)
    except OSError:
        return packs
    for entry in entries:
        folder = os.path.join(sounds_root, entry)
        if not os.path.isdir(folder):
            continue
        pack = _load_pack(entry, folder)
        if pack:
            packs[entry] = pack
    return packs


def _pack_relative_file(pack: dict, rel_path) -> str:
    """Join a pack-relative path onto the pack's dir. Returns '' if the path
    is missing or (a corrupted/hand-edited manifest) absolute — a manifest
    must never carry an absolute path, so one is treated as not resolvable
    rather than trusted."""
    if not rel_path or not isinstance(rel_path, str) or os.path.isabs(rel_path):
        return ""
    return os.path.join(pack["dir"], rel_path)


def resolve_sound_event_path(active_pack, default_pack, event_key: str, override_path: str = "") -> str:
    """Resolve the file to play for a Sound Events entry, in priority order:
    1. `override_path` (a per-event custom path the user set), if it exists.
    2. The active pack's own file for this event.
    3. The default pack's file for this event — covers packs that don't
       define every event, or a broken/hand-edited settings.json leaving an
       empty/stale override path. This is the fallback the previous
       (non-pack-aware) implementation was missing: an empty or invalid
       stored path used to silently produce no sound instead of falling
       back to the bundled default.
    Returns '' if nothing resolves at all (caller falls back to NullSound).
    """
    if override_path and os.path.isfile(override_path):
        return override_path
    if active_pack:
        p = _pack_relative_file(active_pack, active_pack.get("events", {}).get(event_key, ""))
        if p and os.path.isfile(p):
            return p
    if default_pack and default_pack is not active_pack:
        p = _pack_relative_file(default_pack, default_pack.get("events", {}).get(event_key, ""))
        if p and os.path.isfile(p):
            return p
    return ""


def resolve_alert_tone_path(active_pack, default_pack, choice: str, custom_path: str = "") -> str:
    """Resolve an alert-tone choice key ('default' / 'alert_N' / 'custom') to
    an absolute path, going through the active soundpack with the same
    fallback-to-default-pack chain as resolve_sound_event_path.
    """
    if choice == "custom":
        return custom_path or ""
    key = "message_background" if choice == "default" else choice
    for pack in (active_pack, default_pack if default_pack is not active_pack else None):
        if not pack:
            continue
        source = pack.get("events", {}) if key == "message_background" else pack.get("alerts", {})
        p = _pack_relative_file(pack, source.get(key, ""))
        if p and os.path.isfile(p):
            return p
    return ""


def validate_soundpack_folder(folder: str):
    """Check that `folder` is a valid, importable soundpack.

    Returns (ok: bool, error_i18n_key: str, parsed: dict|None). On success
    error_i18n_key is '' and parsed has 'name'/'events'/'alerts' (paths still
    relative to `folder`, not yet pointed at the copied destination).
    """
    if not folder or not os.path.isdir(folder):
        return False, "soundpack_import_error_no_folder", None

    manifest = _find_pack_manifest(folder)
    if not manifest:
        return False, "soundpack_import_error_no_manifest", None

    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False, "soundpack_import_error_bad_manifest", None

    if not isinstance(data, dict) or not data.get("name") or not isinstance(data.get("events"), dict):
        return False, "soundpack_import_error_bad_manifest", None

    events = data.get("events") or {}
    alerts = data.get("alerts") if isinstance(data.get("alerts"), dict) else {}
    for rel_path in list(events.values()) + list(alerts.values()):
        if not isinstance(rel_path, str) or not rel_path:
            continue
        if os.path.isabs(rel_path):
            return False, "soundpack_import_error_absolute_path", None
        if not os.path.isfile(os.path.join(folder, rel_path)):
            return False, "soundpack_import_error_missing_file", None

    return True, "", {"name": str(data["name"]), "events": events, "alerts": alerts}


def import_soundpack(source_folder: str, sounds_root: str):
    """Validate `source_folder` as a soundpack, then copy it into
    `sounds_root` as a new subfolder (named after the source folder,
    de-duplicated if one with that name already exists).

    Returns (ok: bool, error_i18n_key: str, new_pack_id: str|None).
    """
    ok, err_key, _data = validate_soundpack_folder(source_folder)
    if not ok:
        return False, err_key, None

    base_name = os.path.basename(os.path.normpath(source_folder)) or "soundpack"
    safe_name = "".join(c for c in base_name if c.isalnum() or c in ("-", "_")) or "soundpack"
    dest_id = safe_name
    suffix = 2
    while os.path.exists(os.path.join(sounds_root, dest_id)):
        dest_id = f"{safe_name}_{suffix}"
        suffix += 1

    dest_folder = os.path.join(sounds_root, dest_id)
    try:
        shutil.copytree(source_folder, dest_folder)
    except OSError:
        return False, "soundpack_import_error_copy_failed", None

    return True, "", dest_id


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
