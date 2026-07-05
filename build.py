"""
WinZapp build script — PyInstaller QEMU/Docker variant.

Build modes:
  --onedir (default):  PyInstaller builds WinZapp.exe (launcher) and WinZappGUI.exe.
                       Then assemble staging dir + create installer + portable zip.

  --onefile:           PyInstaller builds a single WinZapp.exe with everything embedded.
                       All Python deps + external resources (qemu/, system/, lib/,
                       sounds/, languages/, data/, .env) are embedded in the exe
                       and extracted to a temp directory at runtime.
"""

import os
import sys
import shutil
import subprocess
import zipfile
import argparse
import io
import tarfile
import urllib.request

# -- Paths -------------------------------------------------------------------

ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR    = os.path.join(ROOT_DIR, "client")
INSTALLER_DIR = os.path.join(ROOT_DIR, "installer")
BUILD_DIR     = os.path.join(ROOT_DIR, "build")
DIST_DIR      = os.path.join(ROOT_DIR, "dist")
VENV_DIR      = os.path.join(ROOT_DIR, "venv")

# QEMU and System virtual disk paths
QEMU_DIR      = os.path.join(CLIENT_DIR, "qemu")
SYSTEM_DIR    = os.path.join(CLIENT_DIR, "system")

PYINSTALLER_CMD = os.path.join(VENV_DIR, "Scripts", "pyinstaller.exe")
PYTHON_CMD      = os.path.join(VENV_DIR, "Scripts", "python.exe")
GCC_CMD         = "gcc"
WINDRES_CMD     = "windres"

# PyInstaller output directories
PYINST_OUTDIR   = os.path.join(BUILD_DIR, "pyinstaller_out")
PYINST_LAUNCHER_EXE = os.path.join(PYINST_OUTDIR, "WinZapp", "WinZapp.exe")
PYINST_GUI_EXE      = os.path.join(PYINST_OUTDIR, "WinZappGUI", "WinZappGUI.exe")
PYINST_INTERNAL     = os.path.join(PYINST_OUTDIR, "WinZappGUI", "_internal")

# Onefile output
ONEFILE_EXE     = os.path.join(DIST_DIR, "WinZapp.exe")

# Staging dir (onedir only)
STAGING_DIR     = os.path.join(BUILD_DIR, "staging_pyinstaller")

# Installer paths (onedir only)
PAYLOAD_ZIP     = os.path.join(BUILD_DIR, "payload_pyinstaller.zip")
INSTALLER_STUB  = os.path.join(BUILD_DIR, "installer_stub.exe")
INSTALLER_RES   = os.path.join(BUILD_DIR, "installer_res.o")
UNINSTALLER_RES = os.path.join(BUILD_DIR, "uninstaller_res.o")
UNINSTALLER_EXE = os.path.join(BUILD_DIR, "uninstall.exe")
INSTALLER_OUT   = os.path.join(DIST_DIR,  "WinZappInstaller.exe")
PORTABLE_ZIP    = os.path.join(DIST_DIR,  "WinZapp.zip")

SETTINGS_DEFAULT = os.path.join(CLIENT_DIR, "data", "settings_default.json")

SITE_PACKAGES = os.path.join(VENV_DIR, "Lib", "site-packages")
SOUND_LIB_X64 = os.path.join(SITE_PACKAGES, "sound_lib", "lib", "x64")
AO2_LIB       = os.path.join(SITE_PACKAGES, "accessible_output2", "lib")

def _find_opus_dll_on_disk():
    candidates = [
        os.path.join(CLIENT_DIR, "lib", "libopus-0.dll"),
        os.path.join(CLIENT_DIR, "lib", "opus.dll"),
        r"C:\msys64\ucrt64\bin\libopus-0.dll",
        r"C:\msys64\mingw64\bin\libopus-0.dll",
        r"C:\msys2\ucrt64\bin\libopus-0.dll",
        r"C:\msys2\mingw64\bin\libopus-0.dll",
        r"C:\ProgramData\chocolatey\bin\libopus-0.dll",
        r"C:\ProgramData\scoop\shims\libopus-0.dll",
    ]
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if path_dir:
            candidates.append(os.path.join(path_dir, "libopus-0.dll"))
            candidates.append(os.path.join(path_dir, "opus.dll"))
    return next((p for p in candidates if os.path.isfile(p)), None)

