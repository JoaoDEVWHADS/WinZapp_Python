"""
WinZapp build script.

Steps:
  1. Check required tools (nuitka, gcc, windres)
  2. Compile client with Nuitka --mode=onefile -> build/WinZapp.exe
       (sounds, languages, lib are external; only Python + wx etc. go inside)
  3. Assemble staging dir: WinZapp.exe + lib/ + sounds/ + languages/ + data/
  4. Compile uninstaller -> build/uninstall.exe
  5. Create payload ZIP (ZIP_STORED) from staging/ + uninstall.exe
  6. Compile installer stub -> build/installer_stub.exe
  7. Append payload ZIP to stub -> dist/WinZappInstaller.exe
  8. Create portable dist/WinZapp.zip (WinZapp/ prefix, ZIP_DEFLATED)

Visible structure after install / extraction:
  WinZapp.exe
  lib/          <- BASS DLLs + screen-reader DLLs (found by sound_lib / ao2)
  sounds/       <- OGG audio files
  languages/    <- JSON translation files
  data/         <- settings_default.json (bootstrap); settings.json created on first run

Usage:
  venv\\Scripts\\python.exe build.py
"""

import os
import sys
import shutil
import subprocess
import zipfile

# -- Paths -------------------------------------------------------------------

ROOT_DIR      = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR    = os.path.join(ROOT_DIR, "client")
INSTALLER_DIR = os.path.join(ROOT_DIR, "installer")
BUILD_DIR     = os.path.join(ROOT_DIR, "build")
DIST_DIR      = os.path.join(ROOT_DIR, "dist")
VENV_DIR      = os.path.join(ROOT_DIR, "venv")

NUITKA_CMD  = os.path.join(VENV_DIR, "Scripts", "nuitka.cmd")
PYTHON_CMD  = os.path.join(VENV_DIR, "Scripts", "python.exe")
GCC_CMD     = "gcc"
WINDRES_CMD = "windres"

# Nuitka onefile output: a single build/WinZapp.exe
NUITKA_EXE      = os.path.join(BUILD_DIR, "WinZapp.exe")

# Staging dir: assembled tree that mirrors the installed layout
STAGING_DIR     = os.path.join(BUILD_DIR, "staging")

PAYLOAD_ZIP     = os.path.join(BUILD_DIR, "payload.zip")
INSTALLER_STUB  = os.path.join(BUILD_DIR, "installer_stub.exe")
INSTALLER_RES   = os.path.join(BUILD_DIR, "installer_res.o")
UNINSTALLER_RES = os.path.join(BUILD_DIR, "uninstaller_res.o")
UNINSTALLER_EXE = os.path.join(BUILD_DIR, "uninstall.exe")
INSTALLER_OUT   = os.path.join(DIST_DIR,  "WinZappInstaller.exe")
PORTABLE_ZIP    = os.path.join(DIST_DIR,  "WinZapp.zip")

SETTINGS_DEFAULT = os.path.join(CLIENT_DIR, "data", "settings_default.json")

SITE_PACKAGES = os.path.join(VENV_DIR, "Lib", "site-packages")
# BASS DLLs (sound_lib) and screen-reader DLLs (accessible_output2) that go in lib/
SOUND_LIB_X64 = os.path.join(SITE_PACKAGES, "sound_lib", "lib", "x64")
AO2_LIB       = os.path.join(SITE_PACKAGES, "accessible_output2", "lib")

# -- Helpers -----------------------------------------------------------------

def step(msg):
    print(f"\n{'-'*60}")
    print(f"  {msg}")
    print('-'*60)

def run(cmd, cwd=None):
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\n[ERROR] Command failed with exit code {result.returncode}.")
        sys.exit(result.returncode)

def walk_dir(root):
    """Yield (absolute_path, relative_path) for every file under root."""
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            abs_path = os.path.join(dirpath, fname)
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
            yield abs_path, rel_path

# -- Step 1: Check tools -----------------------------------------------------

