"""Load BASS plugins on macOS.

SoundSystem._load_bass_plugin() looks for Windows .dll files and preloads
them with ctypes.WinDLL, which does not exist off Windows — so on the Mac
the Opus plugin never loaded and WhatsApp voice messages (OGG Opus) could
not play. This maps the plugin names onto the universal .dylib builds in
macos/lib (bundled into the app as lib/) and loads them through sound_lib's
own BASS handle.

AAC needs no plugin on macOS: BASS decodes AAC/MP4/ALAC through CoreAudio.
"""

import logging
import os
import sys

_DYLIBS = {
    "bassopus.dll": "libbassopus.dylib",
    "bass_opus.dll": "libbassopus.dylib",
    "bassflac.dll": "libbassflac.dylib",
    "bassmix.dll": "libbassmix.dylib",
}
_BUILTIN = {"bass_aac.dll", "bassaac.dll", "bass_alac.dll", "bassalac.dll"}


def lib_dirs():
    dirs = []
    if hasattr(sys, "_MEIPASS"):
        dirs.append(os.path.join(sys._MEIPASS, "lib"))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs.append(os.path.join(here, "lib"))
    return dirs


def _load_bass_plugin(self, dll_name):
    if dll_name in _BUILTIN:
        return True
    dylib = _DYLIBS.get(dll_name)
    if not dylib:
        return False
    import ctypes
    from sound_lib.external import pybass
    for d in lib_dirs():
        path = os.path.join(d, dylib)
        if not os.path.isfile(path):
            continue
        fn = pybass.bass_module.BASS_PluginLoad
        fn.restype = ctypes.c_ulong
        fn.argtypes = [ctypes.c_char_p, ctypes.c_ulong]
        handle = fn(path.encode("utf-8"), 0)
        if handle:
            logging.info("[sound_mac] BASS_PluginLoad OK: %s", path)
            return True
        logging.warning("[sound_mac] BASS_PluginLoad failed for %s (BASS error %s)",
                        path, pybass.BASS_ErrorGetCode())
    return False


def find_ffmpeg():
    """The static arm64 ffmpeg bundled with the Mac build (voice-note
    encoding, media probing, video frames), else one on PATH. Upstream's
    search can return the @ffmpeg-installer/ffmpeg *directory* on macOS."""
    import shutil
    for d in lib_dirs():
        path = os.path.join(d, "ffmpeg")
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return shutil.which("ffmpeg")


def install():
    from core import sound_system
    sound_system.SoundSystem._load_bass_plugin = _load_bass_plugin
    from main_window import sending
    sending.SendingMixin._find_api_ffmpeg = staticmethod(find_ffmpeg)
