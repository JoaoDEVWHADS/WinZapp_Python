# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# libopus-0.dll — required for OGG Opus voice message encoding.
# Mirrors the search order used by build.py.
_SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
def _find_opus_dll_spec():
    candidates = [
        os.path.join(_SPEC_DIR, 'lib', 'libopus-0.dll'),
        os.path.join(_SPEC_DIR, 'lib', 'opus.dll'),
        r'C:\msys64\ucrt64\bin\libopus-0.dll',
        r'C:\msys64\mingw64\bin\libopus-0.dll',
        r'C:\msys2\ucrt64\bin\libopus-0.dll',
        r'C:\msys2\mingw64\bin\libopus-0.dll',
        r'C:\ProgramData\chocolatey\bin\libopus-0.dll',
        r'C:\ProgramData\scoop\shims\libopus-0.dll',
    ]
    for _d in os.environ.get('PATH', '').split(os.pathsep):
        if _d:
            candidates.append(os.path.join(_d, 'libopus-0.dll'))
            candidates.append(os.path.join(_d, 'opus.dll'))
    return next((p for p in candidates if os.path.isfile(p)), None)

_opus_dll = _find_opus_dll_spec()
if _opus_dll:
    # dest='lib' places the DLL at _internal/lib/libopus-0.dll in onedir builds.
    # ogg_opus.py searches sys._MEIPASS/lib/ so it will find it there.
    binaries += [(_opus_dll, 'lib')]
tmp_ret = collect_all('sound_lib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('accessible_output2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('platform_utils')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('libloader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('wx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cryptography')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('socketio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('engineio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyperclip')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('packaging')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('windows_toasts')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('winrt')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyaudio')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('aiosqlite')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['C:\\WinZapp\\client\\main.py'],
    pathex=['C:\\WinZapp\\client'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WinZapp',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WinZapp',
)