def check_tools():
    step("1/8  Checking required tools")
    missing = []

    if not os.path.isfile(NUITKA_CMD):
        missing.append(f"nuitka  (expected at {NUITKA_CMD})")
    if not os.path.isfile(PYTHON_CMD):
        missing.append(f"python  (expected at {PYTHON_CMD})")

    for tool, name in [(GCC_CMD, "gcc"), (WINDRES_CMD, "windres")]:
        if shutil.which(tool) is None:
            missing.append(f"{name}  (not found in PATH)")

    if missing:
        print("\n[ERROR] Missing required tools:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    print("  All tools found.")

# -- Step 2: Nuitka onefile compile ------------------------------------------

def nuitka_compile():
    step("2/8  Compiling client with Nuitka (--mode=onefile)")

    os.makedirs(BUILD_DIR, exist_ok=True)

    # Remove previous onefile output if present
    if os.path.isfile(NUITKA_EXE):
        os.remove(NUITKA_EXE)

    cmd = [
        NUITKA_CMD,
        "--mode=onefile",
        "--windows-console-mode=disable",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=WinZapp",
        # Extract to a persistent cache location (faster re-launches)
        "--onefile-tempdir-spec={CACHE_DIR}/WinZapp",
        # Packages to include inside the exe
        "--include-package=sound_lib",
        "--include-package=accessible_output2",
        "--include-package=platform_utils",
        "--include-package=libloader",
        "--include-package=wx",
        "--include-package=cryptography",
        "--include-package=requests",
        "--include-package=socketio",
        "--include-package=engineio",
        "--include-package=pyperclip",
        # Exclude BASS DLLs from the exe - they live in the external lib/ folder
        "--noinclude-dlls=bass*.dll",
        "--noinclude-dlls=tags.dll",
        # Entry point
        os.path.join(CLIENT_DIR, "main.py"),
    ]
    run(cmd, cwd=CLIENT_DIR)

    if not os.path.isfile(NUITKA_EXE):
        print(f"[ERROR] Nuitka did not produce {NUITKA_EXE}")
        sys.exit(1)

    size_mb = os.path.getsize(NUITKA_EXE) / (1024 * 1024)
    print(f"  -> {NUITKA_EXE}  ({size_mb:.1f} MB)")

# -- Step 3: Assemble staging dir --------------------------------------------

def assemble_staging():
    step("3/8  Assembling staging distribution")

    # Clean and recreate
    if os.path.isdir(STAGING_DIR):
        shutil.rmtree(STAGING_DIR)
    os.makedirs(STAGING_DIR)

    # WinZapp.exe (the onefile)
    shutil.copy2(NUITKA_EXE, os.path.join(STAGING_DIR, "WinZapp.exe"))

    # lib/ - BASS DLLs from sound_lib
    lib_dir = os.path.join(STAGING_DIR, "lib")
    os.makedirs(lib_dir)
    dll_count = 0
    if os.path.isdir(SOUND_LIB_X64):
        for fname in os.listdir(SOUND_LIB_X64):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(SOUND_LIB_X64, fname),
                             os.path.join(lib_dir, fname))
                dll_count += 1
    # accessible_output2 DLLs (NVDA, SAPI, etc.) - copy if present
    if os.path.isdir(AO2_LIB):
        for fname in os.listdir(AO2_LIB):
            if fname.lower().endswith(".dll"):
                shutil.copy2(os.path.join(AO2_LIB, fname),
                             os.path.join(lib_dir, fname))
                dll_count += 1
    print(f"  -> lib/  ({dll_count} DLLs)")

    # sounds/ - OGG files from client
    sounds_src = os.path.join(CLIENT_DIR, "sounds")
    shutil.copytree(sounds_src, os.path.join(STAGING_DIR, "sounds"))
    sounds_count = len(os.listdir(sounds_src))
    print(f"  -> sounds/  ({sounds_count} files)")

    # languages/ - JSON files from client
    langs_src = os.path.join(CLIENT_DIR, "languages")
    shutil.copytree(langs_src, os.path.join(STAGING_DIR, "languages"))
    langs_count = len(os.listdir(langs_src))
    print(f"  -> languages/  ({langs_count} files)")

    # data/settings_default.json
    data_dir = os.path.join(STAGING_DIR, "data")
    os.makedirs(data_dir)
    shutil.copy2(SETTINGS_DEFAULT, os.path.join(data_dir, "settings_default.json"))
    print(f"  -> data/settings_default.json")