def _download_opus_dll():
    dst_dir = os.path.join(CLIENT_DIR, "lib")
    dst     = os.path.join(dst_dir, "libopus-0.dll")
    print("  [opus] libopus-0.dll not found locally — downloading from MSYS2...")
    try:
        import zstandard
    except ImportError:
        print("  [WARN] 'zstandard' package not installed; cannot auto-download libopus.")
        return None

    api_url = "https://packages.msys2.org/api/packages/ucrt64/mingw-w64-ucrt-x86_64-opus"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "WinZapp-build"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            import json
            info = json.loads(resp.read())
        entry = info[0] if isinstance(info, list) else info
        pkg_filename = entry.get("filename") or entry.get("name") or ""
        pkg_url = entry.get("url") or entry.get("download_url") or (
            f"https://mirror.msys2.org/mingw/ucrt64/{pkg_filename}" if pkg_filename else ""
        )
    except Exception as exc:
        print(f"  [opus] MSYS2 API unavailable ({exc}); using pinned version 1.5.2.")
        pkg_url = "https://mirror.msys2.org/mingw/ucrt64/mingw-w64-ucrt-x86_64-opus-1.5.2-1-any.pkg.tar.zst"

    if not pkg_url:
        return None

    print(f"  [opus] Downloading {pkg_url} ...")
    try:
        req = urllib.request.Request(pkg_url, headers={"User-Agent": "WinZapp-build"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            pkg_data = resp.read()
    except Exception as exc:
        print(f"  [WARN] Download failed: {exc}")
        return None

    print("  [opus] Extracting libopus-0.dll ...")
    try:
        dctx = zstandard.ZstdDecompressor()
        with dctx.stream_reader(io.BytesIO(pkg_data)) as zst_reader:
            with tarfile.open(fileobj=zst_reader) as tar:
                dll_member = next(
                    (m for m in tar.getmembers() if m.name.endswith("/libopus-0.dll") or m.name == "libopus-0.dll"),
                    None
                )
                if dll_member is None:
                    return None
                f = tar.extractfile(dll_member)
                os.makedirs(dst_dir, exist_ok=True)
                with open(dst, "wb") as out:
                    out.write(f.read())
    except Exception as exc:
        print(f"  [WARN] Extraction failed: {exc}")
        return None

    return dst

def _find_opus_dll():
    found = _find_opus_dll_on_disk()
    if found:
        return found
    return _download_opus_dll()

OPUS_DLL = _find_opus_dll()

# -- CLI --------------------------------------------------------------------

parser = argparse.ArgumentParser(description="WinZapp build script — QEMU/Docker variant")
parser.add_argument("--onefile", action="store_true", help="Build single-file .exe with QEMU VM embedded")
args = parser.parse_args()
ONEFILE = args.onefile

def step(msg):
    print(f"\n{'-'*60}")
    print(f"  {msg}")
    print('-'*60)

def run(cmd, cwd=None):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        sys.exit(result.returncode)

def walk_dir(root):
    for dirpath, dirs, files in os.walk(root):
        for fname in files:
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            yield abs_path, rel_path

# -- Step 1: Check tools and pre-built assets --------------------------------

def check_tools():
    step("1/8  Checking required tools and pre-built assets")
    missing = []

    if not os.path.isfile(PYINSTALLER_CMD):
        missing.append(f"pyinstaller  (expected at {PYINSTALLER_CMD})")
    if not os.path.isfile(PYTHON_CMD):
        missing.append(f"python  (expected at {PYTHON_CMD})")

    if not ONEFILE:
        for tool, name in [(GCC_CMD, "gcc"), (WINDRES_CMD, "windres")]:
            if shutil.which(tool) is None:
                missing.append(f"{name}  (not found in PATH)")

    qemu_exe = os.path.join(QEMU_DIR, "qemu-system-x86_64.exe")
    if not os.path.isfile(qemu_exe):
        missing.append(f"client/qemu/qemu-system-x86_64.exe  (not found)")

    disk_img = os.path.join(SYSTEM_DIR, "ubuntu-22.04.qcow2")
    if not os.path.isfile(disk_img):
        missing.append(f"client/system/ubuntu-22.04.qcow2  (not found)")

    if missing:
        print("\n[ERROR] Missing required tools or pre-built assets:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    print("  All tools and assets found.")

# -- Step 2: PyInstaller compile --------------------------------------------

def pyinstaller_compile():
    mode = "onefile" if ONEFILE else "onedir"
    step(f"2/8  Compiling client and launcher with PyInstaller (--{mode})")

    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(DIST_DIR, exist_ok=True)
    
    if not ONEFILE:
        os.makedirs(PYINST_OUTDIR, exist_ok=True)
        for d in [os.path.join(PYINST_OUTDIR, "WinZapp"), os.path.join(PYINST_OUTDIR, "WinZappGUI")]:
            if os.path.isdir(d):
                shutil.rmtree(d)

    work_dir = os.path.join(BUILD_DIR, "pyinstaller_work")

    collect_all = [
        "sound_lib",
        "accessible_output2",
        "platform_utils",
        "libloader",
        "wx",
        "cryptography",
        "requests",
        "socketio",
        "engineio",
        "pyperclip",
        "packaging",
        "windows_toasts",
        "winrt",
        "pyaudio",
        "aiosqlite",
    ]

    # 1. Compile the GUI (main.py -> WinZappGUI.exe)
    print("Compiling WinZappGUI...")
    gui_cmd = [
        PYINSTALLER_CMD,
        "--onefile" if ONEFILE else "--onedir",
        "--windowed",
        "--name", "WinZappGUI",
        "--distpath", DIST_DIR if ONEFILE else PYINST_OUTDIR,
        "--workpath", work_dir,
        "--noconfirm",
    ]
    for pkg in collect_all:
        gui_cmd += ["--collect-all", pkg]
    gui_cmd += ["--paths", CLIENT_DIR]
    gui_cmd.append(os.path.join(CLIENT_DIR, "main.py"))
    run(gui_cmd, cwd=CLIENT_DIR)

    # 2. Compile the Launcher (launcher.py -> WinZapp.exe)
    print("Compiling Launcher...")
    launcher_cmd = [
        PYINSTALLER_CMD,
        "--onefile" if ONEFILE else "--onedir",
        "--windowed",
        "--name", "WinZapp",
        "--distpath", DIST_DIR if ONEFILE else PYINST_OUTDIR,
        "--workpath", work_dir,
        "--noconfirm",
    ]
    launcher_cmd += ["--paths", CLIENT_DIR]

    if ONEFILE:
        # Embed the compiled GUI, QEMU and the QCOW2 system disk directly inside the single Launcher exe
        add_data_pairs = [
            (os.path.join(DIST_DIR, "WinZappGUI.exe"), "."),
            (QEMU_DIR, "qemu"),
            (SYSTEM_DIR, "system"),
            (SOUND_LIB_X64, "lib"),
            (AO2_LIB, "lib"),
            (os.path.join(CLIENT_DIR, "sounds"), "sounds"),
            (os.path.join(CLIENT_DIR, "languages"), "languages"),
            (SETTINGS_DEFAULT, os.path.join("data", "settings_default.json")),
        ]
        if os.path.isfile(os.path.join(CLIENT_DIR, ".env")):
            add_data_pairs.append((os.path.join(CLIENT_DIR, ".env"), ".env"))

        for src, dst in add_data_pairs:
            if os.path.exists(src):
                launcher_cmd += ["--add-data", f"{src};{dst}"]

        if OPUS_DLL:
            launcher_cmd += ["--add-binary", f"{OPUS_DLL};lib"]

    launcher_cmd.append(os.path.join(CLIENT_DIR, "launcher.py"))
    run(launcher_cmd, cwd=CLIENT_DIR)

# -- Step 3: Assemble staging dir (onedir only) -----------------------------

def assemble_staging():
    step("3/8  Assembling staging distribution")

    if os.path.isdir(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
    os.makedirs(STAGING_DIR)

    # Launcher
    shutil.copy2(PYINST_LAUNCHER_EXE, os.path.join(STAGING_DIR, "WinZapp.exe"))
    # GUI
    shutil.copy2(PYINST_GUI_EXE, os.path.join(STAGING_DIR, "WinZappGUI.exe"))
    print("  -> WinZapp.exe & WinZappGUI.exe")

    # Internal libs for GUI
    if os.path.isdir(PYINST_INTERNAL):
        dst_internal = os.path.join(STAGING_DIR, "_internal")
        shutil.copytree(PYINST_INTERNAL, dst_internal)
        print("  -> _internal/")

    # DLLs
    lib_dir = os.path.join(STAGING_DIR, "lib")
    os.makedirs(lib_dir)
    if os.path.isdir(SOUND_LIB_X64):
        for fname in os.listdir(SOUND_LIB_X64):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(SOUND_LIB_X64, fname), os.path.join(lib_dir, fname))
    if os.path.isdir(AO2_LIB):
        for fname in os.listdir(AO2_LIB):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(AO2_LIB, fname), os.path.join(lib_dir, fname))
    if OPUS_DLL:
        shutil.copy2(OPUS_DLL, os.path.join(lib_dir, "libopus-0.dll"))
    
    # bassopus
    _bsrc = os.path.join(CLIENT_DIR, "lib", "bassopus.dll")
    if os.path.isfile(_bsrc):
        shutil.copy2(_bsrc, os.path.join(lib_dir, "bassopus.dll"))

    # Sounds, Languages, default settings
    shutil.copytree(os.path.join(CLIENT_DIR, "sounds"), os.path.join(STAGING_DIR, "sounds"))
    shutil.copytree(os.path.join(CLIENT_DIR, "languages"), os.path.join(STAGING_DIR, "languages"))
    data_dir = os.path.join(STAGING_DIR, "data")
    os.makedirs(data_dir)
    shutil.copy2(SETTINGS_DEFAULT, os.path.join(data_dir, "settings_default.json"))

    client_env = os.path.join(CLIENT_DIR, ".env")
    if os.path.isfile(client_env):
        shutil.copy2(client_env, os.path.join(STAGING_DIR, ".env"))

    # Copy QEMU and the QCOW2 system image instead of Node and API folders
    shutil.copytree(QEMU_DIR, os.path.join(STAGING_DIR, "qemu"))
    shutil.copytree(SYSTEM_DIR, os.path.join(STAGING_DIR, "system"))
    print("  -> Embedded QEMU & System virtual disk successfully.")

# -- Step 4-7: Installer (onedir only) -------------------------------------

def compile_uninstaller():
    step("4/8  Compiling uninstaller")
    run([
        WINDRES_CMD, "--codepage", "65001",
        os.path.join(INSTALLER_DIR, "uninstaller.rc"),
        "-o", UNINSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
    ])
    run([
        GCC_CMD, "-finput-charset=UTF-8", "-fwide-exec-charset=UTF-16LE",
        os.path.join(INSTALLER_DIR, "uninstaller.c"),
        UNINSTALLER_RES, "-o", UNINSTALLER_EXE, "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])

def create_payload_zip():
    step("5/8  Creating payload ZIP (ZIP_STORED)")
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
        for abs_path, rel_path in walk_dir(STAGING_DIR):
            zf.write(abs_path, rel_path)
        zf.write(UNINSTALLER_EXE, "uninstall.exe")

def compile_installer_stub():
    step("6/8  Compiling installer stub")
    run([
        WINDRES_CMD, "--codepage", "65001",
        os.path.join(INSTALLER_DIR, "installer.rc"),
        "-o", INSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
    ])
    run([
        GCC_CMD, "-finput-charset=UTF-8", "-fwide-exec-charset=UTF-16LE",
        os.path.join(INSTALLER_DIR, "installer.c"),
        INSTALLER_RES, "-o", INSTALLER_STUB, "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32", "-luuid",
    ])

def append_zip_to_stub():
    step("7/8  Appending payload to installer stub")
    os.makedirs(DIST_DIR, exist_ok=True)
    with open(INSTALLER_OUT, "wb") as out:
        with open(INSTALLER_STUB, "rb") as stub:
            shutil.copyfileobj(stub, out)
        with open(PAYLOAD_ZIP, "rb") as payload:
            shutil.copyfileobj(payload, out)

# -- Step 8: Create portable ZIP -------------------------------------------

def create_portable_zip():
    step("8/8  Creating portable WinZapp.zip")
    os.makedirs(DIST_DIR, exist_ok=True)

    if ONEFILE:
        with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(ONEFILE_EXE, "WinZapp/WinZapp.exe")
    else:
        with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for abs_path, rel_path in walk_dir(STAGING_DIR):
                zf.write(abs_path, "WinZapp/" + rel_path)

# -- Main --------------------------------------------------------------------

if __name__ == "__main__":
    mode_str = "onefile" if ONEFILE else "onedir"
    print(f"\nWinZapp Build Script — PyInstaller ({mode_str})")
    print("=" * 60)

    if ONEFILE:
        check_tools()
        pyinstaller_compile()
        create_portable_zip()
        print(f"\nOnefile build complete!")
    else:
        check_tools()
        pyinstaller_compile()
        assemble_staging()
        compile_uninstaller()
        create_payload_zip()
        compile_installer_stub()
        append_zip_to_stub()
        create_portable_zip()
        print(f"\nBuild complete!")
