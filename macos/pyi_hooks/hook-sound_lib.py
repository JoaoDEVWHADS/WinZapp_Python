# Overrides pyinstaller-hooks-contrib's hook, which bundles every file under
# sound_lib/lib — including Windows DLLs and i386-only macOS dylibs that
# PyInstaller cannot process on arm64. The universal BASS dylibs are added by
# macos/build_app.py into sound_lib/lib/x64 instead.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules("sound_lib")