# -- Step 4: Compile uninstaller ---------------------------------------------

def compile_uninstaller():
    step("4/8  Compiling uninstaller")

    run([
        WINDRES_CMD,
        os.path.join(INSTALLER_DIR, "uninstaller.rc"),
        "-o", UNINSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])

    run([
        GCC_CMD,
        os.path.join(INSTALLER_DIR, "uninstaller.c"),
        UNINSTALLER_RES,
        "-o", UNINSTALLER_EXE,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])
    print(f"  -> {UNINSTALLER_EXE}")

# -- Step 5: Create payload ZIP ----------------------------------------------

def create_payload_zip():
    step("5/8  Creating payload ZIP (ZIP_STORED)")

    count = 0
    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
        # All staging files at the ZIP root (preserving sub-folders)
        for abs_path, rel_path in walk_dir(STAGING_DIR):
            zf.write(abs_path, rel_path)
            count += 1
        # Uninstaller at root
        zf.write(UNINSTALLER_EXE, "uninstall.exe")
        count += 1

    size_mb = os.path.getsize(PAYLOAD_ZIP) / (1024 * 1024)
    print(f"  -> {PAYLOAD_ZIP}  ({size_mb:.1f} MB, {count} entries)")

# -- Step 6: Compile installer stub ------------------------------------------

def compile_installer_stub():
    step("6/8  Compiling installer stub")

    run([
        WINDRES_CMD,
        os.path.join(INSTALLER_DIR, "installer.rc"),
        "-o", INSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
        "--preprocessor-arg=-I/c/msys64/ucrt64/include",
    ])

    run([
        GCC_CMD,
        os.path.join(INSTALLER_DIR, "installer.c"),
        INSTALLER_RES,
        "-o", INSTALLER_STUB,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32", "-luuid",
    ])
    print(f"  -> {INSTALLER_STUB}")

# -- Step 7: Append ZIP to stub ----------------------------------------------

def append_zip_to_stub():
    step("7/8  Appending payload to installer stub")
    os.makedirs(DIST_DIR, exist_ok=True)

    with open(INSTALLER_OUT, "wb") as out:
        with open(INSTALLER_STUB, "rb") as stub:
            shutil.copyfileobj(stub, out)
        with open(PAYLOAD_ZIP, "rb") as payload:
            shutil.copyfileobj(payload, out)

    size_mb = os.path.getsize(INSTALLER_OUT) / (1024 * 1024)
    print(f"  -> {INSTALLER_OUT}  ({size_mb:.1f} MB)")

# -- Step 8: Create portable ZIP ---------------------------------------------

def create_portable_zip():
    step("8/8  Creating portable WinZapp.zip")
    os.makedirs(DIST_DIR, exist_ok=True)

    count = 0
    with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for abs_path, rel_path in walk_dir(STAGING_DIR):
            zf.write(abs_path, "WinZapp/" + rel_path)
            count += 1

    size_mb = os.path.getsize(PORTABLE_ZIP) / (1024 * 1024)
    print(f"  -> {PORTABLE_ZIP}  ({size_mb:.1f} MB, {count} entries)")

# -- Main --------------------------------------------------------------------

if __name__ == "__main__":
    print("\nWinZapp Build Script")
    print("=" * 60)

    check_tools()
    nuitka_compile()
    assemble_staging()
    compile_uninstaller()
    create_payload_zip()
    compile_installer_stub()
    append_zip_to_stub()
    create_portable_zip()

    print("\n" + "=" * 60)
    print("  Build complete!")
    print(f"  Installer  : {INSTALLER_OUT}")
    print(f"  Portable   : {PORTABLE_ZIP}")
    print("=" * 60 + "\n")
