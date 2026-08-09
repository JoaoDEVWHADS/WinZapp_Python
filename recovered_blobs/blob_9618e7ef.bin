"""Per-account audio device selection (client/audio_devices.py).

WinZapp has three independent audio paths, each of which the user can pin to a
specific device per account (plan: audio devices per session, 2 modes):

  * voice_input   — microphone for recording voice messages (PyAudio capture).
  * voice_output  — playback device for voice messages (BASS channel).
  * effects_output— playback device for UI sound effects / alerts (BASS channel).

Devices are stored BY NAME, not index: PortAudio/BASS indices shuffle when a USB
headset is plugged/unplugged, so a saved index would silently point at the wrong
device. We resolve name→index at use time and fall back to the system default
when the saved device is gone.

The pure helpers here (settings normalization, name→choice resolution) are
wx/PyAudio/BASS-free so they unit-test without any audio stack. The thin
enumeration functions that DO touch PyAudio/BASS are guarded and return [] when
the backend is unavailable (e.g. headless CI / WSL), so importing this module is
always safe.
"""

from __future__ import annotations

import logging

# settings["audio_devices"] keys. Value "" (or missing) means "system default".
VOICE_INPUT = "voice_input"
VOICE_OUTPUT = "voice_output"
EFFECTS_OUTPUT = "effects_output"
_KEYS = (VOICE_INPUT, VOICE_OUTPUT, EFFECTS_OUTPUT)

# Sentinel stored/compared for "follow the system default device".
SYSTEM_DEFAULT = ""

# BASS device number for "let BASS pick the default output" (see sound_lib
# Output(device=-1) → use_default_device()). Channels created before any
# explicit device land on device 1 (the first real one); -1 asks BASS to use
# whatever the OS default is.
BASS_DEFAULT_DEVICE = -1


# ── pure helpers (unit-tested, no audio backend) ─────────────────────────────
def normalize_audio_devices(raw) -> dict:
    """Coerce a persisted settings["audio_devices"] blob into the canonical
    {voice_input, voice_output, effects_output} shape with string values.

    Missing/None/non-string values become SYSTEM_DEFAULT ("") so callers never
    have to special-case a half-written or legacy settings file."""
    out = {k: SYSTEM_DEFAULT for k in _KEYS}
    if isinstance(raw, dict):
        for k in _KEYS:
            v = raw.get(k)
            if isinstance(v, str):
                out[k] = v
    return out


def resolve_device_choice(saved_name: str, available: list[str]) -> str:
    """Return the device name to actually use, given the saved preference and
    the list of currently-available device names.

    - "" (SYSTEM_DEFAULT) → "" (use the backend's default device).
    - a saved name that is still present → that name.
    - a saved name that vanished (unplugged) → "" (fall back to default),
      WITHOUT mutating the stored preference, so the device is picked up again
      if it comes back.
    """
    if not saved_name:
        return SYSTEM_DEFAULT
    if saved_name in (available or []):
        return saved_name
    logging.info("[audio] saved device %r not available — falling back to "
                 "system default", saved_name)
    return SYSTEM_DEFAULT


def effective_output_devices(devices: dict) -> tuple[str, str]:
    """(voice_output, effects_output) as stored. Exposed so callers/tests can
    tell whether the two BASS output paths coincide (same device or both
    default) and a single BASS device init can serve both."""
    d = normalize_audio_devices(devices)
    return d[VOICE_OUTPUT], d[EFFECTS_OUTPUT]


def outputs_share_device(devices: dict) -> bool:
    """True when voice and effects want the SAME output (identical name, or
    both system-default). Lets SoundSystem skip initialising a second BASS
    device when there's nothing to separate."""
    voice, effects = effective_output_devices(devices)
    return voice == effects


