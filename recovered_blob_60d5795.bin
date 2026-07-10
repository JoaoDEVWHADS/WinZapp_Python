"""
WinZapp build script.

Steps:
  1. Check required tools (nuitka, gcc, windres)
  2. Compile client with Nuitka → build/WinZapp.dist/
  3. Copy sound_lib and accessible_output2 DLLs into build/WinZapp.dist/
  4. Compile uninstaller → build/uninstall.exe
  5. Create payload ZIP (ZIP_STORED) from build/WinZapp.dist/ + uninstall.exe
  6. Compile installer stub → build/installer_stub.exe
  7. Append payload ZIP to stub → dist/WinZappInstaller.exe
  8. Create portable dist/WinZapp.zip (ZIP_DEFLATED, WinZapp/ prefix)

Usage:
  venv\\Scripts\\python.exe build.py
"""

import os
import sys
import shutil
import subprocess
import zipfile
import glob

# ── Paths ────────────────────────────────────────────────────────────────

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

NUITKA_OUTPUT_DIR = os.path.join(BUILD_DIR, "WinZapp.dist")
PAYLOAD_ZIP       = os.path.join(BUILD_DIR, "payload.zip")
INSTALLER_STUB    = os.path.join(BUILD_DIR, "installer_stub.exe")
INSTALLER_RES     = os.path.join(BUILD_DIR, "installer_res.o")
UNINSTALLER_RES   = os.path.join(BUILD_DIR, "uninstaller_res.o")
UNINSTALLER_EXE   = os.path.join(BUILD_DIR, "uninstall.exe")
INSTALLER_OUT     = os.path.join(DIST_DIR,  "WinZappInstaller.exe")
PORTABLE_ZIP      = os.path.join(DIST_DIR,  "WinZapp.zip")

# DLL source directories (inside venv site-packages)
SITE_PACKAGES = os.path.join(VENV_DIR, "Lib", "site-packages")
SOUND_LIB_DLLS = os.path.join(SITE_PACKAGES, "sound_lib", "lib", "x64")
AO2_DLLS       = os.path.join(SITE_PACKAGES, "accessible_output2", "lib")

# ── Helpers ──────────────────────────────────────────────────────────────

def step(msg):
    print(f"\n{'─'*60}")
    print(f"  {msg}")
    print('─'*60)

def run(cmd, cwd=None):
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"\n[ERROR] Command failed with exit code {result.returncode}.")
        sys.exit(result.returncode)

# ── Step 1: Check tools ───────────────────────────────────────────────────

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

# ── Step 2: Nuitka compile ─────────────────────────────────────────────────

def nuitka_compile():
    step("2/8  Compiling client with Nuitka")

    # Clean previous output
    if os.path.exists(NUITKA_OUTPUT_DIR):
        shutil.rmtree(NUITKA_OUTPUT_DIR)
    os.makedirs(BUILD_DIR, exist_ok=True)

    cmd = [
        NUITKA_CMD,
        "--standalone",
        "--onedir",
        "--windows-console-mode=disable",
        "--output-dir=" + BUILD_DIR,
        "--output-filename=WinZapp",
        "--include-package=sound_lib",
        "--include-package=accessible_output2",
        "--include-package=wx",
        "--include-package=cryptography",
        "--include-package=requests",
        "--include-package=socketio",
        "--include-package=engineio",
        "--include-package=accessible_output2",
        "--include-data-dir=" + os.path.join(CLIENT_DIR, "sounds") + "=sounds",
        "--include-data-dir=" + os.path.join(CLIENT_DIR, "languages") + "=languages",
        os.path.join(CLIENT_DIR, "main.py"),
    ]
    run(cmd, cwd=CLIENT_DIR)

# ── Step 3: Copy DLLs ─────────────────────────────────────────────────────

def copy_dlls():
    step("3/8  Copying DLLs into build/WinZapp.dist/")
    dest = NUITKA_OUTPUT_DIR

    if not os.path.isdir(dest):
        print(f"[ERROR] Nuitka output directory not found: {dest}")
        sys.exit(1)

    copied = 0
    for src_dir, pattern in [
        (SOUND_LIB_DLLS, "*.dll"),
        (AO2_DLLS,       "*.dll"),
    ]:
        if not os.path.isdir(src_dir):
            print(f"  [WARN] DLL source directory not found: {src_dir}")
            continue
        for dll in glob.glob(os.path.join(src_dir, pattern)):
            dst = os.path.join(dest, os.path.basename(dll))
            shutil.copy2(dll, dst)
            print(f"  copied {os.path.basename(dll)}")
            copied += 1

    print(f"  {copied} DLL(s) copied.")

