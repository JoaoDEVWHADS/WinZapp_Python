"""Enumeration and selection helpers for the Settings > Audio Devices tab.

Output (playback) device switching goes through sound_lib/BASS — a single
process-wide `Output` device, shared by every stream anywhere in the app
(program sounds, conversation audio, status audio). Input (recording) device
selection only affects PyAudio, used solely for voice-message recording in
`ui/conversations.py`.

Devices are stored in settings by friendly name, not raw index — BASS/PortAudio
device indices are not stable across reboots or device (dis)connections, so a
name is resolved back to the current index each time it's needed.
"""

import ctypes
import logging

import pyaudio


def _match_device(name: str, devices: list):
    """Return the index of the device named `name` in `devices`
    ([(index, friendly_name), ...]), or None if absent/empty."""
    if not name:
        return None
    for idx, dev_name in devices:
        if dev_name == name:
            return idx
    return None


def enumerate_output_devices() -> list:
    """[(bass_device_index, friendly_name), ...] for enabled BASS output
    devices (excludes BASS's special device 0, "No sound", and its "Default"
    pseudo-device — BASS always lists a device literally named "Default"
    ahead of the real hardware entries, which would otherwise show up as a
    second, redundant "use the default" choice alongside the combo's own
    sentinel first entry).

    Written directly against BASS_GetDeviceInfo rather than reusing
    sound_lib.output.Output.get_device_names()/find_device_by_name(): those
    assume the returned (gap-free) name list's position + 1 equals the real
    BASS device index, which only holds if no disabled device was skipped
    during enumeration — not something we can rely on.
    """
    from sound_lib.external.pybass import BASS_DEVICEINFO, BASS_GetDeviceInfo, BASS_DEVICE_ENABLED

    devices = []
    info = BASS_DEVICEINFO()
    count = 1
    while BASS_GetDeviceInfo(count, ctypes.byref(info)):
        if info.flags & BASS_DEVICE_ENABLED:
            name = info.name
            if isinstance(name, bytes):
                name = name.decode("mbcs")
            name = name.replace("(", "").replace(")", "").strip()
            if name.lower() != "default":
                devices.append((count, name))
        count += 1
    return devices


def _pyaudio_input_devices(pa: "pyaudio.PyAudio") -> list:
    """[(device_index, friendly_name), ...] for input-capable devices,
    preferring the WASAPI host API: its device names/order match Windows'
    own Sound control panel (mmsys.cpl), whereas MME truncates names to 31
    characters and DirectSound duplicates the whole device list."""
    try:
        host_api = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
    except Exception:
        host_api = pa.get_default_host_api_info()

    devices = []
    for i in range(host_api.get("deviceCount", 0)):
        try:
            info = pa.get_device_info_by_host_api_device_index(host_api["index"], i)
        except Exception:
            continue
        if info.get("maxInputChannels", 0) > 0:
            devices.append((info["index"], str(info["name"]).strip()))
    return devices


def enumerate_input_devices(pa: "pyaudio.PyAudio | None" = None) -> list:
    """[(device_index, friendly_name), ...] for input-capable devices. Opens
    a temporary PyAudio instance if `pa` isn't supplied."""
    owns_pa = pa is None
    if owns_pa:
        pa = pyaudio.PyAudio()
    try:
        return _pyaudio_input_devices(pa)
    finally:
        if owns_pa:
            try:
                pa.terminate()
            except Exception:
                pass


def find_output_device_index(name: str):
    """Resolve a stored output device name to its current BASS device index,
    or None if empty/not currently present."""
    if not name:
        return None
    return _match_device(name, enumerate_output_devices())


def find_input_device_index(name: str, pa: "pyaudio.PyAudio | None" = None):
    """Resolve a stored input device name to its current PyAudio device
    index, or None if empty/not currently present."""
    if not name:
        return None
    return _match_device(name, enumerate_input_devices(pa))


# Sample-rate/channel combinations to try opening an input device with, in
# preference order — must mirror ui/conversations.py's _start_voice_recording()
# fallback chain exactly. A single hardcoded (rate, channels) pair doesn't
# work as a general "can this device open" test: most WASAPI devices only
# accept their own native rate (48000 on every device tested), rejecting
# 44100 outright with "Invalid sample rate" — every non-default recording
# device used to fail Settings validation for exactly this reason, the
# device itself was never actually at fault.
RECORDING_SAMPLE_CONFIGS = [(48000, 1), (48000, 2), (44100, 1), (44100, 2)]


def test_input_device(device_index: int) -> bool:
    """Try to briefly open (without starting) an input stream on
    `device_index`, across every sample-rate/channel combo recording itself
    would try. Returns True if any combo was accepted."""
    pa = pyaudio.PyAudio()
    try:
        for rate, channels in RECORDING_SAMPLE_CONFIGS:
            try:
                stream = pa.open(
                    rate=rate,
                    channels=channels,
                    format=pyaudio.paInt16,
                    input=True,
                    input_device_index=device_index,
                    frames_per_buffer=1024,
                    start=False,
                )
                stream.close()
                return True
            except Exception:
                continue
        logging.warning(
            "[audio_devices] Input device test failed for every sample-rate/channel combo (index=%s)",
            device_index,
        )
        return False
    finally:
        try:
            pa.terminate()
        except Exception:
            pass