def _bass_device_names_utf8() -> list[str]:
    """Enumerate BASS output device names decoding as UTF-8.

    sound_lib's Output.get_device_names() decodes with 'mbcs' on Windows, which
    turns non-ASCII names (e.g. Polish diacritics) into mojibake — BASS actually
    returns UTF-8. We read BASS_GetDeviceInfo directly and decode UTF-8 so names
    display correctly. Returns names for enabled devices in BASS device order
    (index 1 = first real device), so a name's position maps to its device
    number via +1 elsewhere. Empty list if BASS is unavailable.
    """
    try:
        import ctypes
        from sound_lib.external.pybass import (
            BASS_GetDeviceInfo, BASS_DEVICEINFO, BASS_DEVICE_ENABLED,
        )
    except Exception:  # pragma: no cover
        return []
    names: list[str] = []
    try:
        info = BASS_DEVICEINFO()
        i = 1
        while BASS_GetDeviceInfo(i, ctypes.byref(info)):
            raw = info.name
            if isinstance(raw, bytes):
                try:
                    name = raw.decode("utf-8")
                except UnicodeDecodeError:
                    name = raw.decode("mbcs", errors="replace")
            else:
                name = raw or ""
            enabled = bool(info.flags & BASS_DEVICE_ENABLED)
            names.append(name.strip() if enabled else "")
            i += 1
    except Exception:  # pragma: no cover
        return []
    return names


# ── backend enumeration (PyAudio / BASS; guarded, safe when unavailable) ─────
def enumerate_input_devices() -> list[str]:
    """Input (microphone) device names via PyAudio. [] if PyAudio can't init.

    De-duplicated preserving order — PortAudio can list the same device under
    several host APIs (MME/WASAPI/DirectSound); we surface each name once."""
    try:
        import pyaudio
    except Exception as exc:  # pragma: no cover - depends on platform
        logging.info("[audio] PyAudio unavailable for input enumeration: %s", exc)
        return []
    names: list[str] = []
    pa = None
    try:
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0)) > 0:
                name = str(info.get("name", "")).strip()
                if name and name not in names:
                    names.append(name)
    except Exception as exc:  # pragma: no cover
        logging.warning("[audio] input enumeration failed: %s", exc)
    finally:
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass
    return names


def enumerate_output_devices() -> list[str]:
    """Output device names via BASS (sound_lib). [] if BASS is unavailable.

    Excludes BASS's synthetic "Default"/"No sound" entries from the *choosable*
    list — the UI offers an explicit "system default" item of its own, and
    "No sound" is never a useful pick. Names are decoded UTF-8 so Polish/other
    diacritics render correctly (not mbcs mojibake)."""
    names = _bass_device_names_utf8()
    skip = {"default", "no sound", ""}
    return [n for n in names if n and n.strip().lower() not in skip]


def input_device_index(name: str):
    """PortAudio device index for a device name, or None for default / not
    found. None is exactly what PyAudio.open(input_device_index=...) wants for
    'use the default input device'."""
    if not name:
        return None
    try:
        import pyaudio
    except Exception:  # pragma: no cover
        return None
    pa = None
    try:
        pa = pyaudio.PyAudio()
        for i in range(pa.get_device_count()):
            try:
                info = pa.get_device_info_by_index(i)
            except Exception:
                continue
            if int(info.get("maxInputChannels", 0)) > 0 and \
                    str(info.get("name", "")).strip() == name:
                return i
    except Exception as exc:  # pragma: no cover
        logging.warning("[audio] input index lookup failed for %r: %s", name, exc)
    finally:
        if pa is not None:
            try:
                pa.terminate()
            except Exception:
                pass
    return None


def bass_output_device(name: str) -> int:
    """BASS device number for an output device name, or BASS_DEFAULT_DEVICE
    (-1) for default / not found. BASS device numbering starts at 1 for the
    first real device, so the name's position in the full device list (+1) is
    its device number. Uses the UTF-8 enumeration so a name with diacritics
    matches the same string the UI stored."""
    if not name:
        return BASS_DEFAULT_DEVICE
    try:
        names = _bass_device_names_utf8()  # positional: index i → device i+1
        return names.index(name) + 1
    except Exception:
        return BASS_DEFAULT_DEVICE