# ── Step 4: Compile uninstaller ────────────────────────────────────────────

def compile_uninstaller():
    step("4/8  Compiling uninstaller")
    os.makedirs(BUILD_DIR, exist_ok=True)

    # Compile resource file
    run([
        WINDRES_CMD,
        os.path.join(INSTALLER_DIR, "uninstaller.rc"),
        "-o", UNINSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
    ])

    # Compile and link
    run([
        GCC_CMD,
        os.path.join(INSTALLER_DIR, "uninstaller.c"),
        UNINSTALLER_RES,
        "-o", UNINSTALLER_EXE,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])
    print(f"  → {UNINSTALLER_EXE}")

# ── Step 5: Create payload ZIP ─────────────────────────────────────────────

def create_payload_zip():
    step("5/8  Creating payload ZIP (ZIP_STORED)")

    if not os.path.isdir(NUITKA_OUTPUT_DIR):
        print(f"[ERROR] Nuitka output not found: {NUITKA_OUTPUT_DIR}")
        sys.exit(1)

    with zipfile.ZipFile(PAYLOAD_ZIP, "w", compression=zipfile.ZIP_STORED) as zf:
        # Add all files from WinZapp.dist/ under "app/" prefix
        for dirpath, dirnames, filenames in os.walk(NUITKA_OUTPUT_DIR):
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, NUITKA_OUTPUT_DIR)
                arc_name = "app\\" + rel_path
                zf.write(full_path, arc_name)

        # Add uninstaller
        if os.path.isfile(UNINSTALLER_EXE):
            zf.write(UNINSTALLER_EXE, "uninstall.exe")
        else:
            print("  [WARN] uninstall.exe not found, skipping.")

    size_mb = os.path.getsize(PAYLOAD_ZIP) / (1024 * 1024)
    print(f"  → {PAYLOAD_ZIP}  ({size_mb:.1f} MB)")

# ── Step 6: Compile installer stub ────────────────────────────────────────

def compile_installer_stub():
    step("6/8  Compiling installer stub")

    # Compile resource file
    run([
        WINDRES_CMD,
        os.path.join(INSTALLER_DIR, "installer.rc"),
        "-o", INSTALLER_RES,
        "--include-dir", INSTALLER_DIR,
    ])

    # Compile and link
    run([
        GCC_CMD,
        os.path.join(INSTALLER_DIR, "installer.c"),
        INSTALLER_RES,
        "-o", INSTALLER_STUB,
        "-mwindows",
        "-I", INSTALLER_DIR,
        "-lole32", "-lshell32", "-lcomctl32", "-lshlwapi", "-ladvapi32",
    ])
    print(f"  → {INSTALLER_STUB}")

# ── Step 7: Append ZIP to stub ─────────────────────────────────────────────

def append_zip_to_stub():
    step("7/8  Appending payload to installer stub")
    os.makedirs(DIST_DIR, exist_ok=True)

    with open(INSTALLER_OUT, "wb") as out:
        with open(INSTALLER_STUB, "rb") as stub:
            shutil.copyfileobj(stub, out)
        with open(PAYLOAD_ZIP, "rb") as payload:
            shutil.copyfileobj(payload, out)

    size_mb = os.path.getsize(INSTALLER_OUT) / (1024 * 1024)
    print(f"  → {INSTALLER_OUT}  ({size_mb:.1f} MB)")

# ── Step 8: Create portable ZIP ───────────────────────────────────────────

def create_portable_zip():
    step("8/8  Creating portable WinZapp.zip")
    os.makedirs(DIST_DIR, exist_ok=True)

    with zipfile.ZipFile(PORTABLE_ZIP, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6) as zf:
        for dirpath, dirnames, filenames in os.walk(NUITKA_OUTPUT_DIR):
            for fname in filenames:
                full_path = os.path.join(dirpath, fname)
                rel_path = os.path.relpath(full_path, NUITKA_OUTPUT_DIR)
                arc_name = os.path.join("WinZapp", rel_path)
                zf.write(full_path, arc_name)

    size_mb = os.path.getsize(PORTABLE_ZIP) / (1024 * 1024)
    print(f"  → {PORTABLE_ZIP}  ({size_mb:.1f} MB)")

# ── Main ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nWinZapp Build Script")
    print("=" * 60)

    check_tools()
    nuitka_compile()
    copy_dlls()
    compile_uninstaller()
    create_payload_zip()
    compile_installer_stub()
    append_zip_to_stub()
    create_portable_zip()

    print("\n" + "=" * 60)
    print("  Build complete!")
    print(f"  Installer : {INSTALLER_OUT}")
    print(f"  Portable  : {PORTABLE_ZIP}")
    print("=" * 60 + "\n")
